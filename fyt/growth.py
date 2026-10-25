"""What makes videos find viewers: sharper titles and hooks, better topics, series,
Shorts cut from long videos, and bonus videos on topics trending on Wikipedia.

Everything here is a nice-to-have on top of the pipeline: when a call fails, the
video is still made the plain way.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import requests
from pydantic import BaseModel, Field

from fyt import llm, wiki
from fyt.config import Config
from fyt.models import Script, ScriptScene

# --- Titles, hooks, thumbnails ------------------------------------------------


class Polish(BaseModel):
    titles: list[str] = Field(description="5 different title ideas, each max 70 characters.")
    best_title: str = Field(description="The strongest of the titles (or a better one), max 70 characters.")
    thumbnail_text: str = Field(description="2-5 punchy words for the thumbnail, different from the title.")
    thumbnail_alternatives: list[str] = Field(
        default_factory=list,
        description="2 more thumbnail texts (2-4 words each), each from a different angle (the feeling, the "
        "promise of the passage, the story's moment), for a thumbnail A/B test.",
    )
    hook: str = Field(description="New opening narration: 1-2 sentences, max 35 words, facts from the script only.")
    loop_line: str = Field(default="", description="Shorts only: last sentence, max 12 words, that flows back into the hook.")
    series: str = Field(default="", description="The series this video belongs to, exactly as listed, or empty.")


POLISH_GUIDE = """You are the packaging editor of a faceless Christian encouragement channel. The script is
written; your job is to help the person who needs this video find it and stay with it, without manipulating them.

Channel promise: {niche}
Audience: {audience}
Format: {format}

Titles:
- max 70 characters, honest and specific, and true to the passage the video is about
- {title_rule}
- don't open the title with "Biblical", "Bible Verse" or "Christian". The video must really deliver what
  the title promises.
