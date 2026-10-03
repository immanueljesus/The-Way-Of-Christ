import shutil
import wave
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fyt import qa, tts
from fyt.config import Config
from fyt.models import Script, ScriptScene, Word
from fyt.pipeline import load_script
from fyt.timeline import build_props, to_srt
from fyt.youtube import build_body

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def script(n=3) -> Script:
    return Script(
        title="T",
        description="D",
        tags=["a"],
        thumbnail_text="X",
        thumbnail_kicker="K",
        thumbnail_query="q",
        scenes=[ScriptScene(narration=f"scene {i} words here.", type="statement", text="t") for i in range(n)],
        sources=["https://example.com"],
    )


def test_fixtures_are_valid_and_pass_qa():
    for fmt in ("long", "short"):
        s = load_script(FIXTURES / f"demo_script_{fmt}.json")
        assert qa.check_script(Config(format=fmt), s) == []


def test_words_from_chars_groups_on_whitespace():
    chars = list("Hi there.")
    starts = [i * 0.1 for i in range(len(chars))]
    ends = [s + 0.1 for s in starts]
    words = tts.words_from_chars(chars, starts, ends)
    assert [w.word for w in words] == ["Hi", "there."]
    assert words[0].start == 0.0 and abs(words[0].end - 0.2) < 1e-9
    assert abs(words[1].start - 0.3) < 1e-9


def test_join_clips_offsets_and_gap(tmp_path):
    cfg = Config()
    clips = [tts.synthesize(cfg, "one two three", tmp_path / f"{i}.wav", "silent") for i in range(2)]
    spans = tts.join_clips(clips, 0.5, tmp_path / "all.wav")
    assert spans[0][0] == 0.0
    assert abs(spans[1][0] - (clips[0].duration + 0.5)) < 1e-3
    with wave.open(str(tmp_path / "all.wav")) as w:
        total = w.getnframes() / w.getframerate()
    assert abs(total - spans[1][1]) < 1e-3


@pytest.mark.skipif(not (shutil.which("espeak-ng") or shutil.which("espeak")), reason="espeak-ng not installed")
def test_espeak_timings_fit_the_audio(tmp_path):
    clip = tts.synthesize(Config(), "Time beats timing, every time.", tmp_path / "e.wav", "espeak")
    assert clip.duration > 0.5
    assert [w.word for w in clip.words] == ["Time", "beats", "timing,", "every", "time."]
    assert clip.words[-1].end <= clip.duration + 1e-3


def test_build_props_covers_timeline_and_shifts_captions():
    s = script(3)
    spans = [(0.0, 2.0), (2.5, 4.0), (4.5, 7.0)]
    words = [[Word(word="w", start=0.1, end=0.3)] for _ in spans]
    props = build_props(Config(), s, spans, words, {}, "voice.wav", None)
    # Scenes are contiguous from 0 to the end, with a tail after the voice.
    assert props.scenes[0].start == 0.0
    for a, b in zip(props.scenes, props.scenes[1:]):
        assert a.end == b.start
    assert props.scenes[-1].end == props.duration > 7.0
    assert [c.start for c in props.captions] == [0.1, 2.6, 4.6]


def test_srt_format():
    srt = to_srt([Word(word="Hello", start=0, end=0.5), Word(word="world.", start=0.5, end=1.25)])
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,250\nHello world.")


def test_scheduled_upload_forces_private_and_shorts_tag():
    cfg = Config(format="short")
    cfg.youtube.privacy = "public"
    cfg.youtube.publish_delay_hours = 2
    body = build_body(cfg, script(), now=datetime(2026, 1, 1, 10, tzinfo=timezone.utc))
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == "2026-01-01T12:00:00Z"
    assert body["status"]["containsSyntheticMedia"] is False  # only for realistic synthetic content
    cfg.youtube.contains_synthetic_media = True
    assert build_body(cfg, script(), now=datetime(2026, 1, 1, 10, tzinfo=timezone.utc))["status"]["containsSyntheticMedia"] is True
    assert "#Shorts" in body["snippet"]["description"]
    assert "https://example.com" in body["snippet"]["description"]


def test_qa_catches_bad_scripts():
    s = script(1)
    s.scenes[0].type = "bars"
    s.title = "x" * 120
    problems = qa.check_script(Config(), s)
    assert any("title" in p for p in problems)
    assert any("bar chart" in p for p in problems)


def test_random_publish_time_stays_inside_the_window():
    import random

    cfg = Config(format="short")
    cfg.youtube.publish_jitter_minutes = 90
    now = datetime(2026, 1, 1, 14, tzinfo=timezone.utc)
    rng = random.Random(1)
    times = [build_body(cfg, script(), now=now, rng=rng)["status"]["publishAt"] for _ in range(50)]
    assert len(set(times)) > 10  # not the same minute every day
    assert all("2026-01-01T14:15:00Z" <= t <= "2026-01-01T15:30:00Z" for t in times)
    cfg.youtube.publish_jitter_minutes = 0
    assert "publishAt" not in build_body(cfg, script(), now=now)["status"]  # off by default


def test_chapter_list_uses_scene_start_times():
    from fyt.models import Chapter
    from fyt.pipeline import chapter_list

    s = script(6).model_copy(update={"chapters": [Chapter(title="Start", scene=0), Chapter(title="Middle", scene=2), Chapter(title="End", scene=4)]})
    spans = [(0, 20), (20.5, 40), (40.5, 75), (75.5, 100), (100.5, 130), (130.5, 150)]
    assert chapter_list(s, spans) == "Chapters:\n0:00 Start\n0:40 Middle\n1:40 End"
    assert chapter_list(script(6), spans) == ""  # Shorts have no chapters
    short_gaps = [(0, 2), (2.5, 4), (4.5, 6), (6.5, 8), (8.5, 10), (10.5, 12)]
    assert chapter_list(s, short_gaps) == ""  # YouTube needs chapters of 10s or more
