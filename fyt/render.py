"""Call the Remotion renderer (renderer/render.mjs) for the video and thumbnail."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from fyt.config import RENDERER_DIR

# Chromium bundled with Playwright, when present; Remotion downloads its own otherwise.
_KNOWN_BROWSERS = [Path("/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell")]


def _env() -> dict:
    env = dict(os.environ)
    if "REMOTION_BROWSER_EXECUTABLE" not in env:
        for p in _KNOWN_BROWSERS:
            if p.exists():
                env["REMOTION_BROWSER_EXECUTABLE"] = str(p)
    return env


def ensure_renderer() -> None:
    if not (RENDERER_DIR / "node_modules").exists():
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("Node.js/npm is required for rendering (https://nodejs.org)")
        subprocess.run([npm, "install"], cwd=RENDERER_DIR, check=True)


def dims(fmt: str) -> tuple[int, int]:
    """Frame size of a video format (same as renderer/src/theme.ts dims)."""
    return (1080, 1920) if fmt == "short" else (1920, 1080)


def normalize_loudness(video: Path, lufs: float) -> None:
    """Bring the finished mix to a target loudness, in place. The picture is copied untouched."""
    import imageio_ffmpeg

    tmp = video.with_suffix(".loud.mp4")
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y", "-i", str(video), "-c:v", "copy",
         "-af", f"loudnorm=I={lufs}:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "192k", str(tmp)],
        check=True,
    )
    tmp.replace(video)


def render(props_json: Path, public: Path, out: Path, still: bool = False, composition: str | None = None) -> Path:
    """Render the video, or with still=True the thumbnail (or another still `composition`, e.g. QuoteCard)."""
    ensure_renderer()
    cmd = ["node", "render.mjs", "--props", str(props_json), "--public", str(public), "--out", str(out)]
    if still:
        cmd.append("--still")
    if composition:
        cmd += ["--comp", composition]
    subprocess.run(cmd, cwd=RENDERER_DIR, check=True, env=_env())
    return out