- no fear-mongering, no "God is warning you", no "skip this and...", no ALL CAPS words except one short one
  at most, no emoji
{thumb_rule}
Hook: rewrite the opening so the first sentence alone makes the right person stop scrolling: open inside the
feeling ("It's late, and you're still carrying it."), or inside the story's moment of tension. Keep it spoken,
short and deliberate. No "welcome back", no "in this video", no
"did you know". Keep Scripture quotes exactly as they are. Use only what appears in the script.
{loop_rule}{series_rule}"""


THUMB_RULE = 'Thumbnail text: 2-4 words that add emotion to the title rather than repeat it (e.g. "NOT FORGOTTEN").'
# Story videos: every thumbnail shows its own story's central conflict, with as few words as possible.
STORY_THUMB_RULE = (
    "Thumbnail text: 1-3 words that name this story's central conflict or dramatic question, not a feeling any "
    'video could have (e.g. "ONE STONE", "SOLD BY HIS BROTHERS", "PRAY OR DIE"). Minimal; the picture carries it.'
)
STORY_THUMB_WORDS = 4


def polish(cfg: Config, script: Script, title_style: str = "cinematic", story: bool = False) -> Script:
    """Rewrite the title, thumbnail text and opening line for clicks and retention, in the given
    title style; a title in the banned "When X, Remember Y" shape is never kept. `story`: a story video,
    whose thumbnail names its central conflict in a few words."""
    short = cfg.format == "short"
    narration = " ".join(s.narration for s in script.scenes)
    series = cfg.growth.series
    guide = POLISH_GUIDE.format(
        niche=cfg.channel.niche,
        audience=cfg.channel.audience,
        format="YouTube Short (vertical, under a minute)" if short else "long video",
        loop_rule=(
            "Loop line: Shorts replay automatically. Write a last sentence that leads straight back into the hook, "
            "so the replay feels seamless.\n"
            if short and cfg.growth.loop_shorts
            else "Leave loop_line empty.\n"
        ),
        series_rule=f"Series: pick the one that fits best: {', '.join(series)}.\n" if series else "Leave series empty.\n",
        title_rule=llm.title_rule(title_style),
        thumb_rule=STORY_THUMB_RULE if story else THUMB_RULE,
    )
    user = (
        f"Current title: {script.title}\nCurrent thumbnail text: {script.thumbnail_text}\n"
        f"Opening narration: {script.scenes[0].narration if script.scenes else ''}\n\n"
        f"Full narration:\n{narration[:3000]}"
    )
    p = llm.structured(cfg, guide, user, Polish, max_tokens=2000)
    scenes = list(script.scenes)
    hook = p.hook.strip()
    if scenes and hook and len(hook.split()) <= 45:
        scenes[0] = scenes[0].model_copy(update={"narration": hook})
    loop = p.loop_line.strip()
    if short and cfg.growth.loop_shorts and scenes and loop and len(loop.split()) <= 16:
        scenes[-1] = scenes[-1].model_copy(update={"narration": scenes[-1].narration.rstrip() + " " + loop})
    options = [p.best_title.strip(), *[t.strip() for t in p.titles]]
    title = next((t for t in options if 10 <= len(t) <= 100 and not llm.title_banned(t)), "")
    update = {"scenes": scenes}
    if title:
        update["title"] = title
    if p.thumbnail_text.strip() and (not story or len(p.thumbnail_text.split()) <= STORY_THUMB_WORDS):
        update["thumbnail_text"] = p.thumbnail_text.strip()
    main = update.get("thumbnail_text", script.thumbnail_text)
    alts = [t.strip() for t in p.thumbnail_alternatives if t.strip() and t.strip().lower() != main.lower()]
    if alts:
        update["thumbnail_variants"] = list(dict.fromkeys(alts))[:2]
    if p.series in series:
        update["series"] = p.series
    return script.model_copy(update=update)


# --- Topic choice ---------------------------------------------------------------

PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{lang}.wikipedia/all-access/user/{title}/daily/{start}/{end}"


def pageviews(cfg: Config, title: str, days: int = 30, today: date | None = None) -> int:
    """How many people read the article over the last `days` days: a free signal of interest."""
    end = (today or datetime.now(timezone.utc).date()) - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    url = PAGEVIEWS.format(
        lang=cfg.wikipedia.lang,
        title=quote(title.replace(" ", "_"), safe=""),
        start=start.strftime("%Y%m%d"),
        end=end.strftime("%Y%m%d"),
    )
    r = requests.get(url, headers={"User-Agent": wiki.user_agent()}, timeout=30)
    if r.status_code == 404:
        return 0
    r.raise_for_status()
    return sum(item.get("views", 0) for item in r.json().get("items", []))


def page_lengths(cfg: Config, titles: list[str]) -> dict[str, int]:
    """Size of each article's source text in bytes (roughly its length), 50 titles per request."""
    out: dict[str, int] = {}
    for i in range(0, len(titles), 50):
        body = wiki._api(cfg, action="query", prop="info", titles="|".join(titles[i : i + 50]), redirects=1)
        for page in body.get("query", {}).get("pages", []):
            if not page.get("missing"):
                out[page["title"]] = page.get("length", 0)
        for r in body.get("query", {}).get("redirects", []):  # keep the title we asked about
            if r["to"] in out:
                out[r["from"]] = out[r["to"]]
    return out


class TopicScore(BaseModel):
    title: str
    fit: int = Field(description="0-10: how well a video on this fits the channel and would fascinate its audience.")


class TopicScores(BaseModel):
    scores: list[TopicScore]


RANK_GUIDE = """You choose topics for a faceless Christian YouTube channel.

Channel niche: {niche}
Audience: {audience}

Rate every candidate Wikipedia article 0-10 for how well a video about it fits this channel and would
move its audience. 8-10: a Bible figure, story, place or teaching with a clear lesson for everyday life. 5-7: fits
but ordinary. 0-4: off-niche (for example celebrities, sports, companies, lists, church politics, controversies).
Score 0 for anything about a recent death, a recent tragedy or disaster with living victims, current politics
or elections, or a private person.
{extra}"""


