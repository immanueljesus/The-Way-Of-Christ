"""The Christian calendar engine: seasonal campaigns that run alongside the evergreen videos.

Every year is computed, not typed in: Easter (Western, or Orthodox) and everything that moves with it
(Ash Wednesday, Holy Week, Ascension, Pentecost...), Advent and Christ the King, fixed feasts and
"world moments" like New Year or Mother's Day. content/calendar.yaml turns each event into a small
campaign: videos days before (anticipation), on the day (the centrepiece) and after (reflection).

Campaign videos get their own publish slots (see schedule.upcoming_slots) and are made up to
`liturgy.lead_days` ahead, so Good Friday's video is rendered and scheduled a week before.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

from fyt.config import ROOT, Config

SEP = "@"  # campaign topics are "idea:<entry id>@<year>", so each year's Easter is its own video


def western_easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def orthodox_easter(year: int) -> date:
    """Orthodox Easter Sunday: the Julian computus, converted to the Gregorian calendar."""
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month, day = divmod(d + e + 114, 31)
    julian = date(year, month, day + 1)
    return julian + timedelta(days=year // 100 - year // 400 - 2)  # 13 days in 1900-2099


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th weekday (Monday = 0) of a month; n = -1 for the last."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def anchor_date(anchor: str, year: int, tradition: str = "western") -> date:
    """The date of a named anchor in a given year.

    Named: easter, ash_wednesday, palm_sunday, ascension, pentecost, trinity, corpus_christi,
    sacred_heart, advent (first Sunday), christ_the_king, christmas, epiphany, baptism.
    Fixed: "MM-DD". Floating: "may:sun:2" (2nd Sunday in May), "nov:thu:4", "jun:sun:3"."""
    easter = orthodox_easter(year) if tradition == "orthodox" else western_easter(year)
    christmas = date(year, 12, 25)
    advent = christmas - timedelta(days=christmas.weekday() + 1 + 21)  # 4th Sunday before Christmas
    named = {
        "easter": easter,
        "ash_wednesday": easter - timedelta(days=46),
        "palm_sunday": easter - timedelta(days=7),
        "ascension": easter + timedelta(days=39),
        "pentecost": easter + timedelta(days=49),
        "trinity": easter + timedelta(days=56),
        "corpus_christi": easter + timedelta(days=60),
        "sacred_heart": easter + timedelta(days=68),
        "advent": advent,
        "christ_the_king": advent - timedelta(days=7),
        "christmas": christmas,
        "epiphany": date(year, 1, 6),
        "baptism": date(year, 1, 6) + timedelta(days=(6 - date(year, 1, 6).weekday()) or 7),  # Sunday after Epiphany
    }
    if anchor in named:
        return named[anchor]
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", anchor)
    if m:
        return date(year, int(m[1]), int(m[2]))
    m = re.fullmatch(r"([a-z]{3}):([a-z]{3}):(-?\d)", anchor)
    if m:
        return _nth_weekday(year, MONTHS[m[1]], DAYS[m[2]], int(m[3]))
    raise ValueError(f"unknown calendar anchor {anchor!r}")


@dataclass(frozen=True)
class Entry:
    """One campaign video on its date."""

    on: date
    kind: str  # short | long
    minutes: float | None
    topic: str  # "idea:<id>@<year>"
    title: str
    event: str
    time: str | None = None  # "HH:MM" in the schedule's time zone; overrides liturgy.long_time / short_times


def _load(cfg: Config) -> dict:
    path = Path(cfg.liturgy.path)
    path = path if path.is_absolute() else ROOT / path
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _wanted(cfg: Config, event: dict) -> bool:
    return event.get("tradition", "ecumenical") in cfg.liturgy.traditions


def entries(cfg: Config, start: date, end: date) -> list[Entry]:
    """Campaign videos dated between start and end (inclusive), earliest first."""
    if not cfg.liturgy.enabled:
        return []
    data = _load(cfg)
    out: list[Entry] = []
    for year in range(start.year - 1, end.year + 2):  # Advent campaigns cross the new year
        for key, event in (data.get("events") or {}).items():
            if not _wanted(cfg, event):
                continue
            base = anchor_date(event["anchor"], year, cfg.liturgy.easter)
            for e in event.get("videos") or []:
                on = base + timedelta(days=int(e.get("offset", 0)))
                if start <= on <= end:
                    out.append(Entry(
                        on, e.get("kind", "short"), e.get("minutes"), f"idea:{e['id']}{SEP}{year}", e["title"], key,
                        e.get("time"),
                    ))
    return sorted(out, key=lambda x: (x.on, x.kind != "long", x.topic))


def idea_data(cfg: Config, entry_id: str) -> dict | None:
    """A campaign video's idea fields, by id (without the year)."""
    for key, event in (_load(cfg).get("events") or {}).items():
        for e in event.get("videos") or []:
            if e["id"] == entry_id:
                fields = {k: v for k, v in e.items() if k not in ("offset", "kind", "minutes", "time")}
                fields.setdefault("category", event.get("category", "jesus"))
                fields["series"] = fields.get("series") or event.get("series")
                fields["pillar"] = event.get("name", key)
                fields["formats"] = ["short", "medium", "long", "sleep"]
                return fields
    return None


def season(cfg: Config, day: date) -> dict:
    """The season around a day and what evergreen picks should lean towards then
    (calendar.yaml `seasons`): {"name", "emotions", "categories"}."""
    if not cfg.liturgy.enabled:
        return {}
    for s in _load(cfg).get("seasons") or []:
        tradition = cfg.liturgy.easter
        start = anchor_date(s["from"], day.year, tradition) + timedelta(days=int(s.get("from_offset", 0)))
        stop = anchor_date(s["to"], day.year, tradition) + timedelta(days=int(s.get("to_offset", 0)))
        if stop < start:  # e.g. a season running over the new year
            if day >= start or day <= stop:
                return s
        elif start <= day <= stop:
            return s
    return {}
