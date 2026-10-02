"""Claude calls: topic ideation, web research, and structured script writing."""

from __future__ import annotations

import json
import os
import time

import anthropic
import requests
from pydantic import BaseModel, Field, ValidationError

from fyt.config import Config
from fyt.models import Chapter, Script, ScriptScene

# Server-side refusal fallbacks: if the primary model declines, the API reroutes
# the same request to a suitable fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}


class ClaudeError(RuntimeError):
    pass


class RequestTooLarge(ClaudeError):
    """The provider rejected the request as too large (e.g. Groq's free tokens-per-minute cap)."""


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(max_retries=4)


def _check(response) -> None:
    if response.stop_reason == "refusal":
        raise ClaudeError(f"Claude declined the request: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise ClaudeError("Response hit max_tokens; raise it or shorten the target length.")


def _text(response) -> str:
    return "\n".join(b.text for b in response.content if b.type == "text").strip()


def _openai_structured(cfg: Config, system: str, user: str, schema: type[BaseModel], max_tokens: int = 16000):
    """Structured output from an OpenAI-compatible API (Groq, OpenRouter, Ollama...).

    Asks for JSON matching the schema, validates it, and on a bad answer retries
    with the validation error so the model can correct itself. If the model keeps
    failing, tries each of `llm.fallback_models` in turn.
    """
    models = [cfg.llm.model, *cfg.llm.fallback_models]
    for i, model in enumerate(models):
        try:
            return _openai_structured_once(cfg, model, system, user, schema, max_tokens)
        except RequestTooLarge:
            raise  # the caller shrinks the request
        except ClaudeError as e:
            if i == len(models) - 1:
                raise
            print(f"{model} failed ({str(e)[:200]}); trying {models[i + 1]}")
    raise AssertionError("unreachable")


def _openai_structured_once(
    cfg: Config, model: str, system: str, user: str, schema: type[BaseModel], max_tokens: int
):
    c = cfg.llm
    key = os.environ.get(c.api_key_env)
    if not key and "localhost" not in c.base_url:
        raise ClaudeError(f"{c.api_key_env} is not set")
    system += (
        "\n\nReply with a single JSON object and nothing else. It must match this JSON schema:\n"
        + json.dumps(schema.model_json_schema(), separators=(",", ":"))
    )
    body = {
        "model": model,
        "temperature": c.temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if c.reasoning_effort and "gpt-oss" in model:
        body["reasoning_effort"] = c.reasoning_effort
    retry_note = ""
    last_error = ""
    for attempt in range(8):
        # A retry resends the same prompt plus a short note, never the rejected reply,
        # so the request doesn't grow past the provider's tokens-per-minute limit.
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user + retry_note}]
        try:
            r = requests.post(
                f"{c.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key or 'none'}"},
                json={**body, "messages": messages},
                timeout=300,
            )
        except requests.RequestException as e:  # dropped connection or timeout
            last_error = str(e)[:500]
            print(f"request to {c.base_url} failed ({e}); retrying")
            time.sleep(min(10 * (attempt + 1), 60))
            continue
        if r.status_code >= 500 and attempt < 7:  # provider hiccup
            last_error = f"{r.status_code}: {r.text[:300]}"
            print(f"{c.base_url} returned {r.status_code}; retrying")
            time.sleep(min(10 * (attempt + 1), 60))
            continue
        if r.status_code == 429 and attempt < 7:  # free tiers limit tokens per minute
            wait = min(max(float(r.headers.get("retry-after") or 30), 10), 65)
            print(f"rate limited by {c.base_url}; waiting {wait:.0f}s")
            time.sleep(wait)
            continue
        if r.status_code == 413:
            raise RequestTooLarge(f"{c.base_url} returned 413: {r.text[:500]}")
        if r.status_code == 400 and "json_validate_failed" in r.text:
            # Groq rejects replies that aren't valid JSON, e.g. when the model ran out of tokens.
            last_error = r.text[:500]
            print(f"{model} did not produce valid JSON; retrying")
            retry_note = "\n\nYour previous reply was not valid JSON. Keep it concise and reply with the JSON object only."
            continue
        if r.status_code >= 400:
            raise ClaudeError(f"{c.base_url} returned {r.status_code}: {r.text[:500]}")
        content = (r.json()["choices"][0]["message"]["content"] or "").strip()
        if content.startswith("```"):  # tolerate a fenced reply
            content = content.strip("`").removeprefix("json").strip()
        try:
            return schema.model_validate_json(content)
        except ValidationError as e:
            last_error = str(e)[:800]
            print(f"{model} reply did not match the schema; retrying")
            retry_note = f"\n\nYour previous reply did not match the schema:\n{last_error}\nReply with the corrected JSON object only."
    raise ClaudeError(f"{model} did not return a valid answer: {last_error}")


