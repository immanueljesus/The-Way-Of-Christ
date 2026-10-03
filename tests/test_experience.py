"""The emotional presentation: mood pacing, pauses, music that follows the journey, closing card."""

import wave

from fyt import media, tts
from fyt.config import Config, load_config
from fyt.models import MOODS, Script, ScriptScene, Word
from fyt.pipeline import load_script
from fyt.timeline import MUSIC_STEP, build_props, music_levels
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def journey_script() -> Script:
    return Script(
        title="God Has Not Forgotten You",
        description="D",
        tags=["a"],
        thumbnail_text="Not Forgotten",
        thumbnail_kicker="When You Feel...",
        thumbnail_query="q",
        scenes=[
            ScriptScene(narration="It's late.", type="broll", mood="struggle"),
            ScriptScene(narration="I will not forget you.", type="quote", mood="realization", pause_after=2.5, text="t", author="Isaiah 49:15"),
            ScriptScene(narration="Keep going.", type="broll", mood="strength"),
        ],
        sources=["Isaiah 49:15"],
    )


def test_demo_scripts_follow_the_journey_in_order():
    for fmt in ("short", "long"):
        s = load_script(FIXTURES / f"demo_script_{fmt}.json")
        moods = [MOODS.index(sc.mood) for sc in s.scenes]
        assert moods == sorted(moods), fmt
        assert s.scenes[0].mood == "struggle" and s.scenes[-1].mood == "strength"
        assert all(sc.broll_query for sc in s.scenes)


def test_pauses_come_from_the_scene_then_its_mood():
    cfg = Config()
    cfg.voice.mood_pacing = True
    s = journey_script()
    assert tts.scene_gaps(cfg, s.scenes) == [0.8, 2.5, 1.0]
    assert tts.scene_gaps(cfg, s.scenes, short=True) == [0.48, 1.5, 0.6]  # Shorts keep it tighter
    assert tts.scene_speed(cfg, "realization") < tts.scene_speed(cfg, "strength")
    cfg.voice.mood_pacing = False
    assert tts.scene_gaps(cfg, s.scenes)[0] == cfg.voice.gap_seconds and tts.scene_speed(cfg, "struggle") == 1.0


def test_join_clips_uses_each_scenes_pause(tmp_path):
    cfg = Config()
    clips = [tts.synthesize(cfg, "one two", tmp_path / f"{i}.wav", "silent") for i in range(3)]
    spans = tts.join_clips(clips, [0.5, 2.0, 9.0], tmp_path / "all.wav")
    assert abs(spans[1][0] - (spans[0][1] + 0.5)) < 1e-3
    assert abs(spans[2][0] - (spans[1][1] + 2.0)) < 1e-3
    with wave.open(str(tmp_path / "all.wav")) as w:
        assert abs(w.getnframes() / w.getframerate() - spans[2][1]) < 1e-3  # no pause after the last one


def test_edge_rate_combines_config_and_mood():
    assert tts._edge_rate("-8%", 1.0) == "-8%"
    assert tts._edge_rate("-8%", 0.9) == "-17%"
    assert tts._edge_rate("+0%", 1.03) == "+3%"


def test_master_voice_keeps_the_length(tmp_path):
    cfg = Config()
    cfg.voice.depth_semitones, cfg.voice.warmth, cfg.voice.room, cfg.voice.loudness = 1.5, True, 0.12, -16
    clip = tts.synthesize(cfg, "one two three four", tmp_path / "v.wav", "silent")
    tts.master_voice(cfg, clip.wav)
    with wave.open(str(clip.wav)) as w:
        assert abs(w.getnframes() / w.getframerate() - clip.duration) < 0.05


def test_music_ducks_under_the_voice_and_rises_with_the_journey():
    cfg = Config()
    cfg.music_dynamics, cfg.music_volume = True, 0.1
    spans = [(0.0, 4.0), (10.0, 14.0), (20.0, 24.0)]
    clip_words = [[Word(word="w", start=0.0, end=4.0)] for _ in spans]  # times within each clip
    props = build_props(cfg, journey_script(), spans, clip_words, {}, "voice.wav", "music.mp3")
    levels = props.music.levels
    at = lambda t: levels[int(t / MUSIC_STEP)]  # noqa: E731
    assert at(3.0) < at(7.0)  # ducked while speaking, swelling in the pause
    assert at(12.0) > at(2.5)  # realization sits higher than struggle
    assert at(22.0) > at(12.0)  # strength higher still
    assert levels[0] == 0 and levels[-1] <= 0.01  # fades in and out
    assert max(levels) <= 1.0


def test_music_levels_are_off_without_dynamics():
    props = build_props(Config(), journey_script(), [(0, 1), (2, 3), (4, 5)], [[], [], []], {}, "voice.wav", "m.mp3")
    assert props.music.levels == [] and props.brand is None and props.letterbox is False


