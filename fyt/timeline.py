"""Turn a script + voiced clips into renderer props (scene timings, captions)."""

from __future__ import annotations

from fyt.config import Config
from fyt.models import Brand, Media, Music, RenderProps, RenderScene, Script, Word

TAIL_SECONDS = 1.5  # hold the last scene after the voice ends (default; see Config.tail_seconds)
MUSIC_STEP = 0.25  # seconds between music volume points


def build_props(
    cfg: Config,
    script: Script,
    spans: list[tuple[float, float]],
    clip_words: list[list[Word]],
    media: dict[int, Media],
    voice: str | None,
    music: str | None,
) -> RenderProps:
    if len(spans) != len(script.scenes):
        raise ValueError("one audio span per scene is required")
    brand = None
    tail = cfg.tail_seconds
    if cfg.closing_card and cfg.channel.name:
        brand = Brand(name=cfg.channel.name, tagline=cfg.channel.tagline, seconds=3.5 if cfg.format == "long" else 2.5)
        tail = max(tail, brand.seconds + 0.5)
    duration = (spans[-1][1] if spans else 0) + tail
    scenes: list[RenderScene] = []
    captions: list[Word] = []
    for i, (scene, (start, _end)) in enumerate(zip(script.scenes, spans)):
        # A scene stays on screen until the next one starts, so pauses are covered.
        vis_start = 0.0 if i == 0 else start
        vis_end = spans[i + 1][0] if i + 1 < len(spans) else duration
        scenes.append(
            RenderScene(
                id=f"s{i + 1}",
                type=scene.type,
                start=round(vis_start, 3),
                end=round(vis_end, 3),
                heading=scene.heading,
                text=scene.text,
                items=scene.items,
                value=scene.value,
                prefix=scene.prefix,
                suffix=scene.suffix,
                data=scene.data,
                events=scene.events,
                left=scene.left,
                right=scene.right,
                leftTitle=scene.left_title,
                rightTitle=scene.right_title,
                author=scene.author,
                media=media.get(i),
                mood=scene.mood,
            )
        )
        captions.extend(
            Word(word=w.word, start=round(w.start + start, 3), end=round(w.end + start, 3)) for w in clip_words[i]
        )
    track = None
    if music:
        levels = music_levels(cfg, scenes, captions, duration, voiced=voice is not None) if cfg.music_dynamics else []
        track = Music(src=music, volume=cfg.music_volume, levels=levels, step=MUSIC_STEP)
    return RenderProps(
        format=cfg.format,
        fps=cfg.sleep.fps if cfg.is_sleep else 30,  # sleep videos are slow and calm: fewer frames to render
        title=script.title,
        duration=round(duration, 3),
        theme=cfg.theme.model_dump(),
        voice=voice,
        music=track,
        scenes=scenes,
        captions=captions,
        showCaptions=cfg.captions,
        showVisualizer=cfg.visualizer,
        brand=brand,
        letterbox=cfg.letterbox and cfg.format == "long",
    )


def music_levels(
    cfg: Config, scenes: list[RenderScene], words: list[Word], duration: float, voiced: bool = True
) -> list[float]:
    """The music's volume every MUSIC_STEP seconds, following the emotional journey:
    each scene's mood sets the level under the voice, the music swells when nobody is speaking
    (the pauses where a line lands), rises through the closing seconds, and fades in and out."""
    n = int(duration / MUSIC_STEP) + 2
    base, mood_level = cfg.music_volume, cfg.music_mood_level
    last_word = words[-1].end if words else 0.0
    raw = []
    wi = 0
    for k in range(n):
        t = k * MUSIC_STEP
        scene = next((s for s in scenes if s.start <= t < s.end), scenes[-1] if scenes else None)
        level = base * mood_level.get((scene.mood if scene else None) or "", 1.0)
        while wi < len(words) and words[wi].end + 0.35 < t:
            wi += 1
        speaking = voiced and wi < len(words) and words[wi].start - 0.35 <= t
        if t > last_word + 0.35 and words:  # after the last word: the music carries the ending
            level = base * max(mood_level.values(), default=1.0) * cfg.music_swell
        elif not speaking:
            level *= cfg.music_swell
        raw.append(level)
    # Smooth over ~1.5 s so the music breathes instead of jumping.
    w = 3
    smooth = [sum(raw[max(0, i - w) : i + w + 1]) / len(raw[max(0, i - w) : i + w + 1]) for i in range(n)]
    out = []
    for k, v in enumerate(smooth):
        t = k * MUSIC_STEP
        fade = min(1.0, t / 2.0, max(0.0, (duration - t) / 2.5))
        out.append(round(min(1.0, v) * fade, 4))
    return out


def to_srt(words: list[Word], max_words: int = 7) -> str:
    """Build an SRT caption file for YouTube from word timings."""

    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    lines, group = [], []
    for w in words:
        group.append(w)
        if len(group) >= max_words or w.word.endswith((".", "!", "?")):
            lines.append(group)
            group = []
    if group:
        lines.append(group)
    return "\n".join(
        f"{i}\n{ts(g[0].start)} --> {ts(g[-1].end)}\n{' '.join(w.word for w in g)}\n" for i, g in enumerate(lines, 1)
    )
