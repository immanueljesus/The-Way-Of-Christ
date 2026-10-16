"""Channel config (channel.yaml) plus secrets from the environment / .env."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
RENDERER_DIR = ROOT / "renderer"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader: KEY=VALUE lines, existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class Theme(BaseModel):
    # Warm candlelight on deep umber (see docs/CHANNEL_ARCHITECTURE.md, "Visual identity").
    background: str = "#120d09"
    background2: str = "#3a2616"
    accent: str = "#e8b86d"
    accent2: str = "#7fa7c4"
    text: str = "#fbf6ee"
    muted: str = "#cdbca3"
    font: str = "Georgia, 'DejaVu Serif', 'Times New Roman', serif"


class ChannelInfo(BaseModel):
    name: str = "My Channel"
    niche: str = "Biblical wisdom and Christian encouragement for the battles of everyday life"
    audience: str = "people going through hard seasons who want hope, strength and Scripture they can hold on to"
    tone: str = "warm, calm, compassionate storytelling; hopeful, never preachy, hype-free or fear-driven"
    language: str = "en"
    # Every video should answer: "What does this person need to hear right now?"
    promise: str = ""
    # Appended to every description (e.g. the Bible translation credit, a gentle call to subscribe).
    description_footer: str = ""
    # Closing card: the channel name and this line fade in over the last seconds of every video.
    tagline: str = ""


class VoiceConfig(BaseModel):
    # kokoro: free, natural Kokoro-82M voice run locally (model downloads once, ~350 MB).
    # elevenlabs: best quality (paid). edge: free Microsoft neural voices.
    # espeak: offline espeak-ng voice (robotic; no network or key needed).
    # silent: no audio, timings estimated -- for testing the render only.
    provider: Literal["kokoro", "elevenlabs", "edge", "espeak", "silent"] = "kokoro"
    elevenlabs_voice_id: str = "JBFqnCBsd6RMkjVDRZzb"
    elevenlabs_model: str = "eleven_multilingual_v2"
    # Lower stability and some style give ElevenLabs a more emotional, less even read.
    elevenlabs_stability: float = 0.5
    elevenlabs_style: float = 0.0
    edge_voice: str = "en-US-AndrewMultilingualNeural"
    edge_rate: str = "+5%"
    edge_pitch: str = "+0Hz"  # e.g. "-6Hz" for a deeper voice
    kokoro_voice: str = "am_michael"  # e.g. af_heart, am_michael, bm_george, bf_emma
    kokoro_speed: float = 1.05
    kokoro_lang: str = "en-us"
    kokoro_sentence_pause: float = 0.18
    kokoro_dir: str = "assets/kokoro"
    espeak_voice: str = "en-us"
    espeak_wpm: int = 165
    gap_seconds: float = 0.35  # pause between scenes (scenes can ask for longer: pause_after)
    # Used for a scene when an online voice (edge, elevenlabs) keeps failing; "" to fail instead.
    fallback_provider: str = "kokoro"
    # Pace and pauses follow the emotional journey: each mood slows or quickens the read
    # (multiplies the voice speed) and sets the default silence after its scenes.
    mood_pacing: bool = False
    mood_speed: dict[str, float] = Field(
        default_factory=lambda: {
            "struggle": 0.94, "uncertainty": 0.95, "faith": 0.97,
            "realization": 0.92, "hope": 1.0, "strength": 1.03,
        }
    )
    mood_pause: dict[str, float] = Field(
        default_factory=lambda: {
            "struggle": 0.8, "uncertainty": 0.9, "faith": 0.9,
            "realization": 1.8, "hope": 1.1, "strength": 1.0,
        }
    )
    # Mastering on the joined narration: lower the pitch a little for a deeper voice, add
    # low-end warmth and a touch of room. 0 / false / 0 leaves the voice untouched.
    depth_semitones: float = 0.0
    warmth: bool = False
    room: float = 0.0  # 0-0.3
    # Normalise the narration to this loudness (LUFS; YouTube plays at about -14). None to leave it.
    loudness: float | None = None
    # Narration pace, used to size scripts to their target length. A deliberate narrator with pauses reads ~120.
    words_per_minute: int = 150
    # The voice cast (edge): which voice reads which videos, so each series always sounds the same.
    # Keys, most specific first: "sleep" (sleep videos), a series name, a category; each may end in
    # ":short" or ":long" to apply to one format only. Anything else uses edge_voice.
    cast: dict[str, str] = Field(default_factory=dict)
    # Kokoro voices used when an Edge voice fails mid-video, matched to the cast voice's gender.
    kokoro_female: str = "af_heart"


class YouTubeConfig(BaseModel):
    privacy: Literal["private", "unlisted", "public"] = "private"
    category_id: str = "27"  # Education
    made_for_kids: bool = False
    # YouTube's "altered or synthetic content" label. Required for REALISTIC synthetic content: a real
    # person made to say or do something, realistic AI footage of real places or events, AI music.
    # Not required for AI help with scripts, titles or captions, stock footage, artwork or a narrator
    # voice that imitates no real person. Turn it on if you add realistic AI-generated imagery or video.
    contains_synthetic_media: bool = False
    # Hours from upload to scheduled publish; forces privacy=private until then.
    publish_delay_hours: float | None = None
    # Adds a random 0..N minute delay on top, so videos don't go live at the exact
    # same minute every day. Also schedules the publish when publish_delay_hours is unset.
    publish_jitter_minutes: int = 0
    upload_captions: bool = True


class LLMConfig(BaseModel):
    # anthropic: Claude (uses `model` and ANTHROPIC_API_KEY; web research works).
    # openai: any OpenAI-compatible API, e.g. Groq's free tier serving open models,
    # OpenRouter, or a local Ollama (base_url http://localhost:11434/v1). No web research.
    provider: Literal["anthropic", "openai"] = "anthropic"
    base_url: str = "https://api.groq.com/openai/v1"
    model: str = "openai/gpt-oss-120b"  # see https://console.groq.com/docs/models
    api_key_env: str = "GROQ_API_KEY"
    temperature: float = 0.8
    # For reasoning models (gpt-oss). Hidden reasoning counts against max_tokens,
    # so "low" leaves room for the script itself. Empty to omit.
    reasoning_effort: str = "low"
    max_note_chars: int = 6000  # research notes sent to the model (free tiers limit tokens/minute)
    # Tried in order when `model` keeps failing (outage, daily token cap). On Groq each
    # model has its own free limits.
    fallback_models: list[str] = Field(default_factory=list)


class WikipediaConfig(BaseModel):
    lang: str = "en"
    # Where to find article ideas. List pages contribute every article they link to.
    list_pages: list[str] = Field(default_factory=lambda: ["Wikipedia:Unusual articles"])
    categories: list[str] = Field(default_factory=list)  # e.g. "Unsolved problems in physics"
    articles: list[str] = Field(default_factory=list)  # specific article titles
    min_chars: int = 3000  # skip stubs
    long_min_chars: int = 15000  # long videos need an article with enough material
    max_chars: int = 40000  # truncate very long articles in the notes
    # Article images whose file name or description contains one of these words are skipped,
    # to keep the artwork consistent with the channel's look.
    image_skip_words: list[str] = Field(default_factory=list)


class PlanSlot(BaseModel):
    """One fixed publish slot in the weekly plan, e.g. Tuesday's Bible story."""

    weekday: int  # Monday = 0
    time: str  # "HH:MM" UTC
    kind: Literal["short", "long"]
    category: str | None = None  # catalog category to draw from (see `catalog.mix`)
    minutes: float | None = None  # long videos: target length (overrides target_minutes)
    label: str = ""  # shown in `fyt buffer`


