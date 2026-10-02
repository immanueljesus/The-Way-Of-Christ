"""The channel's curated idea list (content/ideas.yaml) as a content source.

Each idea names its category, series, suitable formats, the Scripture it rests on and,
for Bible stories, a Wikipedia article for background and classical artwork. The next
idea is chosen to keep the content mix on target (config `catalog.mix`), or from the
category a publish slot asks for (config `schedule.plan`).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from fyt.config import ROOT, Config

PREFIX = "idea:"
FORMATS = ("short", "medium", "long", "sleep")


class Idea(BaseModel):
    id: str
    title: str
    category: str  # motivational | bible_story | prayer | jesus | facts
    pillar: str = ""
    series: str | None = None
    formats: list[str] = Field(default_factory=lambda: ["short", "medium"])
    scriptures: list[str] = Field(default_factory=list)
    wiki: str | None = None  # Wikipedia article for background and artwork
    angle: str = ""  # the pain point or hook, and what the viewer should leave with

    @property
    def topic(self) -> str:
        return PREFIX + self.id


def is_idea(topic: str) -> bool:
    return topic.startswith(PREFIX)


def load(cfg: Config) -> list[Idea]:
    path = Path(cfg.catalog.path)
    path = path if path.is_absolute() else ROOT / path
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    ideas = [Idea.model_validate(i) for i in raw.get("ideas", [])]
    ids = [i.id for i in ideas]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate idea ids in {path}: {', '.join(sorted(dupes))}")
    return ideas


def get(cfg: Config, topic_or_id: str) -> Idea:
    key = topic_or_id.removeprefix(PREFIX)
    for idea in load(cfg):
        if idea.id == key:
            return idea
    raise KeyError(f"no idea with id {key!r} in {cfg.catalog.path}")


def length_bucket(fmt: str, minutes: float) -> str:
    """short: Shorts. medium: 2-6 min. long: 8-15 min. sleep: 20-40 min prayer/story/sleep videos."""
    if fmt == "short":
        return "short"
    if minutes <= 6.5:
        return "medium"
    if minutes <= 18:
        return "long"
    return "sleep"


def pick(cfg: Config, used: set[str], category: str | None = None, minutes: float | None = None) -> Idea | None:
    """The next unused idea for this format: from `category` if given (falling back to any
    category), otherwise from the category furthest below its share of `catalog.mix`."""
    ideas = load(cfg)
    bucket = length_bucket(cfg.format, minutes or cfg.target_minutes)
    fresh = [i for i in ideas if i.topic not in used]
    fits = [i for i in fresh if bucket in i.formats]
    if not fits and bucket != "short":  # any long-form idea can stretch or shrink a little
        fits = [i for i in fresh if set(i.formats) & {"medium", "long", "sleep"}]
    if not fits:
        return None
    if category:
        same = [i for i in fits if i.category == category]
        if same:
            return same[0]
        print(f"note: no unused {category} ideas for a {bucket} video; picking by the content mix")
    made = Counter(i.category for i in ideas if i.topic in used)
    total = sum(made.values()) or 1
    mix = cfg.catalog.mix
    weight = sum(mix.values()) or 1

    def deficit(i: Idea) -> float:
        return mix.get(i.category, 0) / weight - made[i.category] / total

    # Stable: among equally short categories, the idea listed first wins.
    return max(fits, key=lambda i: (deficit(i), -fits.index(i)))


def brief(idea: Idea, cfg: Config) -> str:
    """The idea as the opening of the research notes."""
    lines = [
        f"# {idea.title}",
        f"Category: {idea.category}" + (f" | Pillar: {idea.pillar}" if idea.pillar else ""),
    ]
    if idea.series:
        lines.append(f"Series: {idea.series}")
    if idea.angle:
        lines.append(f"Angle: {idea.angle}")
    if idea.scriptures:
        lines.append("Key Scriptures: " + "; ".join(idea.scriptures))
    return "\n".join(lines)


def summary(cfg: Config) -> str:
    """Counts per category and format, for `fyt ideas`."""
    ideas = load(cfg)
    cats = Counter(i.category for i in ideas)
    fmts = Counter(f for i in ideas for f in i.formats)
    series = Counter(i.series for i in ideas if i.series)
    return (
        f"{len(ideas)} ideas\n"
        + "by category: " + ", ".join(f"{k} {v}" for k, v in cats.most_common()) + "\n"
        + "by format:   " + ", ".join(f"{k} {fmts[k]}" for k in FORMATS) + "\n"
        + "by series:   " + ", ".join(f"{k} {v}" for k, v in series.most_common())
    )
