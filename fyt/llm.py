"""Claude calls: topic ideation, web research, and structured script writing."""

from __future__ import annotations

import json
import os
import re
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


class NewIdea(BaseModel):
    id: str = Field(description="lowercase-words-with-dashes, unique")
    title: str = Field(description="Cinematic or curious working title, max 70 characters.")
    category: str
    emotion: str
    character: str = Field(default="", description="The Bible person at the centre, if any.")
    arc: str = Field(description="journey | story | curiosity | wisdom | prayer | peace | joy")
    scriptures: list[str] = Field(description="1-3 exact references, 'Book chapter:verse' or 'Book chapter:verse-verse'.")
    angle: str = Field(description="One or two sentences: the hook and what the viewer leaves with.")
    formats: list[str] = Field(description="Any of short, medium, long.")


class NewIdeas(BaseModel):
    ideas: list[NewIdea]


PILLAR_NOTES = {
    "everyday_life": "a recognisable MODERN situation (career, money, social media, aging, leadership, loneliness, "
    "success, family, responsibility) met by Scripture. Usually no Bible character, never an invented one.",
    "history": "a real historical, cultural or archaeological detail of the Bible's world that changes how a "
    "passage feels. Only well-established facts.",
    "wisdom": "practical life wisdom, mostly from Proverbs, Ecclesiastes or Jesus' teaching, for a real situation.",
    "bible_story": "one Bible story told from inside it, often about a lesser-known person named in Scripture.",
    "jesus": "one moment, teaching, miracle or parable of Jesus from the Gospels.",
    "prayer": "a prayer for one specific situation, prayed together with the viewer.",
    "peace": "a slow, still moment of rest in God's presence.",
}


def ideate_catalog(
    cfg: Config, category: str, n: int, avoid: list[str], recent_people: list[str], examples: str = ""
) -> list[NewIdea]:
    """New ideas for one pillar of the content universe, in the catalog's own shape."""
    ch = cfg.channel
    prompt = f"""You plan videos for "{ch.name}", a faceless Christian YouTube channel.
Channel promise: {ch.niche}
Creative principle: don't just tell people about faith, make them feel faith.

Propose {n} new video ideas for the pillar "{category}". Pillars of the channel: jesus, bible_story, motivation,
prayer, peace, relationships, purpose, spiritual_battles, wisdom, history (Bible & history curiosities),
everyday_life (career, money, social media, aging, leadership, loneliness, success, family...).

Each idea:
- one specific story, question, situation or prayer; evergreen; faithful to Scripture; mainstream Christian
- vary the emotion (courage, love, grief, peace, joy, curiosity, fear, strength, wisdom, hope, gratitude,
  temptation, forgiveness, purpose) and the story shape (journey, story, curiosity, wisdom, prayer, peace, joy)
- favour lesser-known Bible people as much as famous ones; avoid these recently used: {", ".join(recent_people) or "none"}
- a title that would make anyone curious, not only church-goers; no news, politics or controversy
- 1-3 Scripture references that really contain what the idea rests on (they are checked against the Bible text)
- only people who are actually named in the Bible; never invent a character, a trade or an event
- Bible first: start from one passage and what it actually means in its context; never bend a passage to
  fit a feeling, and never stack different teachings into one idea
- titles in varied styles (cinematic, a question, a character's name, the verse's own words, a prayer...);
  never the formula 'When [feeling], Remember [person or thing]'
- no prosperity promises ("God will make you rich"), no medical claims
- this pillar is: {PILLAR_NOTES.get(category, category)}

Ideas of this pillar the channel already has, as examples of the quality and shape wanted:
{examples or "(none)"}

Already covered (don't repeat or closely paraphrase):
{chr(10).join(f"- {t}" for t in avoid[-150:]) or "- (none)"}"""
    out = structured(cfg, "You plan YouTube videos.", prompt, NewIdeas, max_tokens=3000)
    return out.ideas[:n]