class ScheduleConfig(BaseModel):
    """`fyt fill`: keep the next few days of publish slots filled with videos uploaded
    ahead of time, so a failed or skipped run never costs a publish."""

    # Shorts go live at these UTC times, each at a random minute up to
    # youtube.publish_jitter_minutes later.
    # The time zone the slot times below are in (and the weekdays of the plan), e.g.
    # "America/New_York": slots then follow daylight saving. Default UTC.
    timezone: str = "UTC"
    short_slots: list[str] = Field(default_factory=lambda: ["14:00", "22:00"])
    long_weekday: int | None = 5  # the long video's day (Monday = 0); None for no long videos
    long_slot: str = "16:00"  # UTC
    buffer_days: float = 2.0  # how far ahead Shorts are kept scheduled
    long_lead_days: float = 3.0  # the long video is made up to this many days before it goes live
    # The YouTube Data API allows 10,000 units a day and an upload with thumbnail and captions uses ~2,050.
    max_uploads_per_day: int = 4
    max_run_minutes: int = 120  # stop starting new videos after this, so the job never times out
    # Fixed weekly slots, in addition to the daily short_slots and long_weekday above.
    plan: list[PlanSlot] = Field(default_factory=list)


class GrowthConfig(BaseModel):
    polish: bool = True  # second pass on title, hook and thumbnail text (plus a loop line for Shorts)
    loop_shorts: bool = True  # Shorts end on a line that leads back into the hook (seamless replay)
    rank_topics: bool = True  # pick articles by fit with the niche and Wikipedia pageviews
    min_topic_fit: int = 6  # 0-10; articles the model rates lower are skipped
    cuts_per_long: int = 2  # Shorts cut from each long video (they fill regular Short slots)
    series: list[str] = Field(default_factory=list)  # playlists; each video is filed under one
    # Extra videos on topics trending on Wikipedia that fit the niche, on top of the schedule.
    bonus_shorts_per_day: int = 1
    bonus_longs_per_week: int = 1
    bonus_min_fit: int = 7  # 0-10
    bonus_long_min_fit: int = 9


