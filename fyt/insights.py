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

Story-first: each video also records its content pillar, visual style and slate (evergreen / timely),
and the lessons compare those on click-through rate, how many viewers are still there at 30 seconds,
average view duration, the share of views from subscribers (the API's nearest stand-in for returning
viewers) and the share from Browse features and Suggested videos (`fyt insights` shows the table).

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
WINNER_LIFT = 1.2  # kept as a winner (bonus.min_lift picks which get follow-ups)
HOOK_POINT = 0.1  # the retention curve is read at 10% of the video: how well the opening holds
HOLD_SECONDS = 30  # and at 30 seconds: the first-30-seconds retention of a long video
# insightTrafficSourceType values: SUBSCRIBER is "Browse features" in YouTube Studio, RELATED_VIDEO "Suggested videos".
BROWSE, SUGGESTED = "SUBSCRIBER", "RELATED_VIDEO"
COMPARED = ("ctr", "hold30", "avg_seconds", "subscribed", "browse", "suggested")


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
            **{k: None for k in COMPARED if k != "avg_seconds"},
        }
        for r in rows
    ]
    try:  # thumbnail click-through rate (YouTube reports a percentage; kept as a share), one request for every video
        imp = yt.reports().query(
            **{**query, "sort": "-videoThumbnailImpressions"},
            metrics="videoThumbnailImpressions,videoThumbnailImpressionsClickRate",
        ).execute()
        names = [h["name"] for h in imp.get("columnHeaders", [])]
        ctr = {d["video"]: float(d["videoThumbnailImpressionsClickRate"]) / 100 for d in (dict(zip(names, r)) for r in imp.get("rows", []) or [])
               if "videoThumbnailImpressionsClickRate" in d}
        for r in out:
            r["ctr"] = ctr.get(r["id"])
    except Exception as e:
        print(f"note: no thumbnail click-through rate ({str(e)[:120]})")
    uploads = Uploads(cfg)
    kinds, described = uploads.kinds(), uploads.described()
    longs = [r for r in out if kinds.get(r["id"]) == "long" and r["views"] >= cfg.insights.min_views]
    for r in longs[: cfg.insights.retention_videos]:
        try:
            curve = retention_curve(yt, r["id"], start.isoformat(), end.isoformat())
            r["hook"] = at_point(curve, HOOK_POINT)
            seconds = described.get(r["id"], {}).get("duration") or 60 * (described.get(r["id"], {}).get("minutes") or 0)
            r["hold30"] = at_point(curve, HOLD_SECONDS / seconds) if seconds else None
        except Exception as e:  # one curve missing doesn't matter
            print(f"note: no retention curve for {r['id']}: {str(e)[:120]}")
    for r in [r for r in out if r["views"] >= cfg.insights.min_views][: cfg.insights.retention_videos]:
        try:
            r.update(audience(yt, r["id"], start.isoformat(), end.isoformat()))
        except Exception as e:
            print(f"note: no traffic sources for {r['id']}: {str(e)[:120]}")
    return out


def _shares(resp: dict) -> dict[str, float]:
    rows = [(str(r[0]), float(r[1])) for r in resp.get("rows", []) or []]
    total = sum(v for _, v in rows) or 1.0
    shares: dict[str, float] = {}
    for k, v in rows:
        shares[k] = shares.get(k, 0.0) + v / total
    return shares


def audience(yt, video_id: str, start: str, end: str) -> dict:
    """Where a video's views came from: shares from Browse features, Suggested videos and subscribers."""
    base = dict(ids="channel==MINE", startDate=start, endDate=end, metrics="views", filters=f"video=={video_id}")
    traffic = _shares(yt.reports().query(dimensions="insightTrafficSourceType", **base).execute())
    status = _shares(yt.reports().query(dimensions="subscribedStatus", **base).execute())
    return {
        "browse": round(traffic.get(BROWSE, 0.0), 3),
        "suggested": round(traffic.get(SUGGESTED, 0.0), 3),
        "subscribed": round(status.get("SUBSCRIBED", 0.0), 3),
    }


