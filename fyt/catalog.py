"""The channel's curated idea list (content/ideas.yaml) as a content source.

Each idea names its category, series, suitable formats, the Scripture it rests on and,
for Bible stories, a Wikipedia article for background and classical artwork. The next
idea is chosen to keep the content mix on target (config `catalog.mix`), or from the
category a publish slot asks for (config `schedule.plan`).

Every idea belongs to one of four content pillars (PILLARS); with `catalog.pillars` set, the picker
keeps those in balance instead of the categories. content/backlog.yaml holds the evergreen Bible
stories for the weekly evergreen long video (fyt/slate.py).
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from fyt.config import ROOT, SLEEP_MINUTES, Config

PREFIX = "idea:"
FORMATS = ("short", "medium", "long", "sleep")
# Story shapes. Every video makes the viewer feel something, but not always by the same road.
ARCS = ("journey", "story", "curiosity", "wisdom", "prayer", "peace", "joy")
DEFAULT_ARC = {
    "bible_story": "story", "jesus": "story", "prayer": "prayer", "peace": "peace",
    "wisdom": "wisdom", "history": "curiosity", "everyday_life": "wisdom",
}
# The four content pillars: story-first, Scripture first.
PILLARS = {
    "stories": "Bible stories told like films (Joseph, Moses, David, Esther, Daniel, Peter, Paul, the prodigal son...)",
    "teachings": "teachings of Jesus and Scripture (parables, hard sayings) in their original context",
    "struggles": "human struggles inside Scripture (fear, betrayal, guilt, doubt, forgiveness, courage, repentance), "
    "always through a specific event, never generic motivation",
    "questions": "overlooked moments and biblical questions: surprising details, misunderstood passages, context",
}


class Idea(BaseModel):
    id: str
    title: str
    category: str  # the pillar that sets the content mix (see content/ideas.yaml)
    emotion: str = ""  # what the viewer should feel: courage, love, grief, peace, joy, curiosity...
    character: str = ""  # the Bible person at the centre, if any
    arc: str = ""  # story shape (ARCS); empty means the category's default
    pillar: str = ""
    series: str | None = None
    formats: list[str] = Field(default_factory=lambda: ["short", "medium"])
    scriptures: list[str] = Field(default_factory=list)
    wiki: str | None = None  # Wikipedia article for background and artwork
    angle: str = ""  # the pain point or hook, and what the viewer should leave with
    truth: str = ""  # the passage's central truth in one sentence, as the editor reads it (optional)
    content_type: str = ""  # story, parable, miracle, verse, question, character, wisdom, prayer, history...
    generated: bool = False  # written by the model when the list ran low (stored in jobs/state.db)
    music: str = ""  # calm | cinematic: overrides the music the category would get (calendar videos)
    # Calendar series: every title of the video starts with this, e.g. "Advent: Day 3 · " (also the thumbnail kicker)
    title_prefix: str = ""
    # Story-first (content/backlog.yaml, fyt/slate.py)
    style: str = ""  # cinematic | illustrated | documentary (long videos); empty: the pillar's default
    passage: str = ""  # the passage as cited, e.g. "Genesis 37-50" (`scriptures` are the verses quoted)
    question: str = ""  # the one dramatic question the video turns on
    minutes: float | None = None  # the long video's length, inside its style's range
    priority: int | None = None  # backlog seed order
    score: dict[str, float] = Field(default_factory=dict)  # significance, story, appeal, seasonal, effort (1-5)
    backlog: bool = False  # from content/backlog.yaml

    @property
    def topic(self) -> str:
        return PREFIX + self.id

    @property
    def shape(self) -> str:
        return self.arc if self.arc in ARCS else DEFAULT_ARC.get(self.category, "journey")


def pillar_of(idea: Idea) -> str:
    """The idea's content pillar: its own, or the one its category and shape fall in."""
    if idea.pillar in PILLARS:
        return idea.pillar
    if idea.shape == "curiosity" or idea.content_type == "question" or idea.category == "history":
        return "questions"
    if idea.content_type == "parable":
        return "teachings"
    if idea.category == "bible_story" or (idea.category == "jesus" and idea.shape == "story"):
        return "stories"
    if idea.category in ("wisdom", "peace", "jesus") or idea.shape in ("wisdom", "peace"):
        return "teachings"
    return "struggles"


def is_idea(topic: str) -> bool:
    return topic.startswith(PREFIX)


def _read(path: Path, **extra) -> list[Idea]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [Idea.model_validate({**i, **extra}) for i in raw.get("ideas", [])]


def _path(name: str) -> Path:
    path = Path(name)
    return path if path.is_absolute() else ROOT / path


