"""Stock footage/photos from Pexels and background music from a local folder."""

from __future__ import annotations

import random
import re
import shutil
import time
from pathlib import Path

import requests

from fyt.config import ROOT, Config, secret
from fyt.models import Media

PEXELS = "https://api.pexels.com"


def _get(path: str, params: dict) -> dict | None:
    key = secret("PEXELS_API_KEY")
    if not key:
        return None
    for attempt in range(3):  # ride out rate limits, server errors and dropped connections
        try:
            r = requests.get(f"{PEXELS}{path}", params=params, headers={"Authorization": key}, timeout=30)
        except requests.RequestException:
            if attempt == 2:
                raise
        else:
            if r.status_code != 429 and r.status_code < 500 or attempt == 2:
                r.raise_for_status()
                return r.json()
        time.sleep(5 * 2**attempt)
    return None


def _download(url: str, dst: Path) -> None:
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with dst.open("wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)


def _best_file(files: list[dict], vertical: bool) -> dict | None:
    """Pick an mp4 close to 1080p in the right orientation (smaller = faster render)."""
    target = 1920 if not vertical else 1080
    mp4s = [f for f in files if f.get("file_type") == "video/mp4" and f.get("width")]
    oriented = [f for f in mp4s if (f["height"] > f["width"]) == vertical] or mp4s
    return min(oriented, key=lambda f: abs(f["width"] - target), default=None)


MEDIA_EXT = {".jpg": "image", ".jpeg": "image", ".png": "image", ".webp": "image", ".mp4": "video", ".mov": "video"}
STOPWORDS = {"a", "an", "the", "of", "in", "on", "at", "and", "with", "to"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t and t not in STOPWORDS}


def local_visual(cfg: Config, query: str, public: Path, name: str, used: set[str]) -> Media | None:
    """The best match for the query in your own artwork folder (visuals_dir), by words in the file name."""
    folder = (ROOT / cfg.visuals_dir).resolve()
    want = _tokens(query or "")
    if not want or not folder.exists():
        return None
    best, score = None, 0
    for path in folder.rglob("*"):
        kind = MEDIA_EXT.get(path.suffix.lower())
        if not kind or f"local:{path}" in used:
            continue
        overlap = len(want & _tokens(str(path.relative_to(folder).with_suffix(""))))
        if overlap > score:
            best, score = path, overlap
    if best is None or score < min(2, len(want)):
        return None
    rel = f"media/{name}{best.suffix.lower()}"
    (public / "media").mkdir(parents=True, exist_ok=True)
    shutil.copy(best, public / rel)
    used.add(f"local:{best}")
    return Media(src=rel, kind=MEDIA_EXT[best.suffix.lower()])


# Cinematic imagery for each stage of the journey, used when a scene's own search finds nothing
# (stock libraries have no "Joseph in prison") or when a scene gives no search at all.
MOOD_QUERIES: dict[str, list[str]] = {
    "struggle": ["storm clouds dark", "rain on window night", "person alone in the dark", "lonely man walking rain",
                 "waves crashing rocks storm"],
    "uncertainty": ["fog forest path", "desert road alone", "person looking at horizon", "misty mountains",
                    "empty road fog"],
    "faith": ["candle flame dark", "hands praying", "man kneeling prayer", "ancient stone path",
              "old bible pages candlelight"],
    "realization": ["light through clouds", "sun rays through forest", "door opening light", "light breaking through darkness",
                    "sunbeams cathedral"],
    "hope": ["sunrise over mountains", "golden field sunrise", "sunrise clouds timelapse", "person watching sunrise",
             "light over the sea"],
    "strength": ["man walking mountain summit", "hiker reaching summit", "cross on hill sunrise", "person walking toward light",
                 "eagle flying mountains"],
}


def mood_queries(mood: str | None, i: int = 0) -> list[str]:
    """Fallback searches for a mood, rotated by scene number so neighbouring scenes differ."""
    qs = MOOD_QUERIES.get(mood or "", [])
    return qs[i % len(qs):] + qs[: i % len(qs)] if qs else []


def fetch_broll(cfg: Config, query: str | list[str], public: Path, name: str, used: set[str]) -> Media | None:
    """Your own artwork if a file matches, else a stock clip (or photo fallback). With several
    queries, each is tried in turn. None when unavailable."""
    queries = [query] if isinstance(query, str) else [q for q in query if q]
    for q in queries:
        local = local_visual(cfg, q, public, name, used)
        if local:
            return local
    if not cfg.stock_footage:
        return None
    for q in queries:
        m = _stock(cfg, q, public, name, used)
        if m:
            return m
    return None


def _stock(cfg: Config, query: str, public: Path, name: str, used: set[str]) -> Media | None:
    if not query:
        return None
    vertical = cfg.format == "short"
    orientation = "portrait" if vertical else "landscape"
    (public / "media").mkdir(parents=True, exist_ok=True)

    data = _get("/videos/search", {"query": query, "orientation": orientation, "per_page": 10, "size": "medium"})
    for video in (data or {}).get("videos", []):
        if str(video["id"]) in used or video.get("duration", 0) < 4:
            continue
        f = _best_file(video.get("video_files", []), vertical)
        if not f:
            continue
        rel = f"media/{name}.mp4"
        _download(f["link"], public / rel)
        used.add(str(video["id"]))
        return Media(src=rel, kind="video")
    return fetch_photo(cfg, query, public, name, used)


def fetch_photo(cfg: Config, query: str, public: Path, name: str, used: set[str]) -> Media | None:
    orientation = "portrait" if cfg.format == "short" else "landscape"
    data = _get("/v1/search", {"query": query, "orientation": orientation, "per_page": 10})
    for photo in (data or {}).get("photos", []):
        if f"p{photo['id']}" in used:
            continue
        rel = f"media/{name}.jpg"
        (public / "media").mkdir(parents=True, exist_ok=True)
        _download(photo["src"]["large2x"], public / rel)
        used.add(f"p{photo['id']}")
        return Media(src=rel, kind="image")
    return None


def pick_music(cfg: Config, public: Path, category: str | None = None) -> str | None:
    """Copy a track from music_dir (subfolders included) into the job, preferring tracks whose
    file or folder name suits the video (music_moods). Use only music you are licensed to use."""
    folder = (ROOT / cfg.music_dir).resolve()
    tracks = [p for p in folder.rglob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"}]
    if not tracks:
        return None
    words = cfg.music_moods.get(category or "", cfg.music_moods.get("default", []))
    fitting = [p for p in tracks if any(w in str(p.relative_to(folder)).lower() for w in words)]
    track = random.choice(fitting or tracks)
    dst = public / f"music{track.suffix.lower()}"
    shutil.copy(track, dst)
    return dst.name
