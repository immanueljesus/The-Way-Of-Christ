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

# YouTube language codes (i18nLanguages): "pt" is Portuguese as YouTube shows it to Brazil ("pt-PT" is Portugal's).
LANGUAGES = {
    "es": "Spanish (neutral Latin American, understood everywhere)",
    "pt": "Brazilian Portuguese",
    "fr": "French (neutral, understood in Africa as well as France)",
    "fil": "Filipino (Tagalog, the way Filipinos write online; keep common English church words where Filipinos use them)",
    "ko": "Korean (natural, warm; the book names Korean Protestant Bibles use)",
}
LABELS = {
    "en": ("Sources", "Series"), "es": ("Fuentes", "Serie"), "pt": ("Fontes", "Série"),
    "fr": ("Sources", "Série"), "fil": ("Mga Pinagmulan", "Serye"), "ko": ("출처", "시리즈"),
}
NUMBERED = re.compile(r"\b\d+:\d+(?:-\d+)?\b")  # Bible chapter:verse references and chapter timestamps
URL = re.compile(r"https?://\S+")


class Localized(BaseModel):
    title: str = Field(description="The title in the target language, max 90 characters.")
    description: str = Field(description="The description in the target language.")
    footer: str = Field(description="The channel footer in the target language.")


class Translation(Localized):
    language: str = Field(description="The language code exactly as listed, e.g. 'pt'.")


class Translations(BaseModel):
    translations: list[Translation] = Field(description="One entry per requested language.")


GUIDE = """You translate the title and description of a Christian YouTube video into {language}.
Write the way a warm, native speaker would say it, not word for word. Keep the meaning exactly: add
nothing, promise nothing the English doesn't, and keep the title honest and close to the English one.

Scripture:
- Bible book names as that language's Bibles write them (e.g. Spanish Mateo, Isaías; French Genèse,
  Ésaïe; Korean 창세기), with the chapter:verse numbers exactly as in the English.
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


def untranslated(english: str, translated: str) -> bool:
    """Most of the words are the English ones (names, numbers and links aside)."""
    words = lambda t: [w for w in re.findall(r"[^\W\d_]{3,}", URL.sub("", t).lower())]  # noqa: E731
    src, out = set(words(english)), words(translated)
    return bool(out) and sum(w in src for w in out) / len(out) > 0.6


def _source(cfg: Config, script: Script) -> str:
    return (
        f"Title: {script.title}\n\nDescription:\n{script.description}\n\n"
        f"Footer:\n{cfg.channel.description_footer.strip() or '(empty)'}"
    )


def _model(cfg: Config) -> Config:
    """Translations can run on another model (localize.model) with its own free daily allowance."""
    if not cfg.localize.model:
        return cfg
    return cfg.model_copy(update={"llm": cfg.llm.model_copy(update={"model": cfg.localize.model})})


def _checked(cfg: Config, script: Script, language: str, loc: Localized) -> Localized | None:
    if cfg.channel.description_footer.strip() == "" or loc.footer.strip() == "(empty)":
        loc.footer = ""
    issues = problems(script.title + "\n" + script.description, loc.title + "\n" + loc.description)
    if not loc.title.strip() or len(loc.title) > 100:
        issues.append("title missing or over 100 characters")
    if untranslated(script.title + " " + script.description, loc.title + " " + loc.description):
        issues.append("came back in English")
    if issues:
        print(f"warning: {language} translation not used: {'; '.join(issues)[:300]}")
        return None
    return Localized(title=loc.title, description=loc.description, footer=loc.footer)


def translate(cfg: Config, script: Script, language: str) -> Localized | None:
    """The script's title, description and the channel footer in one language, or None when the
    translation lost something (see `problems`)."""
    from fyt import llm

    name = LANGUAGES.get(language, language)
    loc = llm.structured(_model(cfg), GUIDE.format(language=name), _source(cfg, script), Localized, max_tokens=4000)
    return _checked(cfg, script, language, loc)


def localize(cfg: Config, script: Script) -> dict[str, dict]:
    """{language: {title, description, footer}} for every configured language that translated cleanly.
    All languages come from one request (the English is sent once); any that come back missing or
    rejected get one request of their own."""
    from fyt import llm

    langs = [lang for lang in cfg.localize.languages if lang != cfg.channel.language]
    out: dict[str, dict] = {}
    if len(langs) > 1:
        names = "; ".join(f"{lang} = {LANGUAGES.get(lang, lang)}" for lang in langs)
        try:
            many = llm.structured(
                _model(cfg), GUIDE.format(language="each of these languages") + f"\nLanguages (code = language): {names}",
                _source(cfg, script), Translations, max_tokens=3000 + 1500 * len(langs),
            )
            for t in many.translations:
                if t.language in langs and t.language not in out:
                    loc = _checked(cfg, script, t.language, t)
                    if loc:
                        out[t.language] = loc.model_dump()
        except Exception as e:
            print(f"warning: translations in one request failed ({str(e)[:150]}); one language at a time")
    for lang in langs:
        if lang in out:
            continue
        try:
            loc = translate(cfg, script, lang)
        except Exception as e:  # a missing translation never stops a video
            print(f"warning: no {lang} title and description: {e}")
            continue
        if loc:
            out[lang] = loc.model_dump()
    return {lang: out[lang] for lang in langs if lang in out}