def score_topics(cfg: Config, candidates: list[tuple[str, int]], extra: str = "") -> dict[str, int]:
    """candidates: (title, 30-day pageviews). Returns title -> fit 0-10."""
    guide = RANK_GUIDE.format(niche=cfg.channel.niche, audience=cfg.channel.audience, extra=extra)
    user = "Candidates (title | readers in the last 30 days):\n" + "\n".join(f"- {t} | {v}" for t, v in candidates)
    scores = llm.structured(cfg, guide, user, TopicScores, max_tokens=2500)
    return {s.title: max(0, min(10, s.fit)) for s in scores.scores}


def rank(fits: dict[str, int], views: dict[str, int], min_fit: int) -> list[str]:
    """Best first: fit matters most, demand (log of readers) breaks ties."""
    ok = [t for t, f in fits.items() if f >= min_fit and t in views]
    return sorted(ok, key=lambda t: fits[t] + 0.3 * math.log10(1 + views[t]), reverse=True)


def pick_topics(
    cfg: Config,
    n: int,
    used: set[str],
    min_chars: int | None = None,
    performance: str = "",
    rng: random.Random | None = None,
    sample: int = 30,
) -> list[str]:
    """Up to n unused articles, chosen for fit with the niche and reader interest.
    Falls back to a random pick when ranking isn't possible."""
    min_chars = min_chars or cfg.wikipedia.min_chars
    if not cfg.growth.rank_topics:
        return wiki.pick_articles(_with_min(cfg, min_chars), n, used, rng)
    try:
        pool = [t for t in wiki.candidates(cfg) if wiki.topic_for(t) not in used]
        (rng or random).shuffle(pool)
        lengths = page_lengths(cfg, pool[: sample * 2])
        # Source text is longer than the readable text, so this is only a first cut.
        pool = [t for t in pool[: sample * 2] if lengths.get(t, 0) >= min_chars][:sample]
        views = {t: pageviews(cfg, t) for t in pool}
        extra = f"What has performed well on the channel so far:\n{performance}\n" if performance else ""
        order = rank(score_topics(cfg, list(views.items()), extra), views, cfg.growth.min_topic_fit)
    except Exception as e:
        print(f"::warning::could not rank topics ({e}); picking at random")
        return wiki.pick_articles(_with_min(cfg, min_chars), n, used, rng)
    picked: list[str] = []
    for title in order:
        if len(picked) >= n:
            break
        try:
            article = wiki.fetch_article(cfg, title)
        except Exception as e:
            print(f"skipping {title}: {e}")
            continue
        if len(article.text) >= min_chars and wiki.topic_for(article.title) not in used:
            picked.append(article.title)
    return picked


def _with_min(cfg: Config, min_chars: int) -> Config:
    return cfg.model_copy(update={"wikipedia": cfg.wikipedia.model_copy(update={"min_chars": min_chars})})


# --- Trending topics --------------------------------------------------------------

FEED = "https://{lang}.wikipedia.org/api/rest_v1/feed/featured/{day:%Y/%m/%d}"


def trending_candidates(cfg: Config, day: date | None = None) -> list[tuple[str, int]]:
    """(title, readers) for yesterday's most-read articles and today's anniversaries."""
    day = day or datetime.now(timezone.utc).date()
    r = requests.get(FEED.format(lang=cfg.wikipedia.lang, day=day), headers={"User-Agent": wiki.user_agent()}, timeout=30)
    r.raise_for_status()
    body = r.json()
    out: dict[str, int] = {}
    for a in (body.get("mostread") or {}).get("articles", [])[:40]:
        out[_title(a)] = a.get("views", 0)
    for event in (body.get("onthisday") or [])[:15]:
        for page in event.get("pages", [])[:2]:
            out.setdefault(_title(page), 0)
    out.pop("Main Page", None)
    return list(out.items())


def _title(page: dict) -> str:
    return page.get("normalizedtitle") or (page.get("titles") or {}).get("normalized") or page["title"].replace("_", " ")