def test_closing_card_and_letterbox_from_the_channel_config():
    cfg = load_config()
    cfg.format = "long"
    props = build_props(cfg, journey_script(), [(0, 1), (2, 3), (4, 5)], [[], [], []], {}, "voice.wav", None)
    assert props.brand.name == "The Way of Christ" and props.brand.tagline
    assert props.letterbox is True
    assert props.duration >= 5 + props.brand.seconds  # the ending holds long enough for the card


def test_mood_queries_give_every_scene_imagery():
    assert media.mood_queries("hope", 0)[0] != media.mood_queries("hope", 1)[0]
    assert media.mood_queries(None) == []
    assert all(media.MOOD_QUERIES[m] for m in MOODS)


def test_music_is_picked_to_suit_the_video(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "ROOT", tmp_path)
    (tmp_path / "music" / "cinematic").mkdir(parents=True)
    (tmp_path / "music" / "calm-piano-prayer.mp3").write_bytes(b"x")
    (tmp_path / "music" / "cinematic" / "rising.mp3").write_bytes(b"x")
    cfg = Config(music_dir="music")
    public = tmp_path / "public"
    public.mkdir()
    assert media.pick_music(cfg, public, category="prayer") == "music.mp3"
    assert (public / "music.mp3").exists()
    for _ in range(5):
        media.pick_music(cfg, public, category="motivational")
    # motivational videos only ever get the cinematic track
    assert all(media.pick_music(cfg, public, category="motivational") for _ in range(3))


def test_stock_clips_are_conformed_for_the_renderer(tmp_path):
    """Odd stock clips (25 fps, 1080x2048, shorter than the scene) broke Remotion with
    "No frame found at position"; they are re-encoded to 30 fps H.264 at the frame size, long enough."""
    import subprocess

    import imageio_ffmpeg

    from fyt import pipeline, qa
    from fyt.models import Media
    from fyt.store import Job

    job = Job.create(Config(jobs_dir=str(tmp_path), format="short"), "t")
    (job.public / "media").mkdir()
    src = job.public / "media" / "s1.mp4"
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         "testsrc=size=1080x2048:rate=25:duration=2", "-c:v", "libx264", str(src)],
        check=True,
    )
    (job.public / "media" / "broken.mp4").write_bytes(b"not a video")
    spans = [(0.0, 5.0), (6.0, 8.0)]
    media_in = {0: Media(src="media/s1.mp4", kind="video"), 1: Media(src="media/broken.mp4", kind="video")}
    out = pipeline.conform_clips(Config(format="short"), job, media_in, spans)
    assert out[0].src == "media/s1-cfr.mp4" and not src.exists()
    clip = job.public / out[0].src
    assert qa.media_duration(clip) >= 6.0 + pipeline.CROSSFADE_SECONDS
    info = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(clip)], capture_output=True, text=True).stderr
    assert "1080x1920" in info and "30 fps" in info
    assert 1 not in out  # unusable clip and no still: the scene falls back to its background


def test_free_music_library_is_used_when_there_are_no_own_tracks(tmp_path, monkeypatch):
    """GitHub Actions has no assets/music of its own: a credited CC BY track is downloaded,
    levelled, cut to the video and its credit handed to the description."""
    import subprocess

    import imageio_ffmpeg

    monkeypatch.setattr(media, "ROOT", tmp_path)
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "music.yaml").write_text(
        "credit: '\"{title}\" by Someone (CC BY 4.0)'\nbase_url: https://example.org/\n"
        "tracks:\n  - {title: Short Hope, mood: cinematic, seconds: 60}\n"
        "  - {title: Long Hope, mood: cinematic, seconds: 600}\n  - {title: Calm, mood: prayer, seconds: 600}\n",
        encoding="utf-8",
    )
    fetched = []

    def fake_download(url, dst):
        fetched.append(url)
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "sine=frequency=220:duration=20", "-f", "mp3", str(dst)], check=True)

    monkeypatch.setattr(media, "_download", fake_download)
    cfg = Config(music_dir="music")
    public = tmp_path / "public"
    public.mkdir()
    assert media.pick_music(cfg, public, category="motivational", seconds=300) == "music.m4a"
    assert fetched == ["https://example.org/Long%20Hope.mp3"]  # a track long enough for the video
    assert media.music_credit(public) == '"Long Hope" by Someone (CC BY 4.0)'
    media.pick_music(cfg, public, category="motivational", seconds=300)
    assert len(fetched) == 1  # downloaded once, then reused
    media.pick_music(cfg, public, category="prayer", seconds=30)
    assert fetched[-1].endswith("/Calm.mp3")


def test_an_online_voice_that_keeps_failing_falls_back(tmp_path, monkeypatch):
    cfg = Config()
    cfg.voice.provider, cfg.voice.fallback_provider = "edge", "silent"

    def down(cfg, text, out, speed=1.0):
        raise ConnectionError("edge is down")

    monkeypatch.setitem(tts.PROVIDERS, "edge", down)
    monkeypatch.setattr(tts.time, "sleep", lambda s: None)
    clip = tts.synthesize(cfg, "Still voiced.", tmp_path / "a.wav")
    assert clip.duration > 0 and [w.word for w in clip.words] == ["Still", "voiced."]
