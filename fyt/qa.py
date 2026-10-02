"""Automatic checks before anything is uploaded. Returns a list of problems."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

from fyt.config import Config
from fyt.models import RenderProps, Script


def media_duration(path: Path) -> float | None:
    """Duration in seconds, parsed from ffmpeg's banner (no ffprobe in imageio-ffmpeg)."""
    proc = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True, check=False
    )
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", proc.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None


def check_script(cfg: Config, script: Script) -> list[str]:
    problems = []
    if not script.scenes:
        problems.append("script has no scenes")
    if len(script.title) > 100:
        problems.append(f"title is {len(script.title)} chars (YouTube max 100)")
    if len(script.description) > 5000:
        problems.append("description exceeds 5000 chars")
    if len(",".join(script.tags)) > 500:
        problems.append("tags exceed 500 chars in total")
    if "<" in script.title + script.description or ">" in script.title + script.description:
        problems.append("title/description contain '<' or '>', which YouTube rejects")
    for i, s in enumerate(script.scenes, 1):
        if not s.narration.strip():
            problems.append(f"scene {i} has no narration")
        if s.type == "bars" and not s.data:
            problems.append(f"scene {i} is a bar chart without data")
        if s.type == "list" and not s.items:
            problems.append(f"scene {i} is a list without items")
        if s.type == "quote" and not (s.text and s.author):
            problems.append(f"scene {i} is a quote without text/author")
    return problems


def check_render(cfg: Config, props: RenderProps, video: Path, voiced: bool = True) -> list[str]:
    problems = []
    if not video.exists() or video.stat().st_size < 10_000:
        return ["rendered video is missing or empty"]
    dur = media_duration(video)
    if dur is None:
        problems.append("could not read rendered video duration")
    elif abs(dur - props.duration) > 1.0:
        problems.append(f"video is {dur:.1f}s but the timeline is {props.duration:.1f}s")
    if cfg.format == "short" and props.duration > 180:
        problems.append(f"short is {props.duration:.0f}s; Shorts must be 3 minutes or less")
    if cfg.format == "long" and props.duration < 0.5 * cfg.target_seconds:
        problems.append(f"video is {props.duration:.0f}s, far below the {cfg.target_seconds:.0f}s target")
    if voiced and props.voice is None:
        problems.append("no voice track")
    return problems