def structured(cfg: Config, system: str, user: str, schema: type[BaseModel], max_tokens: int = 3000):
    """A small structured answer from whichever provider the channel uses."""
    if cfg.llm.provider == "openai":
        return _openai_structured(cfg, system, user, schema, max_tokens=max_tokens)
    response = _client().beta.messages.parse(
        model=cfg.model,
        max_tokens=max(max_tokens, 8000),
        betas=[FALLBACK_BETA],
        fallbacks="default",
        output_config={"effort": "medium"},
        output_format=schema,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    _check(response)
    if response.parsed_output is None:
        raise ClaudeError("Claude did not return a parsable answer.")
    return response.parsed_output


class TopicIdeas(BaseModel):
    topics: list[str]


def ideate_topics(cfg: Config, n: int, avoid: list[str], performance_notes: str = "") -> list[str]:
    """Propose fresh video topics for the channel, skipping ones already covered."""
    ch = cfg.channel
    prompt = f"""You plan videos for a faceless Christian YouTube channel.

Channel promise: {ch.niche}
Audience: {ch.audience}
Format: {"YouTube Shorts (under 60 seconds)" if cfg.format == "short" else f"~{cfg.target_minutes:g} minute videos"}
Series: {", ".join(cfg.growth.series) or "(none)"}

Propose {n} specific video topics. Each must:
- answer "what does this person need to hear right now?" for one recognisable, evergreen struggle
  (fear, waiting, failure, loneliness, grief, temptation, purpose, forgiveness, anxiety, discipline...)
  or tell one Bible story, teaching of Jesus, prayer or fascinating Biblical fact
- be grounded in specific Scripture and faithful to it; mainstream, non-denominational Christian teaching
- be specific (one struggle, one story or one passage, not a broad subject) and phrased the way people search
- avoid news, politics, controversies, date-setting prophecy, prosperity promises and medical advice

Already covered or queued -- do not repeat or closely paraphrase:
{chr(10).join(f"- {t}" for t in avoid) or "- (none yet)"}
{f"{chr(10)}What has performed well so far:{chr(10)}{performance_notes}" if performance_notes else ""}
Return one topic per entry, phrased as a working title."""
    if cfg.llm.provider == "openai":
        ideas = _openai_structured(cfg, "You plan YouTube videos.", prompt, TopicIdeas, max_tokens=4000)
        return [t.strip() for t in ideas.topics if t.strip()][:n]
    response = _client().beta.messages.parse(
        model=cfg.model,
        max_tokens=16000,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        output_config={"effort": "medium"},
        output_format=TopicIdeas,
        messages=[{"role": "user", "content": prompt}],
    )
    _check(response)
    return [t.strip() for t in response.parsed_output.topics if t.strip()][:n]


def research(cfg: Config, topic: str) -> str:
    """Gather facts, figures and sources for the topic using web search."""
    if cfg.llm.provider == "openai":
        print("note: web research needs Claude; writing from the model's own knowledge")
        return ""
    messages: list = [
        {
            "role": "user",
            "content": f"""Research this video topic for a Christian encouragement channel: "{topic}"

Search the web and produce research notes for a scriptwriter:
- the key Bible passages (book chapter:verse) and what they say, in context
- the Bible story or stories behind the lesson: who, where, what happened, how it ended, and above all what
  the people in it would have felt, seen and heard (the details that let a viewer step inside the story)
- historical and cultural background that makes the passage come alive (places, customs, dates where known)
- how mainstream Christian teaching has understood it (avoid fringe or denominational disputes)
- the modern struggle it speaks to, and practical application
- one or two real, verified quotes from well-known Christian writers, with attribution (never invent quotes)
- a gentle, honest hook: the moment of tension or the question the viewer is living with

Prefer reputable sources (Bible commentaries, study Bibles, scholarly or encyclopedia articles). Flag anything
uncertain, and never present legend or tradition as Scripture.""",
        }
    ]
    client = _client()
    # Server-side tool turns can pause; resume by sending the partial turn back.
    for _ in range(5):
        with client.beta.messages.stream(
            model=cfg.model,
            max_tokens=32000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            tools=[WEB_SEARCH],
            messages=messages,
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason != "pause_turn":
            break
        messages.append({"role": "assistant", "content": response.content})
    _check(response)
    return _text(response)


SHORT_SECONDS = 52  # Shorts aim for 45-55 seconds of narration
SHORT_WORDS = 130  # at 150 words a minute; see short_words() for the configured pace


def short_words(cfg: Config) -> int:
    return int(SHORT_SECONDS * cfg.voice.words_per_minute / 60)


# The emotional journey every video follows (channel creative principle: don't just tell them
# about faith, make them feel faith). Each scene sets `mood` to its stage; the narration pace,
# pauses, music and colour grade follow it.
LONG_STRUCTURE = """The journey (in this order; set each scene's `mood` to its stage):
1. struggle: open inside the feeling, in the present tense, with concrete images the viewer knows from
   their own life ("It's late. The house is quiet, and the thing you've been carrying all day is still
   there."). Name it gently and precisely. They should think "that's me".
2. uncertainty: the questions they are afraid to say out loud ("Where are you, God?"). Stay here long
   enough to be honest. Don't rush to fix it.
3. faith: take them into the Bible story as if they were standing there: the dust, the dark, the silence,
   what the person felt. Tell it as an experience, not a summary, and keep connecting it to the viewer
   ("Joseph knew that feeling. The pit. The waiting. The silence.").
4. realization: the turn. The truth that changes everything, carried by the key Scripture, said slowly.
   This is the emotional peak; give it room (pause_after 2-3 seconds).
5. hope: what this means for them, personally and tenderly ("You are not forgotten. Not tonight. Not ever.").
6. strength: rise. Courage to keep going, a short prayer or a declaration they can say with you, and one
   last line they will carry out of the video."""

SHORT_STRUCTURE = """The journey, compressed (set each scene's `mood`): struggle (one line that names exactly
what they feel and stops the scroll) -> faith (the Bible moment, felt, in a few vivid lines) -> realization
(the Scripture, quoted exactly, slowly) -> hope / strength (one line to carry today). No title card and no
greeting: open straight on the feeling."""

PRAYER_STRUCTURE = """This is a prayer video: an experience of praying together, not a talk about prayer.
Open with one or two quiet sentences naming the moment (struggle / uncertainty) and inviting the viewer to
pray along. Then pray slowly in the first person ("Lord, ...") in short lines with room to breathe (faith),
turning to trust as the key Scriptures are woven in word for word (realization, hope), and closing with a
blessing spoken over the viewer and "Amen" (strength). Moods: struggle -> faith -> realization -> hope -> strength."""

SCRIPT_GUIDE = """Write the complete script for a faceless Christian YouTube video on {name}.

Channel: {name} -- {niche}
Audience: {audience}
Tone: {tone}
Language: {language}
Format: {format_line}
Target narration length: about {words} words in total across all scenes.

The creative principle: don't just tell them about faith, make them feel faith. This is an experience of
faith, not a lesson about it. Someone tired, lost, afraid, discouraged or lonely should finish the video
thinking "I needed to hear this", "God has not forgotten me", "I am not alone", "I can keep going",
"there is still hope". Follow the emotional journey struggle -> uncertainty -> faith -> realization -> hope
-> strength, never fact -> explanation -> conclusion.

{structure}

How it sounds (a warm, deep, deliberate narrator reads every word):
- Speak to one person, "you", like someone who has been there, not a teacher and not a preacher.
- Short, spoken sentences. Vary the rhythm: a long line, then a short one. Then shorter.
- Leave space. End a line with "..." where the voice should trail off and breathe. Use repetition that
  builds ("Not forgotten. Not abandoned. Not alone.").
- Never sound like a documentary or a lecture: no "in this video", "let's explore", "scholars say",
  "historically", "the text tells us", "fun fact", "did you know", no dates or numbers unless they hurt or
  heal. Even a Bible fact is a doorway to a feeling.
- Scripture is the heart of the video, not a citation: introduce it like a promise being spoken over them.

Scene templates (field names in brackets). Most scenes should be pictures with the words spoken over them:
- broll: a full-screen cinematic shot [broll_query, optional heading]. Use it for most of the video.
  Leave heading empty unless one short line (max 6 words) should appear on screen.
- statement: one short line on screen over a picture, for the lines that should land [text, broll_query]
- quote: Scripture on screen over a picture [text, author, broll_query]. author is the reference (e.g.
  "Matthew 11:28") and text is the verse's exact wording from the notes.
- title: only to open a long video, after the first struggle line [heading, text, broll_query]
- timeline, list, comparison, stat, bars: avoid. They feel like a lesson.

Every scene:
- mood: its stage in the journey (struggle, uncertainty, faith, realization, hope or strength), in order.
- pause_after: seconds of silence after it (0.5-1 normally, 1.5-3 after a line that should land).
- broll_query: a concrete, filmable stock-footage search that carries the feeling, 2-4 words. Think
  cinematic and immersive: storm clouds, rain on a window at night, a lone figure walking in the rain, a
  desert road, fog over mountains, a candle in the dark, hands folded in prayer, light breaking through
  clouds, sunrise over mountains, a person on a summit, a cross on a hill, an old stone path, a shepherd
  with sheep, waves in a storm, a field of wheat in golden light. Match the mood: darkness, storms and
  solitude for struggle; fog and empty roads for uncertainty; candlelight and prayer for faith; light
  breaking through for realization; sunrise and open landscapes for hope; summits, walking forward and
  the cross for strength. (A search for a Bible character by name finds nothing; describe the shot.)
- visual_prompt: one cinematic sentence for the storyboard: setting, light, mood, camera movement.
- 1-4 sentences of narration that match what is on screen.

Rules:
- The first sentence is the hook: open inside the feeling or inside the story. No greeting.
- Scripture: quote only the exact verse text given in the notes, and name the reference. If a verse isn't
  in the notes, paraphrase it clearly as a paraphrase and give the reference. Never invent or merge
  verses, and never put words in Jesus' mouth.
- Stay faithful to the Bible story: feelings, sounds and light may be imagined as scene-setting, never new
  events. Mainstream Christian teaching; no politics, prosperity promises, guilt, fear tactics or medical advice.
- End on strength: the line they carry, then (only in long videos) one gentle invitation to subscribe
  or pray along.
- Title max 70 characters: speak to the feeling ("God Has Not Forgotten You", "When You're Tired of Being
  Strong"). The description is 2 short, warm paragraphs, then the key Scriptures (references), then a
  one-line prayer. No hashtag spam.
- List the sources you relied on (the Bible references count as sources).
"""


WIKI_GUIDE = """
Part of the research notes is a Wikipedia article, for background only:
- Tell the Bible story itself; use the article for historical and cultural context, not as the storyline.
- Write every sentence in your own words. Never copy or lightly reword sentences from the article.
- Don't say "according to Wikipedia" in the narration.
- Only state historical facts the notes support; label scholarly estimates and traditions as such.

Visuals: the message ends with a numbered list of "Available images" from the article (often classical
paintings of the story). For each scene, set `image` to the number of the image that best shows what the
narration is talking about at that moment, or leave it null if none fits. Use each image at most once.
For scenes without an image, set `broll_query` to a concrete, cinematic stock-footage search for what is
being said. The title scene should show the story's key moment whenever an image of it exists.
"""


def write_script(
    cfg: Config,
    topic: str,
    notes: str,
    from_wikipedia: bool = False,
    images: str = "",
    feedback: str = "",
    prayer: bool = False,
) -> Script:
    ch = cfg.channel
    if cfg.format == "short":
        format_line = "YouTube Short, vertical 9:16, 45-55 seconds, 5-8 scenes"
        words = short_words(cfg)
    else:
        format_line = f"horizontal 16:9 video, about {cfg.target_minutes:g} minutes"
        words = cfg.target_words
    if prayer:
        structure = PRAYER_STRUCTURE
    else:
        structure = SHORT_STRUCTURE if cfg.format == "short" else LONG_STRUCTURE
    guide = (SCRIPT_GUIDE + (WIKI_GUIDE if from_wikipedia else "")).format(
        name=ch.name,
        niche=ch.niche,
        audience=ch.audience,
        tone=ch.tone,
        language=ch.language,
        format_line=format_line,
        words=words,
        structure=structure,
    )
    tail = f"\n\nAvailable images:\n{images}" if images else ""
    tail += f"\n\n{feedback}" if feedback else ""

    def user_message(notes: str) -> str:
        return f"Topic: {topic}\n\n<research_notes>\n{notes or '(no research notes; stick to well-established facts)'}\n</research_notes>{tail}"

    if cfg.llm.provider == "openai" and cfg.format == "long":
        return write_long_script(cfg, topic, notes, guide, images, from_wikipedia)
    if cfg.llm.provider == "openai":
        # Free tiers cap tokens per minute (Groq: 8000, counting max_tokens), so send a
        # slice of long notes and halve it if the request is still too large.
        limit = cfg.llm.max_note_chars
        for attempt in range(3):
            try:
                return _openai_structured(cfg, guide, user_message(notes[:limit]), Script, max_tokens=3000)
            except RequestTooLarge:
                if attempt == 2:
                    raise
                limit //= 2
                print(f"request too large; retrying with {limit} characters of notes")
    user = user_message(notes)
    with _client().beta.messages.stream(
        model=cfg.model,
        max_tokens=48000,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
        output_format=Script,
        system=guide,
        messages=[
            {
                "role": "user",
                "content": user,
            }
        ],
    ) as stream:
        response = stream.get_final_message()
    _check(response)
    script = response.parsed_output
    if script is None:
        raise ClaudeError("Claude did not return a parsable script.")
    return script


# Long videos on a free tier: one request can't hold a whole 8-10 minute script
# (Groq counts max_tokens against 8000 tokens a minute), so plan the video first,
# then write it one chapter at a time, each from its own slice of the notes.

WORDS_PER_CHAPTER = 220

LONG_WIKI_GUIDE = """
This is a long video, so it can tell the whole story. Build it as a narrative that follows the
emotional arc above, not a section-by-section summary of the article.
"""


class ChapterPlan(BaseModel):
    heading: str = Field(description="Chapter title for the description's chapter list, max ~6 words.")
    angle: str = Field(description="One sentence: what this chapter tells, and why the viewer keeps watching.")


class Outline(BaseModel):
    title: str = Field(description="YouTube title, max 70 characters, curiosity-driven but truthful.")
    description: str = Field(description="YouTube description: 2 short paragraphs, then key points. No hashtag spam.")
    tags: list[str] = Field(description="8-15 search tags.")
    thumbnail_text: str = Field(description="2-5 punchy words for the thumbnail (not the title).")
    thumbnail_kicker: str = Field(description="1-3 word label above the thumbnail text: the series or Bible figure.")
    thumbnail_query: str = Field(description="Stock photo search query for a cinematic thumbnail background.")
    chapters: list[ChapterPlan]
    sources: list[str] = Field(description="URLs or references backing the facts used.")


class ChapterScenes(BaseModel):
    scenes: list[ScriptScene]


def chapter_count(cfg: Config) -> int:
    # Long sleep and prayer videos (20-40 min) get more, longer chapters.
    per = WORDS_PER_CHAPTER if cfg.target_minutes <= 15 else WORDS_PER_CHAPTER * 2
    return max(3, min(8 if cfg.target_minutes <= 15 else 14, round(cfg.target_words / per)))


def split_notes(notes: str, parts: int, limit: int) -> list[str]:
    """Consecutive slices of the notes, one per chapter, cut at line breaks, each at most `limit` chars."""
    size = -(-len(notes) // parts) if notes else 0
    chunks, start = [], 0
    for i in range(parts):
        end = len(notes) if i == parts - 1 else notes.find("\n", start + size)
        end = len(notes) if end == -1 else end
        chunks.append(notes[start:end].strip()[:limit] or notes[:limit])
        start = end
    return chunks


def scripture_section(notes: str) -> tuple[str, str]:
    """Split the "## Scripture" section (see scripture.notes) from the rest of the notes."""
    start = notes.find("## Scripture")
    if start == -1:
        return "", notes
    end = notes.find("\n#", start + 1)
    end = len(notes) if end == -1 else end
    return notes[start:end].strip(), (notes[:start] + notes[end:]).strip()


def write_long_script(
    cfg: Config, topic: str, notes: str, guide: str, images: str = "", from_wikipedia: bool = False
) -> Script:
    guide += LONG_WIKI_GUIDE if from_wikipedia else ""
    limit = cfg.llm.max_note_chars
    n = chapter_count(cfg)
    # Every chapter may quote Scripture, so the verses go with each chapter's slice of the notes.
    verses, notes = scripture_section(notes)
    chunks = [verses + "\n\n" + c if verses else c for c in split_notes(notes, n, max(1000, limit - len(verses)))]
    overview = "\n...\n".join(c[: limit // n] for c in chunks)
    image_tail = f"\n\nAvailable images:\n{images}" if images else ""

    plan_note = (
        f"\n\nFirst, plan the video as exactly {n} chapters that together follow the journey above in order "
        "(each chapter carries one or two of its stages; name them in the chapter's angle). The notes "
        "below are excerpts in order; chapter k should draw mainly on part k. Return the metadata and the chapter "
        "plan only: the scenes are written chapter by chapter afterwards."
    )
    user = f"Topic: {topic}\n\n<research_notes>\n{overview or '(no research notes)'}\n</research_notes>"
    outline = _openai_structured(cfg, guide + plan_note, user, Outline, max_tokens=3000)
    plans = outline.chapters[: max(8, n)] or [ChapterPlan(heading=topic, angle="The story.")]
    if len(plans) != n:
        n = len(plans)
        chunks = split_notes(notes, n, limit)

    words = int(cfg.target_words / n)
    plan_text = "\n".join(f"{i}. {c.heading}: {c.angle}" for i, c in enumerate(plans, 1))
    scenes: list[ScriptScene] = []
    chapters: list[Chapter] = []
    used_images: set[int] = set()
    for i, plan in enumerate(plans, 1):
        if i == 1:
            position = "This chapter opens the video: start with a title scene, and make the first two sentences the hook."
        else:
            last = scenes[-1].narration if scenes else ""
            position = f"Continue straight on from the previous chapter, which ended: \"{last}\" Don't re-introduce the topic."
        if i == n:
            position += " This is the last chapter: end with a satisfying conclusion and one natural line inviting viewers to subscribe."
        else:
            position += " Don't wrap up or invite viewers to subscribe yet."
        taken = f"\nImages already used (don't reuse): {', '.join(map(str, sorted(used_images)))}" if used_images else ""
        system = guide + (
            f"\n\nYou are writing one chapter of this video at a time. Return only this chapter's scenes: "
            f"{words} words of narration in total (about {max(3, words // 30)} scenes of 25-35 words each). "
            "Don't write less: the video needs this length."
        )
        chunk = chunks[i - 1]
        for attempt in range(3):
            user = (
                f"Video title: {outline.title}\nChapter plan:\n{plan_text}\n\n"
                f"Write chapter {i}: {plan.heading}. {position}{taken}\n\n"
                f"<research_notes>\n{chunk or '(no research notes)'}\n</research_notes>{image_tail}"
            )
            try:
                part = _openai_structured(cfg, system, user, ChapterScenes, max_tokens=3000)
                break
            except RequestTooLarge:
                if attempt == 2:
                    raise
                chunk = chunk[: len(chunk) // 2]
                print(f"request too large; retrying chapter {i} with {len(chunk)} characters of notes")
        if not part.scenes:
            continue
        chapters.append(Chapter(title=plan.heading, scene=len(scenes)))
        for sc in part.scenes:
            if sc.image is not None:
                used_images.add(sc.image)
        scenes.extend(part.scenes)
        print(f"wrote chapter {i}/{n}: {plan.heading} ({sum(len(sc.narration.split()) for sc in part.scenes)} words)")

    return Script(
        title=outline.title,
        description=outline.description,
        tags=outline.tags,
        thumbnail_text=outline.thumbnail_text,
        thumbnail_kicker=outline.thumbnail_kicker,
        thumbnail_query=outline.thumbnail_query,
        scenes=scenes,
        sources=outline.sources,
        chapters=chapters,
    )
