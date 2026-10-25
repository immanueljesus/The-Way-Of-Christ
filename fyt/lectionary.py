"""The Sunday Gospel of the Roman Catholic Lectionary: which Sunday a date is, and its Gospel.

Catholics around the world hear the same readings at Sunday Mass, set by the Lectionary's three-year
cycle (Year A: Matthew, B: Mark, C: Luke, with John through Lent and Easter). The Sunday is computed
from the date, like the feasts in fyt/liturgy.py; its Gospel references come from content/lectionary.yaml.
The Sunday Gospel Shorts (liturgy.sunday_gospel) are written from those passages.

Follows the calendar most English-speaking countries use: Epiphany on the Sunday between 2 and 8
January, Corpus Christi on the Sunday after Trinity Sunday, Ascension on its Thursday.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

from fyt.config import ROOT, Config
from fyt.liturgy import anchor_date, western_easter

PATH = "content/lectionary.yaml"
PREFIX = "sunday-gospel-"  # campaign ids: "sunday-gospel-<key>-<A|B|C>"


@dataclass(frozen=True)
class Sunday:
    day: date
    key: str  # ot29, advent1, easter3, palm, christ_the_king, feast-08-15...
    cycle: str  # A | B | C
    name: str  # "29th Sunday in Ordinary Time"
    gospel: list[str]  # references, e.g. ["Matthew 22:15-21"]

    @property
    def id(self) -> str:
        return f"{PREFIX}{self.key}-{self.cycle}"


def _load() -> dict:
    path = ROOT / PATH
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.exists() else {}


def cycle(day: date) -> str:
    """The Lectionary year (A, B or C). A liturgical year starts on the First Sunday of Advent and is
    named after the calendar year it ends in: Year A when that year divides by 3 with remainder 1."""
    year = day.year + (1 if day >= anchor_date("advent", day.year) else 0)
    return "CAB"[year % 3]


def _ordinal(n: int) -> str:
    words = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh"]
    return words[n - 1] if n <= len(words) else f"{n}th"


def _ot_ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _name(data: dict, key: str) -> str:
    """ "ot29" -> "29th Sunday in Ordinary Time", "advent1" -> "First Sunday of Advent"."""
    names = data.get("names") or {}
    kind = key.rstrip("0123456789")
    n = int(key[len(kind):] or 0)
    return names.get(key) or names.get(kind, key).format(n=_ot_ordinal(n) if kind == "ot" else _ordinal(n))


def epiphany(year: int) -> date:
    """Epiphany on the Sunday between 2 and 8 January."""
    jan2 = date(year, 1, 2)
    return jan2 + timedelta(days=(6 - jan2.weekday()) % 7)


def baptism(year: int) -> date:
    """The Baptism of the Lord: the Sunday after Epiphany, or the Monday after it when Epiphany falls
    on 7 or 8 January."""
    e = epiphany(year)
    return e + timedelta(days=1 if e.day >= 7 else 7)


def which(day: date) -> tuple[str, int]:
    """The Sunday's key and number, e.g. ("ot", 29), ("advent", 1), ("palm", 0)."""
    if day.weekday() != 6:
        raise ValueError(f"{day} is not a Sunday")
    y = day.year
    advent = anchor_date("advent", y)
    christmas = date(y, 12, 25)
    if advent <= day < christmas:
        return "advent", (day - advent).days // 7 + 1
    if day > christmas:
        return "holy_family", 0
    if day == christmas:
        return "christmas", 0
    if day == date(y, 1, 1):
        return "mary_mother_of_god", 0
    if day == epiphany(y):
        return "epiphany", 0
    if day < epiphany(y):
        return "christmas2", 0
    if day == baptism(y):
        return "baptism", 0
    easter = western_easter(y)
    ash = easter - timedelta(days=46)
    pentecost = easter + timedelta(days=49)
    if day < ash:  # the Baptism of the Lord is the First Sunday in Ordinary Time (even on a Monday)
        b = baptism(y)
        return "ot", (day - (b - timedelta(days=(b.weekday() + 1) % 7))).days // 7 + 1
    if day < easter - timedelta(days=7):
        return "lent", (day - ash).days // 7 + 1
    if day < easter:
        return "palm", 0
    if day < pentecost:
        return "easter", (day - easter).days // 7 + 1
    if day == pentecost:
        return "pentecost", 0
    if day == pentecost + timedelta(days=7):
        return "trinity", 0
    if day == pentecost + timedelta(days=14):
        return "corpus_christi", 0
    christ_the_king = advent - timedelta(days=7)
    if day == christ_the_king:
        return "christ_the_king", 0
    return "ot", 34 - (christ_the_king - day).days // 7


def sunday(day: date) -> Sunday | None:
    """The Sunday Mass of a date (a Sunday) with its Gospel, or None if the table has no entry."""
    data = _load()
    kind, n = which(day)
    key = f"{kind}{n}" if n else kind
    name = _name(data, key)
    c = cycle(day)
    entry = (data.get("sundays") or {}).get(key)
    feast = (data.get("feasts") or {}).get(day.strftime("%m-%d"))
    if feast and kind == "ot":  # a feast of the Lord or solemnity takes the place of the Sunday
        key, name, entry = f"feast-{day.strftime('%m-%d')}", feast["name"], feast
    if not entry:
        return None
    refs = entry.get(c) or entry.get("all")
    return Sunday(day, key, c, name, list(refs)) if refs else None


def idea_data(cfg: Config, entry_id: str) -> dict | None:
    """The idea fields for a Sunday Gospel video, by id ("sunday-gospel-ot29-A")."""
    if not entry_id.startswith(PREFIX):
        return None
    key, _, c = entry_id[len(PREFIX):].rpartition("-")
    data = _load()
    if key.startswith("feast-"):
        entry = (data.get("feasts") or {}).get(key.removeprefix("feast-"))
        name = entry.get("name", key) if entry else key
    else:
        entry = (data.get("sundays") or {}).get(key)
        name = _name(data, key)
    refs = (entry or {}).get(c) or (entry or {}).get("all")
    if not refs:
        return None
    return {
        "title": f"{name}: the Gospel at Mass this Sunday",
        "category": "jesus",
        "content_type": "gospel",
        "series": cfg.liturgy.sunday_gospel_series,
        "pillar": "teachings",
        "formats": ["short", "medium", "long"],
        "scriptures": list(refs),
        "angle": (
            f"This is the Gospel Catholics around the world hear at Mass this Sunday ({name}, Year {c}): "
            f"{', '.join(refs)}. Step inside this passage, draw out its central message as the Church reads it, "
            "faithfully and without adding to it, and give the viewer one thing to carry into Sunday Mass and the week."
        ),
        "title_prefix": cfg.liturgy.sunday_gospel_prefix,
    }


def entries(cfg: Config, start: date, end: date, taken: set[date]) -> list[tuple[date, Sunday]]:
    """(publish day, Sunday) for the Sunday Gospel videos published between start and end: each goes
    out liturgy.sunday_gospel_offset days before its Sunday. Sundays in `taken` (a calendar campaign
    already has a video that day, e.g. Easter) are left to the campaign."""
    out = []
    offset = timedelta(days=cfg.liturgy.sunday_gospel_offset)
    s = start - offset
    s += timedelta(days=(6 - s.weekday()) % 7)
    while s + offset <= end:
        if s not in taken:
            found = sunday(s)
            if found:
                out.append((s + offset, found))
        s += timedelta(days=7)
    return out
