"""Bonus videos on top of the schedule: follow-ups to winners, and rising faith topics.

Once a day `scan` looks for two kinds of opportunity and queues a video for each:
- winners: a Short that held viewers far better than the channel's usual (fyt/insights.py lift) gets a
  follow-up Short on the same passage or story from a new angle, and a long version when the month's
  minutes allow. They go out within `bonus.follow_up_days`, while the interest is still there.
- trends: a Bible or faith Wikipedia article whose readership suddenly jumps (free pageviews API), or a
  faith search YouTube has just started suggesting (free search suggestions, no API quota), that fits
  the channel well. An unused idea from the catalog is used when one matches; otherwise a new idea is
  written around passages that are checked to exist.

Bible first: every bonus idea names its passages, they're checked against the Bible text, and the video
goes through the same study, faithfulness review and Scripture check as every other video.

`run` (from `fill`, after the schedule) makes the queued videos while there's room: upload quota left
today, the weekly / monthly caps, and the month's free GitHub Actions minutes (measured, not guessed).
"""

from __future__ import annotations

import calendar
import json
import re
from datetime import datetime, timedelta, timezone
from statistics import median
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests
from pydantic import BaseModel, Field

from fyt.config import Config
from fyt.store import Uploads

QUEUE, SEEN, SCANNED, SUGGESTIONS = "bonus-queue", "bonus-seen", "bonus-scanned", "bonus-suggestions"
SUGGEST = "https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&q={q}"


def _today(cfg: Config, now: datetime) -> str:
    return now.astimezone(ZoneInfo(cfg.schedule.timezone)).date().isoformat()


def _load(cfg: Config, key: str, default):
    raw = Uploads(cfg).note(key)
    return json.loads(raw) if raw else default


def _save(cfg: Config, key: str, value) -> None:
    Uploads(cfg).set_note(key, json.dumps(value))


def queue(cfg: Config) -> list[dict]:
    return _load(cfg, QUEUE, [])


def enqueue(cfg: Config, now: datetime, topic: str, kind: str, reason: str, minutes: float | None = None) -> None:
    items = queue(cfg)
    if any(i["topic"] == topic for i in items):
        return
    expires = now + timedelta(days=cfg.bonus.follow_up_days)
    items.append({"topic": topic, "kind": kind, "minutes": minutes, "reason": reason,
                  "added": now.isoformat(timespec="seconds"), "expires": expires.isoformat(timespec="seconds")})
    _save(cfg, QUEUE, items)
    print(f"bonus queued: {kind} {topic} ({reason})")


# --- New ideas around a passage --------------------------------------------------------


class BonusIdea(BaseModel):
    title: str = Field(description="Working title, max 70 characters, true to the passage.")
    angle: str = Field(description="The angle: the moment, feeling or question this video takes, and what the viewer leaves with.")
    scriptures: list[str] = Field(description="1-3 exact references, 'Book chapter:verse' or 'Book chapter:verse-verse'.")
    arc: str = Field(description="journey, story, curiosity, wisdom, prayer, peace or joy")
    emotion: str = Field(description="hope, peace, courage, love, joy, grief, gratitude, curiosity, wisdom, strength...")
    character: str = Field(default="", description="The Bible person at the centre, if any.")


IDEA_GUIDE = """You plan one video for a faceless Christian YouTube channel ({niche}).
Bible first, emotion second: the video rests on specific passages and must stay faithful to them. Name 1-3
exact references (Book chapter:verse). Never invent events or put words in Jesus' mouth; no prosperity
promises, fear tactics, politics or date-setting prophecy.
{task}"""


def write_idea(cfg: Config, task: str, context: str, kind: str, category: str, extra: dict | None = None) -> str | None:
    """A new catalog idea (stored with the generated ones) from the model, kept only if its passages exist.
    Returns its topic ("idea:<id>"), or None."""
    from fyt import catalog, llm, scripture

    new = llm.structured(cfg, IDEA_GUIDE.format(niche=cfg.channel.niche, task=task), context, BonusIdea, max_tokens=1500)
    refs = [r for r in new.scriptures if scripture.find_references(r) == [r]]
    refs = [r for r in refs if r in scripture.fetch_all(cfg, refs)]
    if not refs:
        print(f"bonus idea dropped: no valid Scripture in {new.scriptures}")
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", new.title.lower()).strip("-")[:50] or "bonus"
    ids = {i.id for i in catalog.load(cfg)}
    base, n = f"bonus-{slug}", 2
    idea_id = base
    while idea_id in ids:
        idea_id, n = f"{base}-{n}", n + 1
    idea = {
        "id": idea_id, "title": new.title, "category": category, "emotion": new.emotion, "character": new.character,
        "arc": new.arc if new.arc in catalog.ARCS else catalog.DEFAULT_ARC.get(category, "journey"),
        "formats": ["short"] if kind == "short" else ["medium", "long"], "scriptures": refs, "angle": new.angle,
        "generated": True, **(extra or {}),
    }
    catalog._save_generated(cfg, [idea])
    return catalog.PREFIX + idea_id


