"""Text-to-speech per scene, returning audio plus word-level timestamps.

Each scene is voiced separately so scene boundaries line up exactly with the
narration; clips are then joined into one WAV with a short pause between them.
"""

from __future__ import annotations

import asyncio
import base64
import re
import shutil
import subprocess
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
import requests

from fyt.config import ROOT, Config, secret
from fyt.models import Word

SAMPLE_RATE = 44100


@dataclass
class Clip:
    wav: Path
    duration: float
    words: list[Word]  # times relative to the clip start


def ffmpeg(*args: str) -> None:
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y", *args], check=True)


def to_wav(src: Path, dst: Path) -> float:
    ffmpeg("-i", str(src), "-ac", "1", "-ar", str(SAMPLE_RATE), "-sample_fmt", "s16", str(dst))
    with wave.open(str(dst)) as w:
        return w.getnframes() / w.getframerate()


def silence_wav(dst: Path, seconds: float) -> None:
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * int(seconds * SAMPLE_RATE))


def estimate_words(text: str, words_per_second: float = 2.6, offset: float = 0.1) -> tuple[list[Word], float]:
    """Evenly spaced word timings; used for the silent provider."""
    tokens = text.split()
    words, t = [], offset
    for tok in tokens:
        d = (0.12 + 0.045 * len(tok)) * (2.6 / words_per_second)
        words.append(Word(word=tok, start=round(t, 3), end=round(t + d, 3)))
        t += d + 0.04
    return words, t + 0.2


def words_from_chars(chars: list[str], starts: list[float], ends: list[float]) -> list[Word]:
    """Collapse ElevenLabs character alignment into words."""
    words: list[Word] = []
    buf, w_start, w_end = "", None, 0.0
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if buf:
                words.append(Word(word=buf, start=w_start, end=w_end))
            buf, w_start = "", None
            continue
        if w_start is None:
            w_start = s
        buf += ch
        w_end = e
    if buf:
        words.append(Word(word=buf, start=w_start, end=w_end))
    return words


def _elevenlabs(cfg: Config, text: str, out: Path, speed: float = 1.0) -> Clip:
    key = secret("ELEVENLABS_API_KEY")
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{cfg.voice.elevenlabs_voice_id}/with-timestamps",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": key},
        json={
            "text": text,
            "model_id": cfg.voice.elevenlabs_model,
            "voice_settings": {
                "stability": cfg.voice.elevenlabs_stability,
                "similarity_boost": 0.8,
                "style": cfg.voice.elevenlabs_style,
                "use_speaker_boost": True,
                "speed": max(0.7, min(1.2, speed)),
            },
        },
        timeout=180,
    )
    r.raise_for_status()
    body = r.json()
    mp3 = out.with_suffix(".mp3")
    mp3.write_bytes(base64.b64decode(body["audio_base64"]))
    duration = to_wav(mp3, out)
    mp3.unlink()
    a = body["alignment"]
    words = words_from_chars(a["characters"], a["character_start_times_seconds"], a["character_end_times_seconds"])
    return Clip(out, duration, words)


def _edge_rate(base: str, speed: float) -> str:
    """Combine the configured rate ("+5%") with a speed multiplier into Edge's "+N%" form."""
    try:
        pct = float(base.strip().rstrip("%"))
    except ValueError:
        pct = 0.0
    return f"{round((1 + pct / 100) * speed * 100 - 100):+d}%"


def _edge(cfg: Config, text: str, out: Path, speed: float = 1.0) -> Clip:
    import edge_tts

    rate = _edge_rate(cfg.voice.edge_rate, speed)

    async def run() -> tuple[bytes, list[Word]]:
        comm = edge_tts.Communicate(
            text, cfg.voice.edge_voice, rate=rate, pitch=cfg.voice.edge_pitch, boundary="WordBoundary"
        )
        audio, words = bytearray(), []
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7  # 100ns ticks
                words.append(Word(word=chunk["text"], start=start, end=start + chunk["duration"] / 1e7))
        return bytes(audio), words

    audio, words = asyncio.run(run())
    mp3 = out.with_suffix(".mp3")
    mp3.write_bytes(audio)
    duration = to_wav(mp3, out)
    mp3.unlink()
    return Clip(out, duration, _reattach_punctuation(text, words))