class ScriptureConfig(BaseModel):
    """Exact Bible text for the references a video uses, so Scripture is never misquoted.
    Fetched from bible-api.com, which serves public-domain translations."""

    enabled: bool = True
    # webbe: World English Bible, British Edition (public domain, modern English, says "the LORD").
    # web: World English Bible (uses "Yahweh"), kjv: King James Version.
    translation: str = "webbe"
    translation_name: str = "World English Bible"
    api: str = "https://bible-api.com"
    max_verse_chars: int = 400  # longer passages are summarised, not shown in full


class CatalogConfig(BaseModel):
    """source: catalog. Videos come from a curated idea list (content/ideas.yaml)."""

    path: str = "content/ideas.yaml"
    # Share of videos per category, in percent. The next idea comes from the category furthest
    # below its share, unless the publish slot names a category.
    mix: dict[str, float] = Field(
        default_factory=lambda: {"motivational": 40, "bible_story": 25, "prayer": 15, "jesus": 10, "facts": 10}
    )
    # Use the idea's Wikipedia article (if it names one) for background notes and classical artwork.
    use_wikipedia: bool = True
    # When every idea is used, ask the model for new topics in the channel's niche.
    ideate_when_empty: bool = True


class LiturgyConfig(BaseModel):
    """The Christian calendar engine (fyt/liturgy.py, content/calendar.yaml)."""

    enabled: bool = False
    path: str = "content/calendar.yaml"
    # Which events to include, by their `tradition` in calendar.yaml: ecumenical (shared by most
    # Christians), western, catholic, orthodox, world (New Year, Mother's Day...), saints.
    traditions: list[str] = Field(default_factory=lambda: ["ecumenical", "western", "world"])
    easter: Literal["western", "orthodox"] = "western"  # which Easter the moveable feasts follow
    lead_days: float = 7  # campaign videos are made and scheduled up to this many days ahead
    long_time: str = "15:00"  # UTC; a campaign long video takes the plan's long slot that day, or this time
    short_times: list[str] = Field(default_factory=lambda: ["17:00", "19:00"])  # UTC, for campaign Shorts
    season_bias: bool = True  # evergreen picks lean towards the season's themes (Lent: repentance...)


class InsightsConfig(BaseModel):
    """The analytics feedback loop (fyt/insights.py): what viewers actually watched, read once a week from
    the free YouTube Analytics API, nudges topic, title and script choices. Never what a passage says."""

    enabled: bool = True
    refresh_days: float = 7  # how often the lessons are recomputed
    lookback_days: int = 90  # videos published in this window are compared
    min_views: int = 30  # videos with fewer views say too little to learn from
    min_videos: int = 3  # a category or title style needs this many videos before it is judged
    retention_videos: int = 15  # newest videos whose retention curve (hook hold) is read, one request each
    # How far a lesson may move a pillar's share of the content mix (x0.8 .. x1.25 by default).
    max_weight: float = 1.25
    min_weight: float = 0.8