# --- Winners ------------------------------------------------------------------------


def queue_winners(cfg: Config, now: datetime, seen: set[str]) -> int:
    """Follow-ups to the Shorts that held viewers far better than usual (best first, one per scan)."""
    from fyt import catalog, insights

    for w in insights.current(cfg).get("winners", []):
        if w["lift"] < cfg.bonus.min_lift or f"winner:{w['id']}" in seen:
            continue
        seen.add(f"winner:{w['id']}")
        idea = None
        if w.get("topic") and catalog.is_idea(w["topic"]):
            try:
                idea = catalog.get(cfg, w["topic"])
            except KeyError:
                idea = None
        category = (idea.category if idea else w.get("category")) or "jesus"
        context = (
            f"The Short \"{w['title']}\" held viewers far better than this channel's usual.\n"
            + (f"Its passages: {', '.join(idea.scriptures)}\nIts angle: {idea.angle}\n" if idea else "")
        )
        extra = {"series": idea.series, "character": idea.character, "wiki": idea.wiki} if idea else {}
        extra = {k: v for k, v in extra.items() if v}
        made = 0
        for kind in ("short", "long"):
            task = (
                f"Plan a follow-up {'Short' if kind == 'short' else 'long video (8-10 minutes)'} to that video: the SAME "
                "passage or story (the verses around it are fine), from a different moment or angle than the first, "
                "so someone who loved the first wants this one too."
                if kind == "short" else
                "Plan the long version of that video: the whole story or passage it comes from, told in full, "
                "faithful to the text, with room for its context and meaning."
            )
            try:
                topic = write_idea(cfg, task, context, kind, category, extra)
            except Exception as e:
                print(f"::warning::no follow-up to {w['id']}: {e}")
                break
            if topic:
                enqueue(cfg, now, topic, kind, f"follow-up to winner {w['id']} (x{w['lift']:.2f})",
                        cfg.bonus.long_minutes if kind == "long" else None)
                made += 1
        return made
    return 0


# --- Rising topics -----------------------------------------------------------------