def pick_trending(cfg: Config, used: set[str], min_fit: int, min_chars: int, day: date | None = None) -> str | None:
    """The trending article that fits the channel best, if any fits well enough."""
    cands = [(t, v) for t, v in trending_candidates(cfg, day) if wiki.topic_for(t) not in used]
    if not cands:
        return None
    extra = (
        "These are trending today (most read yesterday, or today's anniversaries). Only rate high what a "
        "viewer of this channel would genuinely want; a trending subject outside the niche is still off-niche.\n"
    )
    fits = score_topics(cfg, cands, extra)
    views = dict(cands)
    for title in rank(fits, views, min_fit):
        try:
            article = wiki.fetch_article(cfg, title)
        except Exception as e:
            print(f"skipping {title}: {e}")
            continue
        if len(article.text) >= min_chars and wiki.topic_for(article.title) not in used:
            print(f"trending pick: {article.title} (fit {fits[title]}/10, {views[title]} readers)")
            return article.title
    return None


# --- Shorts cut from a long video -------------------------------------------------

CUT_WORDS = 140
# The last words of a Short cut from a long video: a calm pointer to the full video (linked at the very top
# of the description and, set by hand in Studio, as the Short's related video). Never a hard sell.
CUT_ENDINGS = (
    "There is more to this story. The full video is linked with this one, whenever you're ready.",
    "If you'd like to stay with this a little longer, the full video is linked with this Short.",
    "The whole story is waiting in the full video, linked with this one. Take your time.",
)


class CutChoice(BaseModel):
    chapters: list[int] = Field(description="Numbers of the chapters that work best as standalone Shorts, best first.")


CUT_GUIDE = (
    "Pick the chapters of this video that would each work as a standalone YouTube Short. Each must be complete "
    "on its own: a mini-story with its own tension and turn, or one teaching with the Scripture it rests on, "
    "understandable without the rest. Pick chapters from different moments of the story (not neighbours, not "
    "the same beat twice), best first. Skip chapters that only set up or only reflect."
)


def spread(choice: list[int], count: int, n: int) -> list[int]:
    """Up to n chapter numbers from the model's choice (1..count), best first, skipping a chapter next to
    one already picked while others are left: cuts come from different moments of the story."""
    valid = [c for c in dict.fromkeys(choice) if 1 <= c <= count]
    picked: list[int] = []
    for c in valid:
        if len(picked) < n and all(abs(c - p) > 1 for p in picked):
            picked.append(c)
    for c in valid:  # not enough far-apart chapters: neighbours are still better than nothing
        if len(picked) < n and c not in picked:
            picked.append(c)
    return picked


def cut_scripts(cfg: Config, script: Script, video_id: str, n: int) -> list[Script]:
    """Standalone Short scripts from the strongest chapters of a long video, each pointing to the full video."""
    groups = _chapter_groups(script)
    if n <= 0 or len(groups) < 2:
        return []
    menu = "\n".join(f"{i}. {title}: {' '.join(s.narration for s in scenes)[:400]}" for i, (title, scenes) in enumerate(groups, 1))
    try:
        choice = llm.structured(cfg, CUT_GUIDE, menu, CutChoice, max_tokens=1000).chapters
    except Exception as e:
        print(f"::warning::could not choose chapters to cut ({e}); using the middle ones")
        choice = list(range(2, len(groups) + 1))
    picked = spread(choice, len(groups), n)

    link = f"https://youtu.be/{video_id}"
    out = []
    for c in picked:
        title, scenes = groups[c - 1]
        kept, words = [], 0
        for s in scenes:
            w = len(s.narration.split())
            if kept and words + w > CUT_WORDS:
                break
            kept.append(s.model_copy(update={"image": None}))  # article images aren't fetched for cuts
            words += w
        if kept[0].type != "title":
            kept[0] = kept[0].model_copy(update={"type": "title", "heading": title})
        kept[-1] = kept[-1].model_copy(update={
            "narration": kept[-1].narration.rstrip() + " " + CUT_ENDINGS[(c - 1) % len(CUT_ENDINGS)],
            "pause_after": max(kept[-1].pause_after or 0, 1.5),  # let it settle before the closing card
        })
        out.append(
            script.model_copy(
                update={
                    "title": title[:70],
                    "description": _cut_description(script.description, link),
                    "scenes": kept,
                    "chapters": None,
                    "thumbnail_text": title,
                }
            )
        )
    return out