class BonusConfig(BaseModel):
    """Extra videos on top of the schedule (fyt/bonus.py), only from what's left of the day's upload quota
    and the month's free GitHub Actions minutes."""

    # Follow-ups to winners: a Short that held viewers far better than the channel's usual (insights lift)
    # gets a follow-up Short on the same passage, and a long version when the minutes allow.
    winners: bool = False
    min_lift: float = 1.25
    # Rising topics: Bible and faith Wikipedia articles whose readership jumps, and new YouTube search
    # suggestions for faith searches, matched to an unused idea or turned into one (Scripture checked).
    trends: bool = False
    watch_articles: list[str] = Field(default_factory=list)  # besides every Wikipedia article the ideas name
    spike_ratio: float = 2.0  # last 2 days vs the month's median daily readers
    min_daily_views: int = 1500
    suggest_seeds: list[str] = Field(default_factory=list)  # YouTube search suggestion seeds, e.g. "prayer for"
    min_fit: int = 8  # 0-10, how well a rising topic must fit the channel
    # Caps.
    shorts_per_week: int = 4
    longs_per_month: int = 1
    long_minutes: float = 8
    follow_up_days: int = 4  # a winner's follow-ups go out within this many days, or are dropped
    # The free Actions allowance for a private repo; bonuses only run while the month's projected use
    # (measured run minutes + the rest of the month at the same pace) stays under this.
    monthly_minutes: int = 2000
    run_overhead_minutes: float = 5  # setup minutes per workflow run that the pipeline doesn't see


class SleepConfig(BaseModel):
    """Long calm videos to fall asleep to ("Fall asleep in God's Word"). A video of 18 minutes or more is
    made this way: slower voice, longer pauses, calm music, no on-screen captions, and a low frame rate
    so a 30-60 minute video renders on the free runner in about the time an 8-10 minute one takes."""

    fps: int = 12
    words_per_minute: int = 95  # a slow, restful read with long pauses
    gap_seconds: float = 2.0
    edge_rate: str = "-18%"
    kokoro_speed: float = 0.8
    music_volume: float = 0.22
    captions: bool = False  # burned-in captions (the .srt is still uploaded)
    letterbox: bool = False


class ThumbnailConfig(BaseModel):
    # Long videos get thumbnail-b.png and thumbnail-c.png beside thumbnail.png (which is uploaded):
    # three versions to load into YouTube Studio's Test & compare by hand.
    variants: int = 3


class LocalizeConfig(BaseModel):
    """Translated titles and descriptions (fyt/localize.py), uploaded as YouTube localizations: viewers
    whose YouTube is set to one of these languages see the title and description in it."""

    languages: list[str] = Field(default_factory=list)  # e.g. ["es"]


