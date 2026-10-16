"""Translated titles and descriptions, uploaded as YouTube localizations (config `localize.languages`).

A viewer whose YouTube is set to Spanish sees the Spanish title and description; the video, voice and
captions stay English. A full Spanish channel (Spanish narration and a Spanish public-domain Bible) is a
separate, later step.

Scripture is never re-worded by the translator: a Bible verse quoted in the English description is
replaced by its reference in the translation, references keep their chapter:verse numbers exactly, and a
translation that drops a reference, a chapter timestamp or a link is not used.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from fyt.config import Config
from fyt.models import Script

LANGUAGES = {"es": "Spanish (neutral Latin American, understood everywhere)"}
LABELS = {"en": ("Sources", "Series"), "es": ("Fuentes", "Serie")}
NUMBERED = re.compile(r"\b\d+:\d+(?:-\d+)?\b")  # Bible chapter:verse references and chapter timestamps
URL = re.compile(r"https?://\S+")


class Localized(BaseModel):
    title: str = Field(description="The title in the target language, max 90 characters.")
    description: str = Field(description="The description in the target language.")
    footer: str = Field(description="The channel footer in the target language.")


GUIDE = """You translate the title and description of a Christian YouTube video into {language}.
Write the way a warm, native speaker would say it, not word for word. Keep the meaning exactly: add
nothing, promise nothing the English doesn't, and keep the title honest and close to the English one.

Scripture:
- Bible book names in {language} (e.g. Mateo, Juan, Salmos, Isaías, 1 Corintios), with the chapter:verse
  numbers exactly as in the English.
- Never write your own translation of a quoted Bible verse. Where the English quotes a verse word for
  word, give only its reference instead (e.g. "(Mateo 11:28)").
- A line saying which English Bible translation the video quotes stays a line saying that, translated.
Keep every link, every chapter timestamp line ("0:00 ..."; translate only the chapter title) and every
#hashtag exactly as they are."""


def problems(english: str, translated: str) -> list[str]:
    """What a translation lost: links, references or timestamps (every n:n number must survive)."""
    out = [f"missing link {u}" for u in URL.findall(english) if u not in translated]
    out += [f"missing {n}" for n in dict.fromkeys(NUMBERED.findall(english)) if n not in translated]
    if "<" in translated or ">" in translated:
        out.append("contains '<' or '>'")
    return out


def translate(cfg: Config, script: Script, language: str) -> Localized | None:
    """The script's title, description and the channel footer in `language`, or None when the
    translation lost something (see `problems`)."""
    from fyt import llm

    name = LANGUAGES.get(language, language)
    user = (
        f"Title: {script.title}\n\nDescription:\n{script.description}\n\n"
        f"Footer:\n{cfg.channel.description_footer.strip() or '(empty)'}"
    )
    loc = llm.structured(cfg, GUIDE.format(language=name), user, Localized, max_tokens=4000)
    if cfg.channel.description_footer.strip() == "" or loc.footer.strip() == "(empty)":
        loc.footer = ""
    issues = problems(script.title + "\n" + script.description, loc.title + "\n" + loc.description)
    if not loc.title.strip() or len(loc.title) > 100:
        issues.append("title missing or over 100 characters")
    if issues:
        print(f"warning: {language} translation not used: {'; '.join(issues)[:300]}")
        return None
    return loc


def localize(cfg: Config, script: Script) -> dict[str, dict]:
    """{language: {title, description, footer}} for every configured language that translated cleanly."""
    out = {}
    for lang in cfg.localize.languages:
        if lang == cfg.channel.language:
            continue
        try:
            loc = translate(cfg, script, lang)
        except Exception as e:  # a missing translation never stops a video
            print(f"warning: no {lang} title and description: {e}")
            continue
        if loc:
            out[lang] = loc.model_dump()
    return out