def _generated(cfg: Config) -> list[Idea]:
    """Ideas the model wrote when a pillar ran low. They live in jobs/state.db, next to the topic
    queue, so the GitHub workflow's existing cache keeps them between runs."""
    db_path = cfg.jobs_path / "state.db"
    if not db_path.exists():
        return []
    import sqlite3

    db = sqlite3.connect(db_path)
    try:
        rows = db.execute("select body from ideas order by rowid").fetchall()
    except sqlite3.OperationalError:  # no ideas written yet
        return []
    finally:
        db.close()
    return [Idea.model_validate(yaml.safe_load(r[0])) for r in rows]


def _save_generated(cfg: Config, ideas: list[dict]) -> None:
    import sqlite3

    cfg.jobs_path.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(cfg.jobs_path / "state.db")
    db.execute("create table if not exists ideas (id text primary key, body text not null)")
    db.executemany(
        "insert or ignore into ideas(id, body) values (?, ?)",
        [(i["id"], yaml.safe_dump(i, allow_unicode=True, sort_keys=False)) for i in ideas],
    )
    db.commit()
    db.close()


def load(cfg: Config) -> list[Idea]:
    """The curated ideas, the evergreen backlog, then the ones the model added when the list ran low (see `top_up`)."""
    path = _path(cfg.catalog.path)
    ideas = _read(path) + _read(_path(cfg.catalog.backlog), backlog=True)
    seen = {i.id for i in ideas}
    ideas += [i for i in _generated(cfg) if i.id not in seen]
    ids = [i.id for i in ideas]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate idea ids in {path}: {', '.join(sorted(dupes))}")
    return ideas


def get(cfg: Config, topic_or_id: str) -> Idea:
    key = topic_or_id.removeprefix(PREFIX)
    if "@" in key:  # a Christian-calendar campaign video, e.g. "easter-he-is-risen@2027"
        from fyt import liturgy

        data = liturgy.idea_data(cfg, key.split("@")[0])
        if data is None:
            raise KeyError(f"no calendar video {key!r} in {cfg.liturgy.path}")
        return Idea.model_validate({**data, "id": key})
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
    if minutes < SLEEP_MINUTES:
        return "long"
    return "sleep"


def pick(
    cfg: Config,
    used: set[str],
    category: str | None = None,
    minutes: float | None = None,
    recent: list[str] | None = None,
    season: dict | None = None,
    weights: dict[str, float] | None = None,
) -> Idea | None:
    """The next unused idea for this format: from `category` if given (falling back to any
    category), otherwise from the category furthest below its share of `catalog.mix`.

    Within a category, ideas that repeat the emotion, Bible character or story shape of the last
    few videos (`recent`, topics newest last) wait their turn, so the channel keeps its variety.
    In a season of the Christian year (`season`, see liturgy.season) ideas with its feelings go first,
    and its pillars get a little extra weight in the mix. `weights` (fyt/insights.py: pillars viewers
    stay with, x0.8..x1.25) scale each pillar's share of the mix a little."""
    season = season or {}
    feel = set(season.get("emotions") or [])
    lean = set(season.get("categories") or [])

    def off_season(i: "Idea") -> int:
        return 0 if (not feel or i.emotion in feel) else 1
    ideas = load(cfg)
    by_topic = {i.topic: i for i in ideas}
    last = [by_topic[t] for t in (recent or [])[-6:] if t in by_topic]

    def repeats(i: Idea) -> int:
        """How much an idea repeats the recent videos (lower is fresher)."""
        score = 0
        for k, r in enumerate(reversed(last)):  # the latest counts most
            w = 3 if k < 2 else 1
            score += w * (bool(i.character) and i.character == r.character)
            score += w * (bool(i.emotion) and i.emotion == r.emotion)
            score += (k < 2) * (i.shape == r.shape)
            score += (k < 2) * (bool(i.content_type) and i.content_type == r.content_type)
        return score

    bucket = length_bucket(cfg.format, minutes or cfg.target_minutes)
    # Bonus ideas wait for fyt/bonus.py, backlog stories for the evergreen slot (fyt/slate.py).
    fresh = [i for i in ideas if i.topic not in used and not i.id.startswith("bonus-") and not i.backlog]
    fits = [i for i in fresh if bucket in i.formats]
    if not fits and bucket != "short":  # any long-form idea can stretch or shrink a little
        fits = [i for i in fresh if set(i.formats) & {"medium", "long", "sleep"}]
    if not fits:
        return None
    if category:
        same = [i for i in fits if i.category == category]
        if same:
            return min(same, key=lambda i: (repeats(i), off_season(i), same.index(i)))
        print(f"note: no unused {category} ideas for a {bucket} video; picking by the content mix")
    # Story-first: the four content pillars are kept in balance; otherwise the categories of `mix`.
    key = pillar_of if cfg.catalog.pillars else (lambda i: i.category)
    made = Counter(key(i) for i in ideas if i.topic in used)
    total = sum(made.values()) or 1
    weights = weights or {}
    mix = {k: v * weights.get(k, 1.0) for k, v in (cfg.catalog.pillars or cfg.catalog.mix).items()}
    weight = sum(mix.values()) or 1

    def deficit(i: Idea) -> float:
        bonus = 0.05 if i.category in lean else 0.0  # roughly a fifth more of the season's pillars
        return mix.get(key(i), 0) / weight - made[key(i)] / total + bonus

    # The category furthest below its share; within it the freshest idea, then the one listed first.
    best = max(deficit(i) for i in fits)
    pool = [i for i in fits if deficit(i) == best]
    return min(pool, key=lambda i: (repeats(i), off_season(i), pool.index(i)))