# Where the translated titles (localize.languages) are spoken, to see which language groups find the channel.
LANGUAGE_COUNTRIES = {
    "es": {"MX", "ES", "AR", "CO", "PE", "VE", "CL", "EC", "GT", "CU", "BO", "DO", "HN", "PY", "SV", "NI", "CR", "PA", "UY", "PR"},
    "pt": {"BR", "PT", "AO", "MZ"},
    "fr": {"FR", "CI", "CD", "CM", "SN", "BF", "ML", "BJ", "TG", "GA", "CG", "HT", "BE", "CH", "MG", "RW", "BI"},
    "fil": {"PH"},
    "ko": {"KR"},
}


def countries(cfg: Config, now: datetime, yt=None) -> list[dict]:
    """Views by viewer country over the lookback window, most first: country, views, share, view_pct.
    (YouTube Analytics has no viewer-language dimension; countries stand in for it.)"""
    from fyt import youtube

    yt = yt or youtube.analytics_service()
    end = (now - timedelta(days=1)).date()
    start = end - timedelta(days=cfg.insights.lookback_days)
    resp = yt.reports().query(
        ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
        metrics="views,averageViewPercentage", dimensions="country", sort="-views", maxResults=50,
    ).execute()
    rows = [(r[0], int(r[1]), float(r[2])) for r in resp.get("rows", []) or [] if int(r[1]) > 0]
    total = sum(v for _, v, _ in rows) or 1
    return [{"country": c, "views": v, "share": round(v / total, 4), "view_pct": round(p, 1)} for c, v, p in rows]


def language_reach(rows: list[dict]) -> dict[str, float]:
    """Share of views from countries where each translated language is spoken."""
    return {lang: round(sum(r["share"] for r in rows if r["country"] in cs), 4) for lang, cs in LANGUAGE_COUNTRIES.items()}


def retention_curve(yt, video_id: str, start: str, end: str) -> list[tuple[float, float]]:
    """(share of the video, share of viewers still watching) points (audienceWatchRatio)."""
    resp = yt.reports().query(
        ids="channel==MINE", startDate=start, endDate=end, metrics="audienceWatchRatio",
        dimensions="elapsedVideoTimeRatio", filters=f"video=={video_id}",
    ).execute()
    return [(float(r[0]), float(r[1])) for r in resp.get("rows", []) or []]


def at_point(curve: list[tuple[float, float]], ratio: float) -> float | None:
    return min(curve, key=lambda p: abs(p[0] - ratio))[1] if curve else None