def ideate_topics(cfg: Config, n: int, avoid: list[str], performance_notes: str = "") -> list[str]:
    """Propose fresh video topics for the channel, skipping ones already covered."""
    ch = cfg.channel
    prompt = f"""You plan videos for a faceless Christian YouTube channel.

Channel promise: {ch.niche}
Audience: {ch.audience}
Format: {"YouTube Shorts (under 60 seconds)" if cfg.format == "short" else f"~{cfg.target_minutes:g} minute videos"}
Series: {", ".join(cfg.growth.series) or "(none)"}

Propose {n} specific video topics. Each must:
- come from the channel's whole universe, varied: Jesus (life, teachings, miracles), Bible stories (with
  lesser-known people as much as famous ones: Deborah, Bartimaeus, Stephen, Barnabas, Lydia, Naomi...),
  motivation, prayer, peace, relationships, purpose, spiritual battles, Biblical wisdom, Bible & history
  curiosities, and faith in everyday life (career, money, social media, aging, leadership, loneliness)
- span the emotions: courage, love, grief, peace, joy, curiosity, wisdom, gratitude, hope, forgiveness
- often be phrased as a cinematic or curious title that doesn't sound like religious programming
  ("He Was Forgotten for Years", "Why Did Jesus Write in the Sand?")
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

# The other story shapes (an idea's `arc`). Every video makes the viewer feel something, but by
# different roads, so the channel never settles into "you are struggling -> here is a verse".
# The `mood` tags still drive pace, music and colour: they describe the energy of each moment.
# Story-first: every story is told like a film, around ONE dramatic question, in six beats.
STORY_STRUCTURE = """The shape: a Bible story told like a film. The whole video turns on ONE dramatic question (the
notes give it; otherwise take it from the Bible study), e.g. "Will Daniel stop praying to save his life?".
Six beats, in this order (set each scene's `mood` as noted):
1. Hook (uncertainty or struggle), the first 5-15 seconds: open on the conflict, the danger, the dilemma or a
   surprising question, in the middle of the moment. No general introduction, no greeting, no "today we".
   By the end of the hook the viewer knows the dramatic question.
2. Setup (uncertainty): the people, the place and what is at stake, as the passage gives them.
3. Escalation (struggle): the tension builds through what actually happens in the passage, event by event,
   in Scripture's order. Don't resolve it early.
4. Turning point (realization): the moment everything turns, carried by the key Scripture, quoted exactly.
   Give it room (pause_after 2-3 seconds).
5. Resolution (hope): what happened, as the passage tells it, and what it reveals: the answer to the
   dramatic question.
6. Reflection (faith -> strength): the passage's teaching, faithfully, and what it asks of the viewer. No
   motivational message the passage doesn't give, and nothing unrelated to it."""

CURIOSITY_STRUCTURE = """The shape: a question that pulls the viewer in, answered in a way that moves them.
1. The question (uncertainty): open on the intriguing detail or question ("Nobody knows what Jesus wrote in
   the sand."). Make them want the answer.
2. The world behind it (faith): the place, custom, history that makes sense of it, told through what people
   saw and felt, never as a lecture. Label scholarly views and traditions as such.
3. The surprising answer (realization): what it reveals, with the Scripture.
4. Why it matters now (hope -> strength): what it means for how we live or see God. End in wonder, not a quiz."""

WISDOM_STRUCTURE = """The shape: a real-life situation, met by ancient wisdom.
1. The situation (struggle or uncertainty): a recognisable moment from work, money, friendship, family,
   ambition, phones, aging... specific and modern, no Bible yet.
2. The wisdom (faith -> realization): what Scripture (often Proverbs, Ecclesiastes, Jesus' teaching) says,
   and a short story or example that shows it.
3. The practice (hope): two or three concrete things to do this week.
4. The blessing (strength): a closing line or short blessing."""

PEACE_STRUCTURE = """The shape: stillness. A slow, unhurried experience of God's presence.
Short lines, long pauses (pause_after 2-3 seconds), gentle images. Moods: uncertainty (naming the noise)
-> faith (settling, breathing) -> realization (the promise, spoken slowly) -> hope -> strength (rest).
No urgency, no calls to action until a soft last line."""

JOY_STRUCTURE = """The shape: gratitude and joy. Not every video is about pain.
1. Remember (faith): a specific gift or faithfulness of God, in the Bible and in ordinary life.
2. Notice (realization): the Scripture that names it.
3. Celebrate (hope -> strength): invite the viewer to thank God for one specific thing today.
The energy is warm and bright, building to the end."""

SHORT_SHAPES = {
    "story": "Shorts version, the same six beats compressed: the hook is the first line (the conflict or the "
    "dramatic question), the setup in one sentence (uncertainty), one escalating beat (struggle), the turning "
    "point with the verse (realization), and the resolution and what it reveals in a line or two (hope/strength).",
    "curiosity": "Shorts version: the question in the first line (uncertainty), one vivid detail (faith), the "
    "surprising answer with the verse (realization), why it matters (strength).",
    "wisdom": "Shorts version: the modern moment (struggle), the ancient line (realization), one thing to do "
    "today (strength).",
    "peace": "Shorts version: one slow breath of a video: a few quiet lines and the promise, with long pauses.",
    "joy": "Shorts version: one thing to remember, the verse, one thing to thank God for today.",
}


def structure_for(shape: str, short: bool, prayer: bool = False) -> str:
    """The script shape for an idea's arc (see catalog.ARCS)."""
    if prayer or shape == "prayer":
        return PRAYER_STRUCTURE
    if shape == "journey" or shape not in SHORT_SHAPES:
        return SHORT_STRUCTURE if short else LONG_STRUCTURE
    full = {"story": STORY_STRUCTURE, "curiosity": CURIOSITY_STRUCTURE, "wisdom": WISDOM_STRUCTURE,
            "peace": PEACE_STRUCTURE, "joy": JOY_STRUCTURE}[shape]
    return full + ("\n" + SHORT_SHAPES[shape] if short else "")



# --- Bible first, emotion second ---------------------------------------------------------------
# Editorial rule for The Way of Christ: never bend Scripture to fit the idea. Every script starts
# from a study of its passage (study_passage), is written on that passage's central truth, and is
# checked afterwards (check_faithfulness) for bent meanings, merged passages and overpromises.

BIBLE_FIRST = """BIBLE FIRST, EMOTION SECOND. The research notes open with a Bible study of the passage this
video rests on: its text, context, original meaning and one-sentence central truth. Build the whole video
on that central truth.
- The passage leads; the modern feeling is only the doorway. Never bend Scripture to fit the idea: if the
  passage doesn't say it, the video doesn't say it.
- One passage, one teaching. Never merge different passages or teachings into one point (the mustard-seed
  faith of Matthew 17:20 and the mustard-seed parable of the kingdom in Matthew 13:31-32 are different
  teachings).
- Show what is actually happening in the passage (who, where, what is said and why) before applying it.
- Offer application as application ("perhaps that's what you need to hear"), never as the passage's meaning.
- Don't overpromise. Never say God will fix everything, a verse guarantees a breakthrough, or enough faith
  gets you what you want. Say what Scripture does say: you can bring your fear to God; God's presence
  doesn't depend on your circumstances; faith doesn't mean knowing how the story ends.
- If the idea names a person (a saint, a Bible character), the video is about that person.
- Imagined is fine only when it is marked. Light, weather, sounds and setting may be imagined as scene-setting.
  Dialogue, thoughts, names, numbers or events the passage doesn't give must be marked as imagined in the
  narration ("perhaps", "we can imagine", "the text doesn't say, but..."), never presented as Scripture.
- Not every video is motivational. Let it be beautiful, thought-provoking, educational, mysterious,
  challenging, peaceful or joyful as the passage calls for, always pointing to Christ."""

# Ten title styles in rotation: a title LANGUAGE, not a title template.
TITLE_STYLES = {
    "cinematic": ("a moment from the story, like a film title",
                  ["The Night Peter Realized What He Had Done", "The Prison Was Not Joseph's Ending", "The Morning the Stone Was Gone"]),
    "direct": ("a short command or truth from the passage, 1-4 words",
               ["Do Not Be Afraid", "Stand Firm", "Be Still", "Forgive"]),
    "curiosity": ("a 'why' or 'what happened' question about the story",
                  ["Why Did Jesus Sleep During the Storm?", "What Happened After Lazarus Walked Out?"]),
    "question": ("what a saying or teaching of Scripture means",
                 ["What Does Jesus Mean by 'Take Up Your Cross'?", "Why Does Jesus Say the First Will Be Last?"]),
    "character": ("the person's name, then who they were or became",
                  ["Moses: The Man Who Didn't Think He Was Ready", "Esther: Courage When Silence Wasn't an Option"]),
    "verse": ("the verse's own words in quotes, then what they mean",
              ["'My Grace Is Sufficient for You': What Paul Learned About Weakness", "'Be Still and Know': What Psalm 46 Actually Means"]),
    "wisdom": ("what Scripture says or teaches about a life topic",
               ["What Proverbs Actually Says About Money", "What Jesus Taught About Ambition"]),
    "prayer": ("an invitation to pray",
               ["A Prayer for the Road Ahead", "Pray This Before You Sleep"]),
    "history": ("the world behind the Bible",
                ["What Was Jerusalem Like in the Time of Jesus?", "What Did Crucifixion Mean in the Roman World?"]),
    "seasonal": ("the moment in the Christian year",
                 ["The Night Before the Cross", "The Long Wait for the Messiah"]),
}
STYLES_FOR_SHAPE = {
    "story": ["cinematic", "character", "curiosity"],
    "curiosity": ["curiosity", "question", "history"],
    "wisdom": ["wisdom", "question", "verse"],
    "prayer": ["prayer"],
    "peace": ["direct", "verse", "prayer"],
    "joy": ["verse", "direct", "cinematic"],
    "journey": ["verse", "direct", "character", "question", "cinematic"],
}
BANNED_TITLE = re.compile(r"^\s*when\b[^,:]*[,:]|[,:]\s*remember\b", re.I)


def title_banned(title: str) -> bool:
    """The worn formula "When [feeling], Remember [character]" (or any "When X, Y" title)."""
    return bool(BANNED_TITLE.search(title or ""))


def choose_title_style(
    shape: str, category: str = "", recent: list[str] | None = None, seasonal: bool = False,
    prefer: list[str] | None = None, avoid: list[str] | None = None,
) -> str:
    """The title style for the next video: one that suits its shape, not used in the last few videos.
    Styles that held viewers (`prefer`, from fyt/insights.py) are tried first and ones that lost them
    (`avoid`) last; every style that suits the shape stays available."""
    allowed = list(STYLES_FOR_SHAPE.get(shape, STYLES_FOR_SHAPE["journey"]))
    if category == "history":
        allowed = ["history", "curiosity"]
    if seasonal:
        allowed = ["seasonal", *allowed]
    prefer, avoid = prefer or [], avoid or []
    rank = lambda s: (prefer.index(s) if s in prefer else len(prefer)) + (100 if s in avoid else 0)  # noqa: E731
    allowed = sorted(allowed, key=lambda s: (rank(s), allowed.index(s)))
    recent = (recent or [])[-4:]
    fresh = [s for s in allowed if s not in recent]
    if fresh:
        return fresh[0]
    return min(allowed, key=lambda s: len(recent) - 1 - recent[::-1].index(s) if s in recent else -1)


def title_rule(style: str) -> str:
    what, examples = TITLE_STYLES.get(style, TITLE_STYLES["cinematic"])
    return (
        f"Title style for this video: {style.upper()}, {what}. Examples of the style (don't copy them): "
        + "; ".join(f'"{e}"' for e in examples)
        + ". Name the actual story, person, passage or question, and keep every word true to the passage: no "
        "event that didn't happen, no promise it doesn't make. Never use the formula 'When [feeling], "
        "Remember [person or thing]' or any title shaped 'When X, Y'."
    )


class Study(BaseModel):
    passage: str = Field(description="The one passage the video rests on, e.g. 'Exodus 3:10-12'.")
    context: str = Field(description="What is happening immediately before and after (2-3 sentences).")
    meaning: str = Field(description="What the passage actually says in its context (2-4 sentences).")
    truth: str = Field(description="The central truth in one sentence, faithful to the text.")
    not_saying: list[str] = Field(description="2-4 misreadings, merges or overpromises this video must avoid.")
    connection: str = Field(description="A modern human experience that connects naturally with the truth.")
    dramatic_question: str = Field(
        default="", description="The one dramatic question a film of this passage turns on, answered by the passage itself."
    )


def _careful(cfg: Config) -> Config:
    """The same model thinking harder: for the study and the faithfulness review."""
    return cfg.model_copy(update={"llm": cfg.llm.model_copy(update={"reasoning_effort": "medium"})})


def study_passage(cfg: Config, title: str, angle: str, notes: str, about: str = "") -> Study:
    """Step 1-5 of the editorial process: passage, context, original meaning, central truth, connection."""
    system = (
        "You are a careful Bible teacher preparing a short video. Study the passage the idea rests on, "
        "faithfully and in its context, within mainstream Christian teaching. Base everything on the exact "
        "Bible text and chapter given in the notes, and on the editor's central truth when the notes give one. "
        "If the idea's angle stretches the passage, say so in not_saying. Keep different passages' teachings "
        "apart. Never let the central truth promise outcomes Scripture doesn't promise."
    )
    if about:
        system += (
            f" The video is about {about}. If {about} is not in the passage (a saint or later Christian), "
            f"the study covers {about}'s life from the notes and how this passage shaped it; the truth stays "
            "faithful to the passage."
        )
    user = f"Idea: {title}\nAngle: {angle}\n\n<notes>\n{notes[: cfg.llm.max_note_chars]}\n</notes>"
    return structured(_careful(cfg), system, user, Study, max_tokens=2500)


def study_markdown(study: Study) -> str:
    return (
        f"## Bible study (the video is built on this)\n"
        f"Passage: {study.passage}\nContext: {study.context}\nWhat it says: {study.meaning}\n"
        f"Central truth: {study.truth}\nThe video must NOT: " + "; ".join(study.not_saying) + "\n"
        f"Modern connection: {study.connection}"
        + (f"\nDramatic question: {study.dramatic_question}" if study.dramatic_question else "")
    )


class Faithfulness(BaseModel):
    faithful: bool = Field(description="True only if the script is faithful to the passage and the study.")
    problems: list[str] = Field(default_factory=list, description="Each place it bends, merges, invents or overpromises.")
    unmarked_inventions: list[str] = Field(
        default_factory=list,
        description="Each piece of dialogue, thought, name, number or event that is not in the passage and is told "
        "as if it were, without being marked as imagined.",
    )


def faithfulness_problems(verdict: Faithfulness) -> list[str]:
    """Everything the review found; empty means the script may go ahead. Unmarked invented detail
    always counts, even when the reviewer calls the script faithful otherwise."""
    problems = [] if verdict.faithful else list(verdict.problems)
    if not verdict.faithful and not problems and not verdict.unmarked_inventions:
        return []  # marked unfaithful without saying why: nothing to fix (as before)
    problems += [f"invented detail told as Scripture (mark it as imagined or cut it): {x}" for x in verdict.unmarked_inventions]
    return problems


def check_faithfulness(cfg: Config, script: Script, study: str, verses: str, about: str = "") -> Faithfulness:
    """Steps 6-8 checked: does the script stay true to the passage, keep teachings apart, label
    application as application and avoid overpromising?"""
    system = (
        "You review scripts for a Christian channel whose rule is: never bend Scripture to fit the idea. "
        "Compare the script with the Bible study and the exact verses. Mark it unfaithful if it changes what a "
        "passage means, merges different passages or teachings into one point, invents events, presents "
        "application as the passage's meaning, promises outcomes Scripture doesn't promise (fixes, breakthroughs, "
        "rewards for enough faith), or drifts away from the person the video is about. Check every point in "
        "the study's 'must NOT' list. Imagined sensory scene-setting (light, sounds, feelings) is fine. Dialogue, "
        "thoughts, names, numbers or events that are not in the passage are fine only when the narration marks "
        "them as imagined ('perhaps', 'we can imagine'); list every one that isn't marked in unmarked_inventions. "
        "Be specific and brief."
    )
    if about:
        system += f" This video must be about {about}; it is unfaithful if {about} is missing or incidental."
    narration = "\n".join(f"- {s.narration}" + (f" [on screen: {s.text} ({s.author})]" if s.type == "quote" else "") for s in script.scenes)
    user = f"Title: {script.title}\n\n{study}\n\n{verses[:3000]}\n\nScript:\n{narration[:5000]}"
    return structured(_careful(cfg), system, user, Faithfulness, max_tokens=2500)


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
"there is still hope", or simply moved, curious, grateful or at peace. The channel has emotional range:
courage, love, grief, peace, joy, curiosity, wisdom, gratitude, hope. Follow the story shape below, never
fact -> explanation -> conclusion.

{bible_first}

{structure}

How it sounds (a warm, deep, deliberate narrator reads every word):
- Speak to one person, "you", like someone who has been there, not a teacher and not a preacher.
- Short, spoken sentences. Vary the rhythm: a long line, then a short one. Then shorter.
- Leave space. End a line with "..." where the voice should trail off and breathe. Use repetition that
  builds, written fresh for this video (never reuse a stock phrase from these instructions).
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
- mood: the energy of the moment (struggle, uncertainty, faith, realization, hope or strength), as the
  shape above sets out; it drives the voice's pace, the music and the colour of the picture.
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
- In a Short, the first scene is a broll scene whose heading is the hook on screen: 2-6 words, a question
  or the tension (e.g. "Forgotten for two years?"). It shows big from the very first frame.
- Scripture: quote only the exact verse text given in the notes, and name the reference. If a verse isn't
  in the notes, paraphrase it clearly as a paraphrase and give the reference. Never invent or merge
  verses, and never put words in Jesus' mouth.
- Stay faithful to the Bible story and anchored to the cited passages: feelings, sounds and light may be
  imagined as scene-setting, never new events; reconstructed detail and imagined dialogue are marked as such
  in the narration. Mainstream Christian teaching; no politics, prosperity promises, guilt, fear tactics or
  medical advice.
- End on strength: the line they carry, then (only in long videos) one gentle invitation to subscribe
  or pray along.
- Title max 70 characters. {title_rule} Never "Biblical Motivation for..." or "Bible Verse About...".
- The description is 2 short, warm paragraphs that say plainly what the passage is about, then the key
  Scriptures (references), then a one-line prayer. No hashtag spam, no promises the passage doesn't make.
- List the sources you relied on (the Bible references count as sources).
"""


SLEEP_NOTE = """, made to fall asleep to ("Fall asleep in God's Word").
This is a sleep video: the listener is lying in the dark with their eyes closed. Read Scripture slowly and
let it rest on them: the passages themselves, quoted exactly from the notes, with a few gentle words between
them and a quiet prayer. No tension, no cliffhangers, no questions that wake them up, no call to subscribe;
moods stay with faith, peace and hope. Long pauses after every verse (pause_after 2-4). Scenes are calm,
dim, slow pictures: night sky, candlelight, still water, moonlit fields, soft rain on a window. End in a
whispered blessing"""


WIKI_GUIDE = """
Part of the research notes is a Wikipedia article, for background only:
- Tell the Bible story itself; use the article for historical and cultural context, not as the storyline.
- Write every sentence in your own words. Never copy or lightly reword sentences from the article.
- Don't say "according to Wikipedia" in the narration.
- Only state historical facts the notes support; label scholarly estimates and traditions as such.
"""

IMAGES_GUIDE = """
Visuals: the message ends with a numbered list of "Available images" (classical paintings of the story
and its people, from Wikipedia and Wikimedia Commons). For each scene, set `image` to the number of the
image that best shows what the narration is talking about at that moment, or leave it null if none fits.
Use each image at most once, and only where it truly shows that moment or person. Mix paintings with
footage: give about a third to a half of the scenes an image and the rest moving footage, alternating
where you can. For scenes without an image, set `broll_query` to a concrete, cinematic stock-footage
search for what is being said. The title scene (in a Short, the first scene) should show the story's key moment
whenever an image of it exists.
"""


def write_script(
    cfg: Config,
    topic: str,
    notes: str,
    from_wikipedia: bool = False,
    images: str = "",
    feedback: str = "",
    prayer: bool = False,
    shape: str = "journey",
    title_style: str = "cinematic",
    lessons: str = "",
    visual: str = "",
) -> Script:
    """`lessons`: what the channel's analytics say about delivery (fyt/insights.py), added to the guide.
    `visual`: the long video's visual style (fyt/slate.py style_note)."""
    ch = cfg.channel
    if cfg.format == "short":
        format_line = "YouTube Short, vertical 9:16, 45-55 seconds, 5-8 scenes"
        words = short_words(cfg)
    else:
        format_line = f"horizontal 16:9 video, about {cfg.target_minutes:g} minutes"
        words = cfg.target_words
    if cfg.is_sleep:
        format_line += SLEEP_NOTE
    structure = structure_for(shape, cfg.format == "short", prayer)
    guide = (SCRIPT_GUIDE + (WIKI_GUIDE if from_wikipedia else "") + (IMAGES_GUIDE if images else "")).format(
        name=ch.name,
        niche=ch.niche,
        audience=ch.audience,
        tone=ch.tone,
        language=ch.language,
        format_line=format_line,
        words=words,
        structure=structure,
        bible_first=BIBLE_FIRST,
        title_rule=title_rule(title_style),
    )
    if visual:
        guide += f"\n{visual}\n"
    if lessons:
        guide += f"\nWhat this channel's viewers have shown so far (from its analytics):\n{lessons}\n"

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
        if i == n and cfg.is_sleep:
            position += " This is the last chapter: let it grow quieter and end in a whispered blessing."
        elif i == n:
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
        # Free models tend to write short. A chapter well under its length gets one more try,
        # and the longer of the two drafts is kept, so long videos reach their target length.
        got = sum(len(sc.narration.split()) for sc in part.scenes)
        if got < 0.7 * words:
            note = (
                f"\n\nYour previous draft of this chapter had only {got} words of narration. It needs about "
                f"{words} words: write more scenes (about {max(3, words // 30)} in total), going deeper into the "
                "story and the feeling. Don't pad with repetition."
            )
            try:
                longer = _openai_structured(cfg, system, user + note, ChapterScenes, max_tokens=3000)
                if sum(len(sc.narration.split()) for sc in longer.scenes) > got:
                    part = longer
            except ClaudeError as e:
                print(f"chapter {i} stays short ({got} words): {str(e)[:200]}")
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
