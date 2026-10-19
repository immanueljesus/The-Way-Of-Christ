"""Stock footage/photos from Pexels and background music from a local folder."""

from __future__ import annotations

import random
import re
import shutil
import subprocess
import time
from pathlib import Path

import imageio_ffmpeg
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


def mood_queries(mood: str | None, i: int = 0, offset: int = 0) -> list[str]:
    """Fallback searches for a mood, rotated by scene number so neighbouring scenes differ, and by
    a per-video offset so each video starts from a different one."""
    qs = MOOD_QUERIES.get(mood or "", [])
    k = (i + offset) % len(qs) if qs else 0
    return qs[k:] + qs[:k]


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


def _off_brand(cfg: Config, text: str) -> bool:
    """Whether a stock result's description (Pexels page slug or photo alt text) names something
    that doesn't fit the channel, e.g. a brand logo, a party or a neon sign."""
    t = text.lower().replace("-", " ").replace("/", " ")
    return any(re.search(rf"\b{re.escape(w.lower())}s?\b", t) for w in cfg.stock_skip_words)


# How many results to look at per search, and how many of the best unused ones to pick from at
# random: the same search (moods repeat from video to video) then gives a different shot each time.
PER_PAGE = 40
PICK_FROM = 8


def _varied(items: list) -> list:
    """The first PICK_FROM items in random order, then the rest in search order."""
    head = items[:PICK_FROM]
    random.shuffle(head)
    return head + items[PICK_FROM:]


def _stock(cfg: Config, query: str, public: Path, name: str, used: set[str]) -> Media | None:
    if not query:
        return None
    vertical = cfg.format == "short"
    orientation = "portrait" if vertical else "landscape"
    (public / "media").mkdir(parents=True, exist_ok=True)

    data = _get("/videos/search", {"query": query, "orientation": orientation, "per_page": PER_PAGE, "size": "medium"})
    fresh = [
        v for v in (data or {}).get("videos", [])
        if str(v["id"]) not in used and v.get("duration", 0) >= 4 and not _off_brand(cfg, v.get("url", ""))
    ]
    for video in _varied(fresh):
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
    data = _get("/v1/search", {"query": query, "orientation": orientation, "per_page": PER_PAGE})
    fresh = [
        p for p in (data or {}).get("photos", [])
        if f"p{p['id']}" not in used and not _off_brand(cfg, f"{p.get('alt', '')} {p.get('url', '')}")
    ]
    for photo in _varied(fresh):
        rel = f"media/{name}.jpg"
        (public / "media").mkdir(parents=True, exist_ok=True)
        _download(photo["src"]["large2x"], public / rel)
        used.add(f"p{photo['id']}")
        return Media(src=rel, kind="image")
    return None


CLIP_FPS = 30
MAX_SLOWDOWN = 2.0  # a short clip is slowed (cinematic slow motion) up to this much before it loops


def _probe_seconds(path: Path) -> float | None:
    proc = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True, check=False)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", proc.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None


def conform_clip(src: Path, dst: Path, seconds: float, width: int, height: int) -> None:
    """Re-encode a stock clip into what the renderer handles reliably: H.264, constant 30 fps,
    exactly the video's frame size, no audio, starting at 0 and at least `seconds` long.

    Stock clips come in every shape (25/29.97/59.94 fps, variable frame rates, odd sizes like
    1080x2048, edit lists), and some make Remotion fail with "No frame found at position".
    A clip shorter than its scene is first slowed down (up to 2x), then looped."""
    have = _probe_seconds(src)
    if not have:
        raise RuntimeError(f"could not read {src.name}")
    slow = max(1.0, min(MAX_SLOWDOWN, seconds / have))
    vf = (
        f"setpts={slow:.4f}*PTS,scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps={CLIP_FPS},format=yuv420p"
    )
    loop = ["-stream_loop", "-1"] if have * slow < seconds else []
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y", *loop, "-i", str(src), "-t", f"{seconds:.3f}",
         "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-movflags", "+faststart", str(dst)],
        check=True,
    )