def hook_hold(yt, video_id: str, start: str, end: str) -> float | None:
    """Share of viewers still watching at 10% of the video (audienceWatchRatio)."""
    return at_point(retention_curve(yt, video_id, start, end), HOOK_POINT)


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

    def compare(field: str) -> dict[str, dict]:
        """Per pillar / style / slate: how many videos, their mean lift, and the mean of each COMPARED metric."""
        groups: dict[str, list[dict]] = {}
        for r in rows:
            key = meta[r["id"]].get(field)
            if key:
                groups.setdefault(key, []).append(r)
        out: dict[str, dict] = {}
        for k, g in sorted(groups.items()):
            row = {"videos": len(g), "lift": round(mean(lifts[r["id"]] for r in g), 3)}
            for name in COMPARED:
                vals = [r[name] for r in g if r.get(name) is not None]
                row[name] = round(mean(vals), 3) if vals else None
            out[k] = row
        return out

    def card(r: dict) -> dict:
        m = meta[r["id"]]
        return {
            "id": r["id"], "title": m.get("title") or r["id"], "format": m["format"], "views": r["views"],
            "view_pct": round(r["view_pct"], 1), "swipe_away": swipe_away(r), "category": m.get("category"),
            "topic": m.get("topic"), "series": m.get("series"), "lift": round(lifts[r["id"]], 3),
        }

    ranked = sorted(rows, key=lambda r: lifts[r["id"]], reverse=True)
    out = {
        "updated": now.isoformat(timespec="seconds"),
        "videos": len(rows),
        "formats": formats,
        "categories": grouped("category"),
        "shapes": grouped("shape"),
        "title_styles": grouped("title_style"),
        "voices": grouped("voice"),
        # Story-first: content pillars, visual styles and the evergreen / timely slate, side by side.
        "pillars": compare("pillar"),
        "styles": compare("style"),
        "slates": compare("slate"),
        # Shorts that held viewers far better than usual: fyt/bonus.py makes follow-ups to them.
        "winners": [card(r) for r in ranked if meta[r["id"]]["format"] == "short" and lifts[r["id"]] >= WINNER_LIFT],
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
    rows = fetch(cfg, now)
    unknown = [r["id"] for r in rows if meta.get(r["id"], {}).get("format") not in ("short", "long")]
    if unknown:  # uploaded before videos were recorded here (or on another machine): ask YouTube what they are
        try:
            for vid, d in youtube.video_details(unknown).items():
                meta[vid] = {**meta.get(vid, {}), "title": d["title"], "format": d["format"]}
        except Exception as e:
            print(f"note: could not look up {len(unknown)} older videos: {str(e)[:120]}")
    lz = lessons(cfg, rows, meta, now)
    try:
        lz["countries"] = countries(cfg, now)
        lz["language_reach"] = language_reach(lz["countries"])
    except Exception as e:  # nice to know; the lessons don't depend on it
        print(f"note: no country breakdown: {str(e)[:120]}")
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


def pillar_weights(cfg: Config) -> dict[str, float]:
    """Content pillar -> multiplier on its share (catalog.pillars), like category_weights."""
    ic = cfg.insights
    return {
        k: round(min(ic.max_weight, max(ic.min_weight, v["lift"])), 3)
        for k, v in current(cfg).get("pillars", {}).items()
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
    for title, key in (("Pillars", "categories"), ("Story shapes", "shapes"), ("Title styles", "title_styles"),
                       ("Voices", "voices")):
        if lz.get(key):
            out += ["", f"{title} (1.00 = the channel's usual):"]
            out += [f"  {k:<18} {v['lift']:.2f}  ({v['videos']} videos)" for k, v in sorted(lz[key].items(), key=lambda kv: -kv[1]["lift"])]
    for title, key in (("Content pillars", "pillars"), ("Visual styles", "styles"), ("Slate", "slates")):
        if lz.get(key):
            out += ["", f"{title}: lift, CTR, still watching at 30 s, avg view (s), from subscribers, Browse, Suggested"]
            pct = lambda v: "    -" if v is None else f"{v:5.1%}"  # noqa: E731
            for k, v in sorted(lz[key].items(), key=lambda kv: -kv[1]["lift"]):
                secs = "   -" if v.get("avg_seconds") is None else f"{v['avg_seconds']:4.0f}"
                out.append(
                    f"  {k:<12} {v['lift']:.2f}  {pct(v.get('ctr'))}  {pct(v.get('hold30'))}  {secs}  "
                    f"{pct(v.get('subscribed'))}  {pct(v.get('browse'))}  {pct(v.get('suggested'))}  ({v['videos']} videos)"
                )
    w = category_weights(cfg)

    if w:
        out += ["", "Content mix nudges: " + ", ".join(f"{k} x{v}" for k, v in sorted(w.items()))]
    prefer, avoid = title_preferences(cfg)
    if prefer or avoid:
        out += [f"Title styles tried first: {', '.join(prefer) or '-'}; last: {', '.join(avoid) or '-'}"]
    for fmt, notes in lz.get("notes", {}).items():
        if notes:
            out += ["", f"Script notes ({fmt}):", notes]
    if lz.get("countries"):
        out += ["", "Where viewers are:"]
        out += [f"  {r['country']}  {r['share']:6.1%}  ({r['views']} views, {r['view_pct']}% viewed)" for r in lz["countries"][:10]]
        reach = lz.get("language_reach") or {}
        out.append("Views from countries of the translated titles: "
                   + ", ".join(f"{k} {v:.1%}" for k, v in reach.items()))
        top = max(reach.items(), key=lambda kv: kv[1], default=(None, 0))
        if top[1] >= 0.05:
            out.append(f"  {top[0]} is past 5%: worth trying a dubbed {top[0]} audio track on the best videos.")
    summ = summary(cfg)
    if summ:
        out += ["", summ]
    return "\n".join(out)