def _reattach_punctuation(text: str, words: list[Word]) -> list[Word]:
    """Edge reports bare words; restore trailing punctuation from the source text
    so captions can break on sentence ends."""
    tokens = text.split()
    if len(tokens) != len(words):
        return words
    return [w.model_copy(update={"word": tok}) for w, tok in zip(words, tokens)]


def _silent(cfg: Config, text: str, out: Path, speed: float = 1.0) -> Clip:
    words, duration = estimate_words(text)
    silence_wav(out, duration)
    return Clip(out, duration, words)


def _espeak(cfg: Config, text: str, out: Path, speed: float = 1.0) -> Clip:
    """Offline voice via espeak-ng. Robotic, but needs no network or key."""
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        raise RuntimeError("espeak-ng is not installed (apt install espeak-ng / brew install espeak-ng)")
    raw = out.with_suffix(".raw.wav")
    wpm = str(int(cfg.voice.espeak_wpm * speed))
    subprocess.run([exe, "-v", cfg.voice.espeak_voice, "-s", wpm, "-w", str(raw), text], check=True)
    duration = to_wav(raw, out)
    raw.unlink()
    # espeak reports no word timings; spread the estimate over the real duration.
    words, est = estimate_words(text, offset=0.0)
    k = duration / est if est else 1.0
    words = [w.model_copy(update={"start": round(w.start * k, 3), "end": round(w.end * k, 3)}) for w in words]
    return Clip(out, duration, words)


KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
KOKORO_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")
_kokoro_model = None


def _kokoro_load(cfg: Config):
    """Load Kokoro once per process, downloading the model files on first use."""
    global _kokoro_model
    if _kokoro_model is None:
        from kokoro_onnx import Kokoro

        d = ROOT / cfg.voice.kokoro_dir
        d.mkdir(parents=True, exist_ok=True)
        for name in KOKORO_FILES:
            path = d / name
            if not path.exists():
                print(f"downloading Kokoro model file {name} ...", flush=True)
                tmp = path.with_suffix(".part")
                with requests.get(f"{KOKORO_RELEASE}/{name}", stream=True, timeout=60) as r:
                    r.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                tmp.rename(path)
        _kokoro_model = Kokoro(str(d / KOKORO_FILES[0]), str(d / KOKORO_FILES[1]))
    return _kokoro_model


SENTENCE_END = re.compile(r"(?<=[.!?…—])\s+")


def _kokoro(cfg: Config, text: str, out: Path, speed: float = 1.0) -> Clip:
    """Kokoro-82M, run locally via ONNX: natural voice, free, no API key.

    Kokoro reports no word timings, so each sentence is voiced separately
    (exact sentence boundaries) and words are spread across their sentence.
    """
    import numpy as np

    model = _kokoro_load(cfg)
    v = cfg.voice
    parts, words, t = [], [], 0.0
    long_pause = False
    for sentence in [x for x in SENTENCE_END.split(text) if x.strip()]:
        trails = sentence.endswith(("…", "—", "..."))
        spoken = sentence.rstrip("….—") + "." if trails else sentence
        samples, sr = model.create(spoken, voice=v.kokoro_voice, speed=v.kokoro_speed * speed, lang=v.kokoro_lang)
        if parts:
            # A line that trails off ("...", "—") gets a longer breath before the next one.
            pause = np.zeros(int(v.kokoro_sentence_pause * (2.2 if long_pause else 1) * sr), dtype=np.float32)
            parts.append(pause)
            t += len(pause) / sr
        long_pause = trails
        dur = len(samples) / sr
        est_words, est = estimate_words(sentence, offset=0.0)
        k = dur / est if est else 1.0
        words += [w.model_copy(update={"start": round(t + w.start * k, 3), "end": round(t + w.end * k, 3)}) for w in est_words]
        parts.append(samples.astype(np.float32))
        t += dur
    audio = np.concatenate(parts) if parts else np.zeros(2400, dtype=np.float32)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    raw = out.with_suffix(".raw.wav")
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(pcm)
    duration = to_wav(raw, out)
    raw.unlink()
    return Clip(out, duration, words)


PROVIDERS = {"kokoro": _kokoro, "elevenlabs": _elevenlabs, "edge": _edge, "espeak": _espeak, "silent": _silent}