def counts(cfg: Config, used: set[str]) -> Counter:
    """Unused ideas per category."""
    return Counter(i.category for i in load(cfg) if i.topic not in used)


LOW_WATER = 4  # unused ideas left in a category before new ones are written


def top_up(cfg: Config, used: set[str], category: str | None, recent: list[str], n: int = 8) -> int:
    """When a pillar runs low, ask the model for new ideas in the same shape and keep the valid ones
    (in jobs/state.db, cached between GitHub runs). Returns how many were added."""
    from fyt import llm, scripture

    left = counts(cfg, used)
    if not category and cfg.catalog.pillars:  # the pillars span categories; a slot's own category still tops up
        return 0
    cats =[category] if category else [c for c in cfg.catalog.mix if cfg.catalog.mix[c] > 0]
    low = [c for c in cats if left.get(c, 0) < LOW_WATER]
    if not low:
        return 0
    ideas = load(cfg)
    by_topic = {i.topic: i for i in ideas}
    people = [by_topic[t].character for t in recent if t in by_topic and by_topic[t].character]
    added: list[dict] = []
    for cat in low[:2]:  # at most two pillars per run keeps the free tier happy
        titles = [i.title for i in ideas] + [a["title"] for a in added]
        examples = "\n".join(
            f"- {i.title} | {i.emotion}/{i.shape} | {i.character or '-'} | {', '.join(i.scriptures)} | {i.angle}"
            for i in [i for i in ideas if i.category == cat and not i.generated][:6]
        )
        for new in llm.ideate_catalog(cfg, cat, n, titles, people, examples):
            # Keep only references that parse and exist in the Bible text.
            refs = [r for r in new.scriptures if scripture.find_references(r) == [r]]
            refs = [r for r in refs if r in scripture.fetch_all(cfg, [r])]
            slug = re.sub(r"[^a-z0-9]+", "-", (new.id or new.title).lower()).strip("-")[:60]
            if not refs or not slug or slug in {i.id for i in ideas} | {a["id"] for a in added}:
                continue
            added.append({
                "id": slug, "title": new.title, "category": cat, "emotion": new.emotion,
                "character": new.character, "arc": new.arc if new.arc in ARCS else DEFAULT_ARC.get(cat, "journey"),
                "formats": [f for f in new.formats if f in FORMATS] or ["short", "medium"],
                "scriptures": refs, "angle": new.angle, "generated": True,
            })
    if added:
        _save_generated(cfg, added)
        print(f"added {len(added)} new ideas for {', '.join(low[:2])}")
    return len(added)


def brief(idea: Idea, cfg: Config) -> str:
    """The idea as the opening of the research notes."""
    lines = [
        f"# {idea.title}",
        f"Category: {idea.category} | Pillar: {pillar_of(idea)} ({PILLARS[pillar_of(idea)]})",
        f"Story shape: {idea.shape}" + (f" | Feeling: {idea.emotion}" if idea.emotion else ""),
    ]
    if idea.passage:
        lines.append(f"Passage: {idea.passage}")
    if idea.question:
        lines.append(f"The dramatic question (the whole video turns on it): {idea.question}")
    if idea.character:
        lines.append(f"At the centre: {idea.character}")
    if idea.series:
        lines.append(f"Series: {idea.series}")
    if idea.angle:
        lines.append(f"Angle: {idea.angle}")
    if idea.truth:
        lines.append(f"Central truth (the editor's reading; build on it): {idea.truth}")
    if idea.scriptures:
        lines.append("Key Scriptures: " + "; ".join(idea.scriptures))
    return "\n".join(lines)


def summary(cfg: Config) -> str:
    """Counts per category and format, for `fyt ideas`."""
    ideas = load(cfg)
    cats = Counter(i.category for i in ideas)
    pillars = Counter(pillar_of(i) for i in ideas)
    fmts = Counter(f for i in ideas for f in i.formats)
    series = Counter(i.series for i in ideas if i.series)
    return (
        f"{len(ideas)} ideas\n"
        + "by pillar:   " + ", ".join(f"{k} {pillars[k]}" for k in PILLARS) + "\n"
        + f"backlog:     {sum(i.backlog for i in ideas)} evergreen stories\n"
        + "by category: " + ", ".join(f"{k} {v}" for k, v in cats.most_common()) + "\n"
        + "by format:   " + ", ".join(f"{k} {fmts[k]}" for k in FORMATS) + "\n"
        + "by series:   " + ", ".join(f"{k} {v}" for k, v in series.most_common())
    )