def daily_views(cfg: Config, title: str, days: int = 30, today=None) -> list[int]:
    """Readers per day of a Wikipedia article over the last `days` days (oldest first)."""
    from fyt import growth, wiki

    end = (today or datetime.now(timezone.utc).date()) - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    url = growth.PAGEVIEWS.format(lang=cfg.wikipedia.lang, title=quote(title.replace(" ", "_"), safe=""),
                                  start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"))
    r = requests.get(url, headers={"User-Agent": wiki.user_agent()}, timeout=30)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return [i.get("views", 0) for i in r.json().get("items", [])]


def spike(views: list[int]) -> float:
    """Last two days against the median day before them (0 when there's too little history)."""
    if len(views) < 10:
        return 0.0
    base = median(views[:-2]) or 1
    return (views[-1] + views[-2]) / 2 / base


def watchlist(cfg: Config) -> list[str]:
    from fyt import catalog

    titles = list(dict.fromkeys([*cfg.bonus.watch_articles, *(i.wiki for i in catalog.load(cfg) if i.wiki)]))
    return titles[:150]


def rising_articles(cfg: Config, now: datetime) -> list[tuple[str, float, int]]:
    """(article, spike ratio, readers a day lately) for watched articles whose readership jumped."""
    out = []
    for title in watchlist(cfg):
        try:
            v = daily_views(cfg, title, today=now.date())
        except Exception as e:
            print(f"note: no pageviews for {title}: {str(e)[:80]}")
            continue
        ratio = spike(v)
        recent = (v[-1] + v[-2]) // 2 if len(v) >= 2 else 0
        if ratio >= cfg.bonus.spike_ratio and recent >= cfg.bonus.min_daily_views:
            out.append((title, round(ratio, 2), recent))
    return sorted(out, key=lambda t: -t[1])


def suggestions(seed: str) -> list[str]:
    """What YouTube's search box suggests for a seed (free; no API quota)."""
    r = requests.get(SUGGEST.format(q=quote(seed)), timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    body = r.json()
    return [s for s in (body[1] if len(body) > 1 else []) if isinstance(s, str)]


def new_suggestions(cfg: Config, now: datetime) -> list[str]:
    """Suggestions that weren't there on any of the last 7 days: searches that are rising."""
    history: dict[str, list[str]] = _load(cfg, SUGGESTIONS, {})
    today = _today(cfg, now)
    got: list[str] = []
    for seed in cfg.bonus.suggest_seeds:
        try:
            got += suggestions(seed)
        except Exception as e:
            print(f"note: no search suggestions for {seed!r}: {str(e)[:80]}")
    old = {s for day, items in history.items() if day != today for s in items}
    history[today] = sorted(set(got))
    keep = sorted(history)[-8:]
    _save(cfg, SUGGESTIONS, {d: history[d] for d in keep})
    if len(keep) < 2:
        return []  # the first day only sets the baseline
    return [s for s in dict.fromkeys(got) if s not in old]


def queue_trends(cfg: Config, now: datetime, seen: set[str], used: set[str]) -> int:
    """At most one bonus Short a day on a rising faith topic that fits the channel well."""
    from fyt import catalog, growth

    for title, ratio, readers in rising_articles(cfg, now):
        if f"wiki:{title}" in seen:
            continue
        seen.add(f"wiki:{title}")
        match = next((i for i in catalog.load(cfg) if i.wiki == title and i.topic not in used and "short" in i.formats), None)
        if match:
            enqueue(cfg, now, match.topic, "short", f"Wikipedia readers of {title} x{ratio}")
            return 1
        fit = growth.score_topics(cfg, [(title, readers)]).get(title, 0)
        if fit >= cfg.bonus.min_fit:
            topic = write_idea(cfg, f"Plan a Short on {title}, which many people are reading about right now.",
                               f"Topic: {title}", "short", "bible_story", {"wiki": title})
            if topic:
                enqueue(cfg, now, topic, "short", f"Wikipedia readers of {title} x{ratio}")
                return 1
    fresh = [s for s in new_suggestions(cfg, now) if f"search:{s}" not in seen][:20]
    if fresh:
        fits = growth.score_topics(cfg, [(s, 0) for s in fresh], "These are searches YouTube has just started suggesting.\n")
        for s in sorted(fresh, key=lambda s: -fits.get(s, 0)):
            seen.add(f"search:{s}")
            if fits.get(s, 0) < cfg.bonus.min_fit:
                break
            topic = write_idea(cfg, f"Plan a Short that answers the search \"{s}\" from Scripture.", f"Search: {s}", "short", "wisdom")
            if topic:
                enqueue(cfg, now, topic, "short", f"rising search: {s}")
                return 1
    return 0


def scan(cfg: Config, now: datetime | None = None, force: bool = False) -> int:
    """Once a day: queue follow-ups to winners and a rising topic. Returns how many videos were queued."""
    from fyt.store import Topics

    now = now or datetime.now(timezone.utc)
    b = cfg.bonus
    if not (b.winners or b.trends) or (not force and _load(cfg, SCANNED, "") == _today(cfg, now)):
        return 0
    _save(cfg, SCANNED, _today(cfg, now))
    seen = set(_load(cfg, SEEN, []))
    queued = 0
    try:
        if b.winners:
            try:
                from fyt import insights

                insights.refresh(cfg, now)
            except Exception as e:
                print(f"::warning::insights not refreshed: {e}")
            queued += queue_winners(cfg, now, seen)
        if b.trends:
            queued += queue_trends(cfg, now, seen, set(Topics(cfg).titles()))
    finally:
        _save(cfg, SEEN, sorted(seen)[-500:])
    return queued


# --- Budget -------------------------------------------------------------------------


def record_minutes(cfg: Config, now: datetime, minutes: float, bonus: bool = False) -> None:
    """Add runner minutes to the month's tally: `fill` records each whole run (plus setup overhead);
    bonus=True records the bonus videos' share of it separately, to tell the schedule's own pace."""
    u = Uploads(cfg)
    key = f"{'bonus-' if bonus else ''}minutes-{now:%Y-%m}"
    u.set_note(key, str(round(float(u.note(key) or 0) + minutes, 1)))


def minutes_allow(cfg: Config, now: datetime, cost: float) -> bool:
    """Whether a bonus costing `cost` runner minutes still keeps the month under the free allowance:
    minutes used so far, plus the rest of the month at the schedule's measured daily pace, plus this."""
    u = Uploads(cfg)
    used = float(u.note(f"minutes-{now:%Y-%m}") or 0)
    bonus_used = float(u.note(f"bonus-minutes-{now:%Y-%m}") or 0)
    days = calendar.monthrange(now.year, now.month)[1]
    limit = cfg.bonus.monthly_minutes * 0.95  # a little room for manual runs
    if now.day < 3:
        return False  # the month's pace isn't known yet
    pace = (used - bonus_used) / now.day
    projected = used + pace * (days - now.day) + cost
    return projected <= limit


def caps_allow(cfg: Config, kind: str, now: datetime) -> bool:
    u = Uploads(cfg)
    if kind == "short":
        since, cap = now - timedelta(days=7), cfg.bonus.shorts_per_week
    else:
        since, cap = now - timedelta(days=30), cfg.bonus.longs_per_month
    return u.count_kind_since(f"bonus-{kind}", since.isoformat(timespec="seconds")) < cap


def due(cfg: Config, now: datetime) -> list[dict]:
    return [i for i in queue(cfg) if i["expires"] > now.isoformat()]


def run(cfg: Config, now: datetime, rng, clock, started: float, budget: int) -> int:
    """Make and upload queued bonus videos while quota, caps, minutes and the run's time allow."""
    from fyt import pipeline, schedule
    from fyt.config import sleep_config
    from fyt.store import Topics

    items = queue(cfg)
    live = [i for i in items if i["expires"] > now.isoformat()]
    if len(live) != len(items):
        print(f"{len(items) - len(live)} bonus video(s) expired unmade")
    made, left = 0, list(live)
    topics = Topics(cfg)
    for item in live:
        kind = item["kind"]
        slot = schedule.Slot(now, kind, minutes=item.get("minutes"))
        cost = schedule.make_minutes(slot, cfg)
        if budget <= 0:
            break
        if not caps_allow(cfg, kind, now):
            continue
        if (clock() - started) / 60 + cost > cfg.schedule.max_run_minutes:
            print(f"not enough time left in this run for a bonus {kind}")
            continue
        if not minutes_allow(cfg, now, cost + cfg.bonus.run_overhead_minutes):
            print(f"bonus {kind} waits: it would take this month past the free Actions minutes")
            continue
        left.remove(item)
        _save(cfg, QUEUE, left)
        t0 = clock()
        vcfg = sleep_config(cfg.model_copy(update={"format": kind, **({"target_minutes": item["minutes"]} if item.get("minutes") else {})}))
        topics.add([item["topic"]])
        topic_id, _ = topics.find(item["topic"])
        topics.set(topic_id, "in_progress")
        try:
            job = pipeline.make_topic(vcfg, item["topic"])
        except Exception as e:
            topics.set(topic_id, "failed")
            print(f"::warning::bonus {kind} failed: {item['topic']}: {e}")
            continue
        finally:
            record_minutes(cfg, now, (clock() - t0) / 60, bonus=True)
        topics.set(topic_id, "done", job.id)
        if job.meta.get("status") != "approved":
            continue
        result = schedule._upload(cfg, job, schedule.Slot(schedule.utcnow(), kind), rng, now, kind=f"bonus-{kind}")
        if result:
            budget -= 1
            made += 1
            print(f"bonus {kind} uploaded: {item['reason']}")
        elif result is None:
            budget = 0
    return made


def report(cfg: Config, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    u = Uploads(cfg)
    used = float(u.note(f"minutes-{now:%Y-%m}") or 0)
    out = [f"Actions minutes this month (measured): {used:.0f} of {cfg.bonus.monthly_minutes}"]
    out.append(f"Bonus Shorts in the last 7 days: {u.count_kind_since('bonus-short', (now - timedelta(days=7)).isoformat())}"
               f" (cap {cfg.bonus.shorts_per_week}); bonus long videos in 30 days: "
               f"{u.count_kind_since('bonus-long', (now - timedelta(days=30)).isoformat())} (cap {cfg.bonus.longs_per_month})")
    items = due(cfg, now)
    out.append(f"Queued: {len(items)}")
    out += [f"  {i['kind']:5} {i['topic']}  ({i['reason']}; until {i['expires'][:10]})" for i in items]
    return "\n".join(out)
