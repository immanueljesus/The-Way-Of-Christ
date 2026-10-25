"""Story-first: the weekly slate of long videos, their visual styles, and the idea score.

Two long videos a week (the plan entries with `slate` in channel.yaml):
- Video A, "evergreen": a Bible story from the backlog (content/backlog.yaml). The calendar never
  picks this slot: a feast's long video can't take it.
- Video B, "timely": the calendar's long video for that week (a feast or season, content/calendar.yaml),
  else the coming Sunday's Mass Gospel (fyt/lectionary.py). If nothing timely can be made, it takes
  the next evergreen story too.

Each long story video has a visual style, chosen per video within what the free pipeline renders
(STYLES): it sets the length, the letterbox, the music and how much of the picture is classical art
versus footage, and it is recorded on the video so the analytics can compare styles (fyt/insights.py).
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from fyt import catalog
from fyt.catalog import Idea
from fyt.config import Config

EVERGREEN, TIMELY = "evergreen", "timely"
LONG = "-long"  # a Sunday Gospel long video's topic: "idea:sunday-gospel-ot29-A@2026-long" (the Short has no suffix)

# Visual styles. `minutes` is the default length, `range` the lengths the style allows.
STYLES: dict[str, dict] = {
    "cinematic": {
        "minutes": 7, "range": (5, 9), "letterbox": True, "music": "cinematic", "art_images": 6,
        "note": "CINEMATIC. Told like a film: moving footage for most scenes (landscapes, weather, fire, water, "
        "crowds and hands, never faces of Bible people), paintings for the story's key moments, slow camera "
        "moves, ambient detail in the narration (wind, footsteps, the crowd), music swelling at the turning point.",
    },
    "illustrated": {
        "minutes": 5, "range": (3, 6), "letterbox": False, "music": "calm", "art_images": 10,
        "note": "ILLUSTRATED SCRIPTURE. Classical paintings carry the story: give two thirds or more of the scenes "
        "an image (a painting, map or manuscript), slow parallax and restrained motion, footage only between "
        "paintings (old stone, parchment, lamplight, landscapes of the place).",
    },
    "documentary": {
        "minutes": 8, "range": (6, 10), "letterbox": False, "music": "cinematic", "art_images": 8,
        "note": "BIBLICAL DOCUMENTARY. A narrator walking the viewer through the world of the passage: the places "
        "(maps, landscapes, ruins), artifacts and customs, paintings as reconstructed scenes. Clear and "
        "unhurried; label scholarly readings and traditions as such, and keep the passage at the centre.",
    },
}
DEFAULT_STYLE = {"stories": "cinematic", "struggles": "cinematic", "teachings": "illustrated", "questions": "documentary"}
SCORE_FIELDS = ("significance", "story", "appeal", "seasonal", "effort")


def style_of(idea: Idea | None) -> str:
    """The idea's visual style: its own, else its pillar's default."""
    if idea is None:
        return ""
    return idea.style if idea.style in STYLES else DEFAULT_STYLE[catalog.pillar_of(idea)]


def style_config(cfg: Config, idea: Idea | None) -> Config:
    """The channel config for a long video in the idea's style (length, letterbox, how many paintings).
    Shorts, sleep videos and topics that aren't ideas are unchanged."""
    if idea is None or cfg.format != "long" or cfg.is_sleep:
        return cfg
    st = STYLES[style_of(idea)]
    low, high = st["range"]
    minutes = min(high, max(low, idea.minutes or st["minutes"]))
    return cfg.model_copy(update={"target_minutes": minutes, "letterbox": st["letterbox"], "art_images": st["art_images"]})


def style_note(idea: Idea | None, cfg: Config) -> str:
    """The style's direction for the script writer ("" for Shorts and videos without a style)."""
    if idea is None or cfg.format != "long" or cfg.is_sleep:
        return ""
    return "Visual style: " + STYLES[style_of(idea)]["note"]


def style_music(idea: Idea | None) -> str:
    """calm | cinematic: the style's music, unless the idea names its own."""
    if idea is None:
        return ""
    return idea.music or STYLES[style_of(idea)]["music"]


def score(idea: Idea, season: dict | None = None) -> float:
    """The idea score used to rank candidates: biblical significance + story potential + audience appeal
    + seasonal relevance (2 more in a season whose feelings or pillars it shares) - production effort.
    Each part is 1-5 (3 when the idea doesn't say)."""
    part = lambda k: float(idea.score.get(k, 3))  # noqa: E731
    season = season or {}
    in_season = idea.emotion in (season.get("emotions") or []) or idea.category in (season.get("categories") or [])
    return part("significance") + part("story") + part("appeal") + part("seasonal") + 2 * in_season - part("effort")


def pick_evergreen(cfg: Config, used: set[str], season: dict | None = None) -> Idea | None:
    """The next evergreen story from the backlog: the seed in its `priority` order, then the pillar
    furthest below its share (catalog.pillars) and, within it, the highest score."""
    ideas = catalog.load(cfg)
    backlog = [i for i in ideas if i.backlog and i.topic not in used]
    if not backlog:
        return None
    seeds = sorted((i for i in backlog if i.priority is not None), key=lambda i: i.priority)
    if seeds:
        return seeds[0]
    made = Counter(catalog.pillar_of(i) for i in ideas if i.topic in used)
    total = sum(made.values()) or 1
    share = cfg.catalog.pillars or {p: 1 for p in catalog.PILLARS}
    weight = sum(share.values()) or 1
    deficit = lambda i: share.get(catalog.pillar_of(i), 0) / weight - made[catalog.pillar_of(i)] / total  # noqa: E731
    return min(backlog, key=lambda i: (-round(deficit(i), 6), -score(i, season), backlog.index(i)))


def timely_options(cfg: Config, day: date) -> list[str]:
    """What the timely slot on `day` can show, best first: the calendar's long videos dated in the week
    from `day` (a feast is published on or before its day), then the Gospel of the Sunday in that week."""
    from fyt import lectionary, liturgy

    if not cfg.liturgy.enabled:
        return []
    end = day + timedelta(days=6)
    longs = [e for e in liturgy._campaigns(cfg, day, end) if e.kind == "long"]
    season = liturgy.season(cfg, day)
    ranked = sorted(longs, key=lambda e: (-score(catalog.get(cfg, e.topic), season), e.on, e.topic))
    out = [e.topic for e in ranked]
    sunday = day + timedelta(days=(6 - day.weekday()) % 7)
    found = lectionary.sunday(sunday) if sunday <= end else None
    if found:
        out.append(f"idea:{found.id}{liturgy.SEP}{found.day.year}{LONG}")
    return out