class Config(BaseModel):
    channel: ChannelInfo = Field(default_factory=ChannelInfo)
    format: Literal["long", "short"] = "long"
    target_minutes: float = 6.0  # ignored for shorts (always < 60s)
    model: str = "claude-opus-5"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    # catalog: videos come from the curated idea list (see `catalog`), with exact Scripture text.
    # wikipedia: videos are written from niche Wikipedia articles (see `wikipedia`).
    # web: Claude researches each topic with web search first.
    source: Literal["catalog", "wikipedia", "web"] = "web"
    wikipedia: WikipediaConfig = Field(default_factory=WikipediaConfig)
    catalog: CatalogConfig = Field(default_factory=CatalogConfig)
    scripture: ScriptureConfig = Field(default_factory=ScriptureConfig)
    liturgy: LiturgyConfig = Field(default_factory=LiturgyConfig)
    research: bool = True  # use Claude's web search before scripting (source: web)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    music_dir: str = "assets/music"
    # Free, credited music used when music_dir has none of your own tracks (see content/music.yaml).
    music_manifest: str = "content/music.yaml"
    # Your own licensed or AI-generated artwork. Files whose names share words with a scene's
    # footage search (e.g. "joseph-prison-light.jpg" for "joseph prison") are used before stock footage.
    visuals_dir: str = "assets/visuals"
    music_volume: float = 0.07  # music level under the narration
    # Music follows the journey: it sits low under struggle and rises through hope to strength,
    # swells in the pauses between lines (music_swell x) and rises again at the end.
    music_dynamics: bool = False
    music_swell: float = 2.0
    music_mood_level: dict[str, float] = Field(
        default_factory=lambda: {
            "struggle": 0.7, "uncertainty": 0.8, "faith": 0.9,
            "realization": 1.1, "hope": 1.25, "strength": 1.5,
        }
    )
    # Tracks are picked by the video's category: a file or folder name containing one of these
    # words wins, e.g. assets/music/cinematic/rising-hope.mp3 for a motivational video.
    music_moods: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "prayer": ["prayer", "calm", "ambient", "piano", "worship"],
            "default": ["cinematic", "inspir", "hope", "epic", "emotional", "rise", "build"],
        }
    )
    tail_seconds: float = 1.5  # picture and music held after the last word
    letterbox: bool = False  # cinematic bars on long (16:9) videos
    closing_card: bool = False  # channel name + tagline over the last seconds (lengthens the tail)
    # Normalise the finished video's sound to this loudness (LUFS; YouTube plays at -14). None to skip.
    mix_loudness: float | None = None
    stock_footage: bool = True  # needs PEXELS_API_KEY
    # Stock results whose description contains one of these are skipped (off-brand for the channel).
    stock_skip_words: list[str] = Field(default_factory=list)
    captions: bool = True
    visualizer: bool = True
    theme: Theme = Field(default_factory=Theme)
    youtube: YouTubeConfig = Field(default_factory=YouTubeConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    growth: GrowthConfig = Field(default_factory=GrowthConfig)
    insights: InsightsConfig = Field(default_factory=InsightsConfig)
    bonus: BonusConfig = Field(default_factory=BonusConfig)
    sleep: SleepConfig = Field(default_factory=SleepConfig)
    thumbnails: ThumbnailConfig = Field(default_factory=ThumbnailConfig)
    localize: LocalizeConfig = Field(default_factory=LocalizeConfig)
    # Bible first, emotion second: study each passage before writing and check the script against it
    # afterwards (fyt/llm.py study_passage, check_faithfulness). A script that bends the passage fails.
    bible_first: bool = False
    # Per video: a storyboard, quote cards, a prayer and a community post (see growth.repurpose).
    repurpose: bool = True
    # Upload only after `fyt approve <job>`; strongly recommended (see README).
    require_review: bool = True
    jobs_dir: str = "jobs"
    seed_topics: list[str] = Field(default_factory=list)

    @property
    def jobs_path(self) -> Path:
        return (ROOT / self.jobs_dir).resolve()

    @property
    def target_words(self) -> int:
        return int(self.target_minutes * self.voice.words_per_minute)

    @property
    def target_seconds(self) -> float:
        return 50.0 if self.format == "short" else self.target_minutes * 60

    @property
    def is_sleep(self) -> bool:
        """A long calm video to fall asleep to (catalog length bucket "sleep")."""
        return self.format == "long" and self.target_minutes >= SLEEP_MINUTES


SLEEP_MINUTES = 18  # long videos this long or longer are sleep / prayer videos (catalog.length_bucket)


def sleep_config(cfg: Config) -> Config:
    """The channel config adjusted for a sleep video (see SleepConfig); other videos are unchanged."""
    if not cfg.is_sleep:
        return cfg
    s = cfg.sleep
    voice = cfg.voice.model_copy(update={
        "words_per_minute": s.words_per_minute, "gap_seconds": s.gap_seconds,
        "edge_rate": s.edge_rate, "kokoro_speed": s.kokoro_speed,
    })
    return cfg.model_copy(update={
        "voice": voice, "captions": s.captions, "letterbox": s.letterbox, "music_volume": s.music_volume,
    })


def load_config(path: str | Path | None = None) -> Config:
    load_dotenv()
    path = Path(path or os.environ.get("FYT_CONFIG", ROOT / "channel.yaml"))
    if not path.exists():
        return Config()
    return Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def secret(name: str) -> str | None:
    value = os.environ.get(name)
    return value or None