def still_from_clip(src: Path, dst: Path) -> None:
    """A frame from a third of the way into a clip, for when the clip itself can't be used."""
    have = _probe_seconds(src) or 0
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y", "-ss", f"{have / 3:.2f}", "-i", str(src),
         "-frames:v", "1", "-q:v", "2", str(dst)],
        check=True,
    )


MUSIC_EXT = {".mp3", ".wav", ".m4a", ".ogg"}
MUSIC_CREDIT = "music-credit.txt"  # written next to the job's music when the track needs a credit
MUSIC_LUFS = -20  # every track is brought to the same loudness, so music_volume means the same for all


def _music_manifest(cfg: Config) -> dict:
    import yaml

    path = ROOT / cfg.music_manifest
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _library_track(cfg: Config, category: str | None, seconds: float | None) -> tuple[Path, str] | None:
    """A track from the free library (content/music.yaml), downloaded into music_dir on first use.
    Prayers get calm tracks, everything else cinematic ones; long videos prefer a track that lasts."""
    manifest = _music_manifest(cfg)
    tracks = manifest.get("tracks") or []
    if not tracks:
        return None
    mood = "prayer" if category == "prayer" else "cinematic"
    pool = [t for t in tracks if t.get("mood") == mood] or tracks
    if seconds:
        lasting = [t for t in pool if t.get("seconds", 0) >= seconds]
        pool = lasting or [max(pool, key=lambda t: t.get("seconds", 0))]
    t = random.choice(pool)
    folder = (ROOT / cfg.music_dir).resolve() / "library" / t.get("mood", "cinematic")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (t["title"].replace(" ", "_") + ".mp3")
    if not path.exists():
        url = manifest.get("base_url", "") + requests.utils.quote(t["title"]) + ".mp3"
        tmp = path.with_suffix(".part")
        _download(url, tmp)
        tmp.replace(path)
    return path, manifest.get("credit", "").format(title=t["title"])


def pick_music(cfg: Config, public: Path, category: str | None = None, seconds: float | None = None) -> str | None:
    """Put a music track for the video into the job (as music.m4a) and return its file name.

    Your own tracks in music_dir win (subfolders by feel, picked by music_moods); otherwise a track
    from the free library in content/music.yaml is used, and its required credit is written to
    music-credit.txt for the description. Each track is levelled to the same loudness and cut to
    the video's length. Use only music you are licensed to use."""
    folder = (ROOT / cfg.music_dir).resolve()
    library = folder / "library"
    own = [p for p in folder.rglob("*") if p.suffix.lower() in MUSIC_EXT and library not in p.parents]
    credit = ""
    if own:
        words = cfg.music_moods.get(category or "", cfg.music_moods.get("default", []))
        fitting = [p for p in own if any(w in str(p.relative_to(folder)).lower() for w in words)]
        track = random.choice(fitting or own)
    else:
        try:
            found = _library_track(cfg, category, seconds)
        except Exception as e:  # no music is better than no video
            print(f"warning: could not get a music track: {e}")
            return None
        if found is None:
            return None
        track, credit = found
    dst = public / "music.m4a"
    cut, start = [], []
    if seconds:
        cut = ["-t", f"{seconds + 5:.1f}"]
        # Cinematic tracks build to a peak late in the track (about 80% in) before their fade-out:
        # start far enough in that the video's last moments (strength) meet that peak, not the fade.
        # Calm prayer tracks start from the top.
        length = _probe_seconds(track) or 0
        if category != "prayer" and length * 0.8 > seconds:
            start = ["-ss", f"{length * 0.8 - seconds:.1f}"]
    try:
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y", *start, "-i", str(track), "-vn", *cut,
             "-af", f"loudnorm=I={MUSIC_LUFS}:TP=-2:LRA=11", "-ar", "44100", "-c:a", "aac", "-b:a", "192k", str(dst)],
            check=True,
        )
    except Exception as e:
        print(f"warning: could not level {track.name} ({e}); using it as is")
        dst = public / f"music{track.suffix.lower()}"
        shutil.copy(track, dst)
    (public / MUSIC_CREDIT).write_text(credit, encoding="utf-8")
    return dst.name


def music_credit(public: Path) -> str:
    p = public / MUSIC_CREDIT
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""
