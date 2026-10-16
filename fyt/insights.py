"""The analytics feedback loop: learn from what viewers actually watched.

Once a week (`insights.refresh_days`) the free YouTube Analytics API is read for the channel's recent
videos: average percentage viewed, how well the opening holds (the retention curve at 10% of the video)
and, for Shorts, how many viewers swipe away (1 - engaged views / views; YouTube counts a Short's view
as engaged once it has been watched past its first seconds). Each video is compared with the median of
its own format, and the comparisons are grouped by what the pipeline chose for it: pillar (category),
story shape and title style (store.Uploads.describe records those at upload).

The lessons feed three choices:
- topic: a pillar viewers stay with gets a little more of the content mix, one they leave a little less
  (bounded, x0.8..x1.25 by default; the mix itself and the Christian calendar stay in charge);
- title: title styles that held viewers are tried first, ones that lost them last (never removed);
- script: plain notes on delivery (the hook, pacing) go into the script prompt.

Bible first, emotion second: lessons shape delivery and the order ideas come in. They never change what
a passage says, which passages are used, or how the faithfulness review judges a script.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from statistics import mean, median

from fyt.config import Config
from fyt.store import Uploads

NOTE = "insights"
GUARD = (
    "These lessons are about delivery only (the opening, pacing, packaging). They never change what the "
    "passage says or means, which Scripture is used, or what the title may promise."
)
HOOK_POINT = 0.1  # the retention curve is read at 10% of the video: how well the opening holds


# --- Reading YouTube Analytics ------------------------------------------------------


def fetch(cfg: Config, now: datetime) -> list[dict]:
    """Per-video analytics for the lookback window: id, views, view_pct, avg_seconds, engaged (or None),
    and hook (audience watch ratio at 10%, for the newest long videos)."""
    from fyt import youtube

    yt = youtube.analytics_service()
    end = (now - timedelta(days=1)).date()  # yesterday: today's numbers are incomplete
    start = end - timedelta(days=cfg.insights.lookback_days)
    query = dict(
        ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
        dimensions="video", sort="-views", maxResults=200,
    )
    try:
        resp = yt.reports().query(metrics="views,averageViewPercentage,averageViewDuration,engagedViews", **query).execute()
    except Exception as e:  # engaged views are newer than the rest; read the others without them
        if "accessNotConfigured" in str(e) or "has not been used in project" in str(e):
            raise RuntimeError(
                "the YouTube Analytics API is not enabled in your Google Cloud project: enable it at "
                "https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com and retry"
            ) from None
        print(f"note: engaged views not available ({str(e)[:120]}); swipe-away can't be measured")
        resp = yt.reports().query(metrics="views,averageViewPercentage,averageViewDuration", **query).execute()
    names = [h["name"] for h in resp.get("columnHeaders", [])]
    rows = [dict(zip(names, r)) for r in resp.get("rows", []) or []]
    out = [
        {
            "id": r["video"],
            "views": int(r.get("views", 0)),
            "view_pct": float(r.get("averageViewPercentage", 0)),
            "avg_seconds": float(r.get("averageViewDuration", 0)),
            "engaged": int(r["engagedViews"]) if "engagedViews" in r else None,
            "hook": None,
        }
        for r in rows
    ]
    kinds = Uploads(cfg).kinds()
    longs = [r for r in out if kinds.get(r["id"]) == "long" and r["views"] >= cfg.insights.min_views]
    for r in longs[: cfg.insights.retention_videos]:
        try:
            r["hook"] = hook_hold(yt, r["id"], start.isoformat(), end.isoformat())
        except Exception as e:  # one curve missing doesn't matter
            print(f"note: no retention curve for {r['id']}: {str(e)[:120]}")
    return out


def hook_hold(yt, video_id: str, start: str, end: str) -> float | None:
    """Share of viewers still watching at 10% of the video (audienceWatchRatio)."""
    resp = yt.reports().query(
        ids="channel==MINE", startDate=start, endDate=end, metrics="audienceWatchRatio",
        dimensions="elapsedVideoTimeRatio", filters=f"video=={video_id}",
    ).execute()
    points = [(float(r[0]), float(r[1])) for r in resp.get("rows", []) or []]
    if not points:
        return None
    return min(points, key=lambda p: abs(p[0] - HOOK_POINT))[1]


# --- Turning numbers into lessons (pure: no network) ---------------------------------


def swipe_away(row: dict) -> float | None:
    if row.get("engaged") is None or not row.get("views"):
        return None
    return max(0.0, 1 - row["engaged"] / row["views"])


def score(row: dict, fmt: str) -> float:
    """How well a video held its viewers. Shorts: the share who stayed past the first seconds (or the
    average percentage viewed, capped, when that isn't known); long videos: average percentage viewed."""
    if fmt == "short":
        s = swipe_away(row)
        return (1 - s) * 100 if s is not None else min(row["view_pct"], 150.0)
    return row["view_pct"]


def lessons(cfg: Config, rows: list[dict], meta: dict[str, dict], now: datetime) -> dict:
    """Lessons from analytics rows and what each video was (meta: youtube_id -> {format, category,
    shape, title_style, title...})."""
    ic = cfg.insights
    rows = [r for r in rows if r["views"] >= ic.min_views and meta.get(r["id"], {}).get("format") in ("short", "long")]
    by_fmt: dict[str, list[dict]] = {"short": [], "long": []}
    for r in rows:
        by_fmt[meta[r["id"]]["format"]].append(r)
    formats, lifts = {}, {}
    for fmt, group in by_fmt.items():
        if not group:
            continue
        mid = median(score(r, fmt) for r in group) or 1.0
        for r in group:
            lifts[r["id"]] = score(r, fmt) / mid
        swipes = [s for s in (swipe_away(r) for r in group) if s is not None]
        hooks = [r["hook"] for r in group if r.get("hook") is not None]
        formats[fmt] = {
            "videos": len(group),
            "median_view_pct": round(median(r["view_pct"] for r in group), 1),
            "median_swipe_away": round(median(swipes), 3) if swipes else None,
            "median_hook_hold": round(median(hooks), 3) if hooks else None,
        }

    def grouped(field: str) -> dict[str, dict]:
        groups: dict[str, list[float]] = {}
        for vid, lift in lifts.items():
            key = meta[vid].get(field)
            if key:
                groups.setdefault(key, []).append(lift)
        return {k: {"lift": round(mean(v), 3), "videos": len(v)} for k, v in sorted(groups.items())}

    def card(r: dict) -> dict:
        m = meta[r["id"]]
        return {
            "id": r["id"], "title": m.get("title") or r["id"], "format": m["format"], "views": r["views"],
            "view_pct": round(r["view_pct"], 1), "swipe_away": swipe_away(r), "category": m.get("category"),
        }

    ranked = sorted(rows, key=lambda r: lifts[r["id"]], reverse=True)
    out = {
        "updated": now.isoformat(timespec="seconds"),
        "videos": len(rows),
        "formats": formats,
        "categories": grouped("category"),
        "shapes": grouped("shape"),
        "title_styles": grouped("title_style"),
        "best": [card(r) for r in ranked[:3]],
        "worst": [card(r) for r in ranked[-3:][::-1]] if len(ranked) > 3 else [],
    }
    out["notes"] = {fmt: _notes(cfg, out, fmt) for fmt in ("short", "long")}
    return out


def _notes(cfg: Config, lz: dict, fmt: str) -> str:
    """What the script writer should know about this format, in plain words ("" when nothing stands out)."""
    f = lz["formats"].get(fmt)
    if not f:
        return ""
    lines = []
    if fmt == "short":
        s = f.get("median_swipe_away")
        if s is not None and s >= 0.4:
            lines.append(
                f"About {s:.0%} of viewers swipe away in the first seconds. The first line must already be the moment "
                "itself (the feeling, or the story at its point of tension): no scene-setting, no preamble."
            )
        if f["median_view_pct"] < 70:
            lines.append(
                f"Viewers watch {f['median_view_pct']:.0f}% of a Short on average: every line must move towards the "
                "Scripture and its meaning; cut any sentence that only repeats."
            )
    else:
        h = f.get("median_hook_hold")
        if h is not None and h < 0.65:
            lines.append(
                f"Only {h:.0%} of viewers are still watching a tenth of the way in. Within the first 20 seconds, "
                "let them know what this video will give them, and step into the story quickly."
            )
        if f["median_view_pct"] < 35:
            lines.append(
                f"Viewers watch {f['median_view_pct']:.0f}% of a long video on average: keep scenes short, bring the "
                "story's tension earlier, and don't linger on background."
            )
    good = [(k, v) for k, v in lz["shapes"].items() if v["videos"] >= cfg.insights.min_videos and v["lift"] >= 1.1]
    if good:
        k, v = max(good, key=lambda kv: kv[1]["lift"])
        lines.append(
            f"Videos shaped as '{k}' hold viewers best so far ({v['lift'] - 1:.0%} above the channel's usual): "
            "where this passage allows, let its moments land the same way."
        )
    if not lines:
        return ""
    return "\n".join(f"- {line}" for line in lines) + f"\n{GUARD}"


# --- Stored lessons and how the pipeline uses them -------------------------------


def current(cfg: Config) -> dict:
    """The last computed lessons ({} before the first refresh, or when the loop is off)."""
    if not cfg.insights.enabled or not (cfg.jobs_path / "state.db").exists():
        return {}
    raw = Uploads(cfg).note(NOTE)
    return json.loads(raw) if raw else {}


def due(cfg: Config, now: datetime) -> bool:
    last = current(cfg).get("updated")
    return not last or datetime.fromisoformat(last) <= now - timedelta(days=cfg.insights.refresh_days)


def refresh(cfg: Config, now: datetime | None = None, force: bool = False) -> dict | None:
    """Recompute the lessons when a week has passed (or force). Returns them, or None when skipped."""
    from fyt import youtube

    now = now or datetime.now(timezone.utc)
    if not cfg.insights.enabled or not (force or due(cfg, now)):
        return None
    if not youtube.can_analyze():
        print("note: insights need the YouTube Analytics permission: run `python -m fyt auth` again and "
              "update the YOUTUBE_TOKEN_JSON secret (see SETUP.md)")
        return None
    uploads = Uploads(cfg)
    meta = uploads.described()
    for vid, kind in uploads.kinds().items():  # videos from before the loop existed: their format at least
        meta.setdefault(vid, {"format": kind})
    lz = lessons(cfg, fetch(cfg, now), meta, now)
    uploads.set_note(NOTE, json.dumps(lz))
    print(f"insights: learned from {lz['videos']} videos")
    return lz


def category_weights(cfg: Config) -> dict[str, float]:
    """Pillar -> multiplier on its share of the content mix (only pillars with enough videos)."""
    ic = cfg.insights
    return {
        k: round(min(ic.max_weight, max(ic.min_weight, v["lift"])), 3)
        for k, v in current(cfg).get("categories", {}).items()
        if v["videos"] >= ic.min_videos
    }


def title_preferences(cfg: Config) -> tuple[list[str], list[str]]:
    """(styles to try first, styles to try last), best and worst first."""
    styles = [(k, v) for k, v in current(cfg).get("title_styles", {}).items() if v["videos"] >= cfg.insights.min_videos]
    prefer = [k for k, v in sorted(styles, key=lambda kv: -kv[1]["lift"]) if v["lift"] >= 1.1]
    avoid = [k for k, v in sorted(styles, key=lambda kv: kv[1]["lift"]) if v["lift"] <= 0.85]
    return prefer, avoid


def script_notes(cfg: Config, fmt: str) -> str:
    return current(cfg).get("notes", {}).get(fmt, "")


def summary(cfg: Config) -> str:
    """Best and weakest videos by how well they held viewers, for topic ideation."""
    lz = current(cfg)

    def line(c: dict) -> str:
        s = f", {c['swipe_away']:.0%} swiped away" if c.get("swipe_away") is not None else ""
        return f"- {c['title']} ({c['format']}): {c['views']} views, {c['view_pct']}% viewed{s}"

    if not lz.get("best"):
        return ""
    out = ["Held viewers best:", *map(line, lz["best"])]
    if lz.get("worst"):
        out += ["Lost viewers soonest:", *map(line, lz["worst"])]
    return "\n".join(out)


def report(cfg: Config) -> str:
    """The lessons as text, for `fyt insights`."""
    lz = current(cfg)
    if not lz:
        return "no insights yet: they need the analytics permission and some uploaded videos (`fyt insights --refresh`)"
    out = [f"Insights from {lz['videos']} videos (updated {lz['updated']})", ""]
    for fmt, f in lz["formats"].items():
        extra = ""
        if f.get("median_swipe_away") is not None:
            extra += f", {f['median_swipe_away']:.0%} swipe away"
        if f.get("median_hook_hold") is not None:
            extra += f", {f['median_hook_hold']:.0%} still watching at 10%"
        out.append(f"{fmt}: {f['videos']} videos, {f['median_view_pct']}% viewed (median){extra}")
    for title, key in (("Pillars", "categories"), ("Story shapes", "shapes"), ("Title styles", "title_styles")):
        if lz.get(key):
            out += ["", f"{title} (1.00 = the channel's usual):"]
            out += [f"  {k:<18} {v['lift']:.2f}  ({v['videos']} videos)" for k, v in sorted(lz[key].items(), key=lambda kv: -kv[1]["lift"])]
    w = category_weights(cfg)
    if w:
        out += ["", "Content mix nudges: " + ", ".join(f"{k} x{v}" for k, v in sorted(w.items()))]
    prefer, avoid = title_preferences(cfg)
    if prefer or avoid:
        out += [f"Title styles tried first: {', '.join(prefer) or '-'}; last: {', '.join(avoid) or '-'}"]
    for fmt, notes in lz.get("notes", {}).items():
        if notes:
            out += ["", f"Script notes ({fmt}):", notes]
    summ = summary(cfg)
    if summ:
        out += ["", summ]
    return "\n".join(out)