def synthesize(cfg: Config, text: str, out: Path, provider: str | None = None, speed: float = 1.0) -> Clip:
    """Voice one scene. `speed` multiplies the configured pace (mood pacing).

    Online voices (edge, elevenlabs) are retried, then fall back to `voice.fallback_provider`
    (Kokoro, offline) so a network hiccup never costs a video."""
    text = re.sub(r"\s+", " ", text).strip()
    name = provider or cfg.voice.provider
    if name not in ("edge", "elevenlabs") or not cfg.voice.fallback_provider:
        return PROVIDERS[name](cfg, text, out, speed)
    for attempt in range(3):
        try:
            return PROVIDERS[name](cfg, text, out, speed)
        except Exception as e:
            last = e
            time.sleep(3 * (attempt + 1))
    print(f"warning: {name} voice failed ({last}); using {cfg.voice.fallback_provider} for this scene")
    return PROVIDERS[cfg.voice.fallback_provider](cfg, text, out, speed)


def scene_speed(cfg: Config, mood: str | None) -> float:
    return cfg.voice.mood_speed.get(mood or "", 1.0) if cfg.voice.mood_pacing else 1.0


def scene_gaps(cfg: Config, scenes: list, short: bool = False) -> list[float]:
    """Silence after each scene: the scene's own pause_after, else its mood's default, else gap_seconds.
    Shorts keep their pauses tighter."""
    gaps = []
    for s in scenes:
        if s.pause_after is not None:
            g = s.pause_after
        elif cfg.voice.mood_pacing and s.mood:
            g = cfg.voice.mood_pause.get(s.mood, cfg.voice.gap_seconds)
        else:
            g = cfg.voice.gap_seconds
        g = max(0.2, min(3.0, g))
        gaps.append(round(g * 0.6, 3) if short and g > cfg.voice.gap_seconds else g)
    return gaps


def master_voice(cfg: Config, wav: Path) -> None:
    """Deepen, warm and add a little room to the joined narration, in place. Length is unchanged."""
    v = cfg.voice
    filters = []
    if v.depth_semitones:
        k = 2 ** (-abs(v.depth_semitones) / 12)
        filters += [f"asetrate={SAMPLE_RATE * k:.0f}", f"aresample={SAMPLE_RATE}", f"atempo={1 / k:.5f}"]
    if v.warmth:
        filters += ["bass=g=3:f=110:w=0.7", "treble=g=-2:f=7000"]
    if v.room:
        r = max(0.0, min(0.3, v.room))
        filters.append(f"aecho=0.85:0.8:45|85:{r:.2f}|{r * 0.6:.2f}")
    if v.loudness is not None:
        filters.append(f"loudnorm=I={v.loudness}:TP=-1.5:LRA=11")
    if not filters:
        return
    with wave.open(str(wav)) as w:
        seconds = w.getnframes() / w.getframerate()
    tmp = wav.with_suffix(".master.wav")
    chain = ",".join(filters + ["alimiter=limit=0.95", f"apad=whole_dur={seconds:.4f}", f"atrim=0:{seconds:.4f}"])
    ffmpeg("-i", str(wav), "-af", chain, "-ac", "1", "-ar", str(SAMPLE_RATE), str(tmp))
    tmp.replace(wav)


def join_clips(clips: list[Clip], gap: float | list[float], out: Path) -> list[tuple[float, float]]:
    """Concatenate clips with silence between them: `gap` seconds, or one gap per clip (the silence
    after it). Returns (start, end) per clip."""
    spans, t = [], 0.0
    gaps = gap if isinstance(gap, list) else [gap] * len(clips)
    with wave.open(str(out), "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(SAMPLE_RATE)
        for i, clip in enumerate(clips):
            with wave.open(str(clip.wav)) as src:
                frames = src.readframes(src.getnframes())
            dst.writeframes(frames)
            n = len(frames) // 2
            spans.append((t, t + n / SAMPLE_RATE))
            t += n / SAMPLE_RATE
            if i < len(clips) - 1:
                n_gap = int(gaps[i] * SAMPLE_RATE)
                dst.writeframes(b"\x00\x00" * n_gap)
                t += n_gap / SAMPLE_RATE
    return spans
