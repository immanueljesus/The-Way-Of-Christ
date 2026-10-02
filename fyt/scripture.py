"""Scripture research: the exact Bible text behind every reference a video uses.

The scriptwriter gets the verses word for word, and after the script is written every
quote scene that cites a Bible reference is checked against the real text, so the
channel never puts words in the Bible's mouth. Text comes from bible-api.com, which
serves public-domain translations (World English Bible, King James Version).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from urllib.parse import quote

import requests

from fyt.config import Config
from fyt.models import Script

BOOKS = """Genesis Exodus Leviticus Numbers Deuteronomy Joshua Judges Ruth|1 Samuel|2 Samuel|1 Kings|2 Kings
|1 Chronicles|2 Chronicles|Ezra|Nehemiah|Esther|Job|Psalms|Psalm|Proverbs|Ecclesiastes|Song of Solomon|Song of Songs
|Isaiah|Jeremiah|Lamentations|Ezekiel|Daniel|Hosea|Joel|Amos|Obadiah|Jonah|Micah|Nahum|Habakkuk|Zephaniah|Haggai
|Zechariah|Malachi|Matthew|Mark|Luke|John|Acts|Romans|1 Corinthians|2 Corinthians|Galatians|Ephesians|Philippians
|Colossians|1 Thessalonians|2 Thessalonians|1 Timothy|2 Timothy|Titus|Philemon|Hebrews|James|1 Peter|2 Peter
|1 John|2 John|3 John|Jude|Revelation""".replace("\n", "").replace(" ", "|", 7).split("|")

# "John 3:16", "1 Peter 5:7", "Psalm 23:1-4", "Song of Solomon 2:4", "Genesis 50:19–21"
REFERENCE = re.compile(
    r"(?<![A-Za-z0-9])("
    + "|".join(re.escape(b) for b in sorted(BOOKS, key=len, reverse=True))
    + r")\s(\d{1,3}):(\d{1,3})(?:\s?[-–]\s?(\d{1,3}))?\b"
)


@dataclass
class Passage:
    reference: str
    text: str
    translation: str


def find_references(text: str) -> list[str]:
    """Bible references mentioned in a piece of text, in order, without repeats."""
    out: list[str] = []
    for m in REFERENCE.finditer(text or ""):
        ref = f"{m[1]} {m[2]}:{m[3]}" + (f"-{m[4]}" if m[4] else "")
        if ref not in out:
            out.append(ref)
    return out


def is_reference(text: str | None) -> bool:
    return bool(text and REFERENCE.search(text))


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # A passage can start or end mid-speech; drop the dangling quote mark so it reads cleanly on screen.
    if text.count("“") > text.count("”") and text.startswith("“"):
        text = text[1:]
    if text.count("”") > text.count("“") and text.endswith("”"):
        text = text[:-1]
    return text.strip()


def fetch(cfg: Config, reference: str) -> Passage:
    """The passage in the configured translation. Retries briefly on rate limits (15 requests / 30s)."""
    url = f"{cfg.scripture.api.rstrip('/')}/{quote(reference)}"
    for attempt in range(3):
        r = requests.get(url, params={"translation": cfg.scripture.translation}, timeout=30)
        if r.status_code == 429 and attempt < 2:
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code == 404:
            raise LookupError(f"no such passage: {reference}")
        r.raise_for_status()
        body = r.json()
        return Passage(
            reference=body.get("reference") or reference,
            text=_clean(body.get("text", "")),
            translation=body.get("translation_name") or cfg.scripture.translation_name,
        )
    raise LookupError(f"could not fetch {reference}")


def fetch_all(cfg: Config, references: list[str]) -> dict[str, Passage]:
    """Every reference that could be fetched; failures are skipped (the video can still be made)."""
    if not cfg.scripture.enabled:
        return {}
    out: dict[str, Passage] = {}
    for ref in references:
        try:
            out[ref] = fetch(cfg, ref)
        except Exception as e:
            print(f"warning: could not fetch {ref}: {e}")
    return out


def notes(passages: dict[str, Passage]) -> str:
    """The verses as research notes for the scriptwriter."""
    if not passages:
        return ""
    lines = ["## Scripture (exact text; quote only these words)"]
    for ref, p in passages.items():
        lines.append(f"- {ref} ({p.translation}): \"{p.text}\"")
    return "\n".join(lines)


def _words(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", text.lower().replace("’", "'")))


def check_quotes(cfg: Config, script: Script, passages: dict[str, Passage]) -> tuple[Script, list[str]]:
    """Make every Scripture quote on screen match the Bible text.

    A quote scene citing a reference must show words that appear in that passage. A quote that
    doesn't match is replaced by the real verse when it is short enough to show, otherwise the
    scene is reported as a problem. References not fetched yet are fetched here; when the Bible
    text can't be reached at all, quotes are left as written."""
    missing = [a for s in script.scenes if s.type == "quote" and is_reference(s.author) for a in find_references(s.author)]
    missing = [r for r in dict.fromkeys(missing) if r not in passages]
    passages = {**passages, **fetch_all(cfg, missing)} if missing else passages
    scenes, problems = list(script.scenes), []
    for i, s in enumerate(scenes):
        if s.type != "quote" or not is_reference(s.author):
            continue
        refs = find_references(s.author or "")
        passage = passages.get(refs[0]) if refs else None
        if passage is None:  # offline or disabled: nothing to check against
            continue
        quoted = _words(s.text or "")
        if quoted and quoted in _words(passage.text):
            continue
        if len(passage.text) <= cfg.scripture.max_verse_chars:
            print(f"scene {i + 1}: replaced a loose quote of {refs[0]} with the exact verse")
            scenes[i] = s.model_copy(update={"text": passage.text})
        else:
            problems.append(f"scene {i + 1}'s quote doesn't match {refs[0]} and the passage is too long to show")
    return script.model_copy(update={"scenes": scenes}), problems


def credit(cfg: Config, passages: dict[str, Passage]) -> str:
    """Description line naming the translation (public domain, but credit is good practice)."""
    names = sorted({p.translation for p in passages.values()}) or [cfg.scripture.translation_name]
    return f"Scripture quotations: {', '.join(names)} (public domain)."