def _chapter_groups(script: Script) -> list[tuple[str, list[ScriptScene]]]:
    if script.chapters:
        starts = [c.scene for c in script.chapters] + [len(script.scenes)]
        return [(c.title, script.scenes[a:b]) for c, a, b in zip(script.chapters, starts, starts[1:]) if b > a]
    size = 6  # no chapters (written in one go): cut the video into even parts
    return [(script.title, script.scenes[i : i + size]) for i in range(0, len(script.scenes), size)]


def _cut_description(description: str, link: str) -> str:
    """The link to the full video first (the line people see before "more"), then the long video's
    opening paragraph and the credits a cut still needs."""
    first = description.split("\n\n")[0].strip()
    # Wikipedia's licence needs its credit; quoted Scripture keeps its translation credit.
    credit = [line for line in description.splitlines() if "CC BY-SA" in line or "Scripture quotations" in line]
    return "\n\n".join([f"Full video: {link}", first, *credit])


# --- One video, many pieces: storyboard, quote cards, prayer, community post ------------


class QuoteCard(BaseModel):
    text: str = Field(description="Max 22 words: a line from the video, or a Scripture quoted exactly from it.")
    reference: str = Field(description="The Bible reference for Scripture, or empty for a line of the channel's own.")


class Extras(BaseModel):
    quote_cards: list[QuoteCard] = Field(description="3 quote cards for images and community posts.")
    prayer_title: str = Field(description='e.g. "A Prayer When Life Feels Unfair".')
    prayer: str = Field(description="A short first-person prayer (80-140 words) on the video's theme, ending in Amen.")
    community_post: str = Field(description="A warm question for the Community tab that invites people to share (max 60 words).")
    pinned_comment: str = Field(description="A pinned comment: one encouraging line plus a question (max 40 words).")
    short_ideas: list[str] = Field(description="6 standalone Shorts from this video: each a hook line, max 12 words.")


REPURPOSE_GUIDE = """You repurpose one video of a Christian encouragement channel into more pieces of content.
Channel promise: {niche}
Tone: {tone}
Use only what is in the script; quote Scripture exactly as it appears there, with its reference.
Never invent verses or put words in Jesus' mouth."""


def repurpose(cfg: Config, script: Script) -> Extras:
    """Quote cards, a prayer, a community post, a pinned comment and 6 Short ideas from one script."""
    narration = "\n".join(s.narration for s in script.scenes)
    quotes = "\n".join(f"- {s.text} ({s.author})" for s in script.scenes if s.type == "quote" and s.text)
    user = f"Title: {script.title}\n\nOn-screen quotes:\n{quotes or '(none)'}\n\nNarration:\n{narration[:6000]}"
    guide = REPURPOSE_GUIDE.format(niche=cfg.channel.niche, tone=cfg.channel.tone)
    return llm.structured(cfg, guide, user, Extras, max_tokens=2500)


def extras_markdown(script: Script, extras: Extras | None) -> str:
    """The storyboard (every scene's narration and shot) plus the repurposed pieces, for extras.md."""
    out = [f"# {script.title}", ""]
    if script.series:
        out += [f"Series: {script.series}", ""]
    if extras:
        out += ["## Quote cards", *[f"- \"{q.text}\"" + (f" ({q.reference})" if q.reference else "") for q in extras.quote_cards], ""]
        out += [f"## {extras.prayer_title}", extras.prayer, ""]
        out += ["## Community post", extras.community_post, ""]
        out += ["## Pinned comment", extras.pinned_comment, ""]
        out += ["## Shorts from this video", *[f"{i}. {t}" for i, t in enumerate(extras.short_ideas, 1)], ""]
    out += ["## Storyboard", "", "| # | Template | Narration | Shot | Footage search |", "|---|---|---|---|---|"]
    cell = lambda t: (t or "").replace("|", "/").replace("\n", " ")  # noqa: E731
    for i, sc in enumerate(script.scenes, 1):
        out.append(f"| {i} | {sc.type} | {cell(sc.narration)} | {cell(sc.visual_prompt)} | {cell(sc.broll_query)} |")
    return "\n".join(out) + "\n"
