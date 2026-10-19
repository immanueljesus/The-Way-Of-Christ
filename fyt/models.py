"""Data shapes: what Claude writes (Script) and what the renderer reads (RenderProps)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

SceneType = Literal["title", "statement", "stat", "bars", "list", "quote", "timeline", "comparison", "broll"]

# The emotional journey every video follows. Each scene carries one, and it drives the
# narration pace, the pause after the scene, the music level and the colour grade of the picture.
Mood = Literal["struggle", "uncertainty", "faith", "realization", "hope", "strength"]
MOODS: tuple[str, ...] = ("struggle", "uncertainty", "faith", "realization", "hope", "strength")


class DataPoint(BaseModel):
    label: str
    value: float


class TimelineEvent(BaseModel):
    label: str
    text: str


class ScriptScene(BaseModel):
    """One beat of the video: what is said, and what is shown while it is said."""

    narration: str = Field(description="Exact words the narrator speaks for this scene.")
    type: SceneType = Field(description="Visual template used while the narration plays.")
    mood: Mood | None = Field(
        default=None,
        description="Where this moment sits in the journey: struggle, uncertainty, faith, realization, hope or strength.",
    )
    pause_after: float | None = Field(
        default=None,
        description="Seconds of silence after this scene (0.3-3) so a line can land; longest after the turning point.",
    )
    heading: str | None = Field(default=None, description="Short on-screen heading (max ~8 words).")
    text: str | None = Field(default=None, description="Supporting on-screen line, or the quote text for quote scenes.")
    items: list[str] | None = Field(default=None, description="list scenes: 2-5 short bullet items.")
    value: float | None = Field(default=None, description="stat scenes: the number to count up to.")
    prefix: str | None = Field(default=None, description="stat scenes: e.g. '$'.")
    suffix: str | None = Field(default=None, description="stat scenes: e.g. '%', 'x', 'M'.")
    data: list[DataPoint] | None = Field(default=None, description="bars scenes: 2-7 real data points.")
    events: list[TimelineEvent] | None = Field(default=None, description="timeline scenes: 3-5 dated events.")
    left_title: str | None = None
    left: list[str] | None = Field(default=None, description="comparison scenes: left column bullets.")
    right_title: str | None = None
    right: list[str] | None = Field(default=None, description="comparison scenes: right column bullets.")
    author: str | None = Field(
        default=None,
        description="quote scenes: the Bible reference (e.g. 'Matthew 11:28') or the real person who said it.",
    )
    image: int | None = Field(
        default=None,
        description="Number of the article image (from the 'Available images' list) to show behind this scene, if one fits what is being said.",
    )
    broll_query: str | None = Field(
        default=None,
        description="2-4 word stock-footage search query for what is being said, concrete, cinematic and visual "
        "(e.g. 'desert path footprints', 'candle dark room', 'fishing boat storm'). Used when no artwork fits.",
    )
    visual_prompt: str | None = Field(
        default=None,
        description="Storyboard: one sentence describing the cinematic shot for this moment (setting, light, "
        "mood, camera), e.g. 'Dim stone prison cell, a single shaft of light falls on a young man's hands'. "
        "Used for the storyboard and for AI-generated or hand-picked visuals.",
    )


class Chapter(BaseModel):
    title: str
    scene: int  # index of the scene the chapter starts on


class Script(BaseModel):
    title: str = Field(description="YouTube title, max 70 characters, curiosity-driven but truthful.")
    description: str = Field(description="YouTube description: 2 short paragraphs, then key points. No hashtag spam.")
    tags: list[str] = Field(description="8-15 search tags.")
    thumbnail_text: str = Field(description="2-5 punchy words for the thumbnail (not the title).")
    thumbnail_kicker: str = Field(description="1-3 word label above the thumbnail text: the series or Bible figure.")
    thumbnail_query: str = Field(description="Stock photo search query for a cinematic thumbnail background.")
    scenes: list[ScriptScene]
    sources: list[str] = Field(description="URLs or references backing the facts used.")
    # Set by the pipeline for long videos written chapter by chapter; not asked of the model.
    chapters: SkipJsonSchema[list[Chapter] | None] = None
    series: SkipJsonSchema[str | None] = None  # playlist the video is filed under
    # Other thumbnail texts for YouTube Studio's Test & compare (set by the polish step).
    thumbnail_variants: SkipJsonSchema[list[str] | None] = None


class Word(BaseModel):
    word: str
    start: float
    end: float


class Media(BaseModel):
    src: str
    kind: Literal["video", "image"]
    # A close-up on part of the picture (a second shot from the same painting).
    detail: bool | None = None


class RenderScene(BaseModel):
    id: str
    type: SceneType
    start: float
    end: float
    heading: str | None = None
    text: str | None = None
    items: list[str] | None = None
    value: float | None = None
    prefix: str | None = None
    suffix: str | None = None
    data: list[DataPoint] | None = None
    events: list[TimelineEvent] | None = None
    left: list[str] | None = None
    right: list[str] | None = None
    leftTitle: str | None = None
    rightTitle: str | None = None
    author: str | None = None
    media: Media | None = None
    # More shots after `media`: the scene is cut into equal parts, one shot each (faster cuts in Shorts).
    shots: list[Media] | None = None
    mood: Mood | None = None


class Music(BaseModel):
    src: str
    volume: float
    # Volume every `step` seconds: ducked under the voice, swelling in the pauses and at the
    # turning points, rising at the end. The renderer interpolates between the points.
    levels: list[float] = Field(default_factory=list)
    step: float = 0.25


class Brand(BaseModel):
    name: str
    tagline: str = ""
    seconds: float = 3.0  # closing card at the end of the video


class RenderProps(BaseModel):
    format: Literal["long", "short"]
    fps: int = 30
    title: str
    duration: float
    theme: dict
    voice: str | None
    music: Music | None
    scenes: list[RenderScene]
    captions: list[Word]
    showCaptions: bool
    showVisualizer: bool
    brand: Brand | None = None
    letterbox: bool = False  # cinematic 2.39:1 bars on 16:9 videos


class QuoteCardProps(BaseModel):
    """A square quote card (Scripture or a line from the video) for the Community tab."""

    text: str
    reference: str = ""
    channel: str = ""
    theme: dict
    background: Media | None = None


class ThumbnailProps(BaseModel):
    format: Literal["long", "short"]
    title: str
    kicker: str
    theme: dict
    background: Media | None
    layout: Literal["side", "center"] = "side"  # text on the left over a side fade, or centred
