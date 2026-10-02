import json
import random
from datetime import datetime, timedelta, timezone

import pytest

from fyt import growth, llm, pipeline, schedule, wiki, youtube
from fyt.config import Config
from fyt.models import Chapter, Script, ScriptScene
from fyt.store import Job, Topics, Uploads

NOW = datetime(2026, 9, 29, 13, 0, tzinfo=timezone.utc)


def script(n=6, chapters=None) -> Script:
    return Script(
        title="Old title",
        description="A story about molasses.\n\nKey points.\n\nBased on the Wikipedia article \"X\" (url), licensed CC BY-SA 4.0.",
        tags=["a"],
        thumbnail_text="Old",
        thumbnail_kicker="K",
        thumbnail_query="q",
        scenes=[
            ScriptScene(narration=f"Scene {i} " + "word " * 30, type="statement", text="t", image=1, broll_query="tank")
            for i in range(n)
        ],
        sources=["https://en.wikipedia.org/wiki/X"],
        chapters=chapters,
    )


def answer(monkeypatch, *replies):
    """Make llm.structured return these objects in turn and record what it was asked."""
    calls = []

    def structured(cfg, system, user, schema, max_tokens=3000):
        calls.append((system, user, schema))
        r = replies[len(calls) - 1]
        if isinstance(r, Exception):
            raise r
        return schema.model_validate(r)

    monkeypatch.setattr(llm, "structured", structured)
    return calls


def test_polish_sharpens_title_hook_and_adds_a_loop_line_to_shorts(monkeypatch):
    cfg = Config(format="short")
    cfg.growth.series = ["Weird History", "Strange Science"]
    calls = answer(
        monkeypatch,
        {
            "titles": ["a", "b"],
            "best_title": "The Flood Made of Molasses",
            "thumbnail_text": "15 ft wave",
            "hook": "In 1919 a wave of molasses swept through Boston.",
            "loop_line": "And it all began with one tank.",
            "series": "Weird History",
        },
    )
    s = growth.polish(cfg, script())
    assert s.title == "The Flood Made of Molasses" and s.thumbnail_text == "15 ft wave"
    assert s.scenes[0].narration.startswith("In 1919")
    assert s.scenes[-1].narration.endswith("And it all began with one tank.")
    assert s.series == "Weird History"
    assert "Weird History, Strange Science" in calls[0][0]


def test_polish_ignores_a_made_up_series_and_long_hooks(monkeypatch):
    cfg = Config(format="long")
    answer(monkeypatch, {"titles": [], "best_title": "x", "thumbnail_text": "", "hook": "word " * 60, "series": "Other"})
    s = growth.polish(cfg, script())
    assert s.title == "Old title"  # too short to be a real title
    assert s.scenes[0].narration.startswith("Scene 0") and s.series is None


def test_a_failed_polish_keeps_the_video(monkeypatch, tmp_path):
    cfg = Config(jobs_dir=str(tmp_path))
    answer(monkeypatch, RuntimeError("groq down"))
    job = Job.create(cfg, "t")
    monkeypatch.setattr(pipeline.qa, "check_script", lambda cfg, s: ["stop here"])
    with pytest.raises(RuntimeError, match="stop here"):
        pipeline._make(cfg, job, "t", script(), None, polish=True)
    assert json.loads(job.file("script.json").read_text(encoding="utf-8"))["title"] == "Old title"


def test_rank_prefers_fit_then_readers():
    fits = {"Molasses flood": 9, "Bruno Mars": 2, "Tanganyika laughter epidemic": 9, "Dull": 6}
    views = {"Molasses flood": 50_000, "Bruno Mars": 900_000, "Tanganyika laughter epidemic": 5_000, "Dull": 10}
    assert growth.rank(fits, views, 6) == ["Molasses flood", "Tanganyika laughter epidemic", "Dull"]


def test_pick_topics_ranks_candidates_and_falls_back_to_random(monkeypatch):
    cfg = Config()
    monkeypatch.setattr(wiki, "candidates", lambda cfg: ["Bruno Mars", "Molasses flood", "Stub"])
    monkeypatch.setattr(growth, "page_lengths", lambda cfg, t: {"Bruno Mars": 90000, "Molasses flood": 20000, "Stub": 100})
    monkeypatch.setattr(growth, "pageviews", lambda cfg, t: {"Bruno Mars": 900000, "Molasses flood": 40000}[t])
    monkeypatch.setattr(wiki, "fetch_article", lambda cfg, t: wiki.Article(t, "u", "x" * 5000))
    calls = answer(monkeypatch, {"scores": [{"title": "Bruno Mars", "fit": 1}, {"title": "Molasses flood", "fit": 9}]})
    assert growth.pick_topics(cfg, 2, set()) == ["Molasses flood"]
    assert "Stub" not in calls[0][1]  # too short to be offered

    answer(monkeypatch, RuntimeError("down"))
    monkeypatch.setattr(wiki, "pick_articles", lambda cfg, n, used, rng=None: ["Random one"])
    assert growth.pick_topics(cfg, 1, set()) == ["Random one"]


def test_pick_trending_skips_off_niche_and_used(monkeypatch):
    cfg = Config()
    monkeypatch.setattr(
        growth, "trending_candidates", lambda cfg, day=None: [("Bruno Mars", 500000), ("Great Emu War", 90000), ("Used", 1)]
    )
    monkeypatch.setattr(wiki, "fetch_article", lambda cfg, t: wiki.Article(t, "u", "x" * 5000))
    calls = answer(monkeypatch, {"scores": [{"title": "Bruno Mars", "fit": 2}, {"title": "Great Emu War", "fit": 9}]})
    assert growth.pick_trending(cfg, {wiki.topic_for("Used")}, 7, 3000) == "Great Emu War"
    assert "Used" not in calls[0][1]
    answer(monkeypatch, {"scores": [{"title": "Bruno Mars", "fit": 3}]})
    assert growth.pick_trending(cfg, set(), 7, 3000) is None


def test_cuts_come_from_the_best_chapters_and_link_the_full_video(monkeypatch):
    cfg = Config()
    chapters = [Chapter(title="Start", scene=0), Chapter(title="The wave", scene=2), Chapter(title="Aftermath", scene=4)]
    answer(monkeypatch, {"chapters": [2, 9, 2, 3]})
    cuts = growth.cut_scripts(cfg, script(6, chapters), "LONG123", 2)
    assert [c.title for c in cuts] == ["The wave", "Aftermath"]
    first = cuts[0]
    assert first.description.startswith("Full video: https://youtu.be/LONG123")
    assert "CC BY-SA" in first.description
    assert first.scenes[0].type == "title" and first.scenes[0].heading == "The wave"
    assert all(s.image is None for s in first.scenes)
    assert sum(len(s.narration.split()) for s in first.scenes) <= growth.CUT_WORDS + 10
    assert first.chapters is None


def test_long_upload_queues_cuts_that_fill_the_next_short_slots(monkeypatch, tmp_path):
    cfg = Config(jobs_dir=str(tmp_path), format="long")
    monkeypatch.setattr(growth, "cut_scripts", lambda cfg, s, vid, n: [script(2), script(3)])
    pipeline.queue_cuts(cfg, script(), "LONG1")
    topics = Topics(cfg)
    topics.add(["wiki:Regular"])
    short = cfg.model_copy(update={"format": "short"})
    first = pipeline.next_topic(short, topics)
    assert first[1] == "cut:LONG1-1"
    made = []
    monkeypatch.setattr(pipeline, "make_video", lambda cfg, t, script=None, polish=None: made.append((t, polish, script)))
    pipeline.make_topic(short, first[1])
    assert made[0][1] is True and len(made[0][2].scenes) == 2
    assert not (tmp_path / "cuts" / "LONG1-1.json").exists()


def test_can_manage_reads_the_token_scopes(monkeypatch, tmp_path):
    monkeypatch.setattr(youtube, "TOKEN", tmp_path / "token.json")
    monkeypatch.setenv("YOUTUBE_TOKEN_JSON", json.dumps({"scopes": ["https://www.googleapis.com/auth/youtube.upload"]}))
    assert youtube.can_manage() is False
    monkeypatch.setenv("YOUTUBE_TOKEN_JSON", json.dumps({"scopes": [youtube.FULL_SCOPE]}))
    assert youtube.can_manage() is True
    monkeypatch.setenv("YOUTUBE_TOKEN_JSON", "{}")
    assert youtube.can_manage() is False


# --- Bonus videos ---


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "authorised", lambda: True)
    monkeypatch.setattr(youtube, "recent_uploads", lambda: [])
    monkeypatch.setattr(schedule, "utcnow", lambda: NOW)
    c = Config(jobs_dir=str(tmp_path), require_review=False)
    c.schedule.short_slots = []  # only bonus videos in these tests
    c.schedule.long_weekday = None
    return c


def fake_channel(monkeypatch, trending=("Great Emu War",)):
    made, uploaded = [], []
    picks = list(trending)

    def make_video(cfg, topic, script=None, voice=None, polish=None):
        job = Job.create(cfg, topic)
        job.update(status="approved")
        made.append((cfg.format, topic))
        return job

    def upload_job(cfg, job, force=False, publish_at=None):
        uploaded.append((job.meta["format"], publish_at))
        return f"v{len(uploaded)}"

    monkeypatch.setattr(pipeline, "make_video", make_video)
    monkeypatch.setattr(pipeline, "upload_job", upload_job)
    monkeypatch.setattr(growth, "pick_trending", lambda cfg, used, fit, chars, day=None: picks.pop(0) if picks else None)
    return made, uploaded


def test_one_bonus_short_a_day_published_soon(cfg, monkeypatch):
    made, uploaded = fake_channel(monkeypatch)
    cfg.growth.bonus_longs_per_week = 0
    assert schedule.fill(cfg, now=NOW, rng=random.Random(0)) == 1
    assert made == [("short", "wiki:Great Emu War")]
    assert NOW + timedelta(minutes=15) <= uploaded[0][1] <= NOW + timedelta(minutes=90)
    assert not schedule.bonus_due(cfg, "short", NOW + timedelta(hours=12))
    assert schedule.bonus_due(cfg, "short", NOW + timedelta(hours=25))


def test_bonus_long_at_most_weekly(cfg, monkeypatch):
    cfg.growth.bonus_shorts_per_day = 0
    made, _ = fake_channel(monkeypatch, trending=("Great Emu War", "Another"))
    schedule.fill(cfg, now=NOW)
    assert made == [("long", "wiki:Great Emu War")]
    assert not schedule.bonus_due(cfg, "long", NOW + timedelta(days=6))
    assert schedule.bonus_due(cfg, "long", NOW + timedelta(days=7, minutes=1))


def test_no_fitting_trend_waits_six_hours_before_looking_again(cfg, monkeypatch):
    cfg.growth.bonus_longs_per_week = 0
    made, _ = fake_channel(monkeypatch, trending=())
    schedule.fill(cfg, now=NOW)
    assert made == []
    assert not schedule.bonus_due(cfg, "short", NOW + timedelta(hours=5))
    assert schedule.bonus_due(cfg, "short", NOW + timedelta(hours=7))


def test_bonus_waits_for_the_schedule_and_the_quota(cfg, monkeypatch):
    made, _ = fake_channel(monkeypatch)
    for i in range(4):
        Uploads(cfg).record("short", f"j{i}", f"v{i}", None, at=NOW.isoformat())
    assert schedule.fill(cfg, now=NOW) == 0 and made == []
    assert schedule.needed(cfg, NOW) is False


def test_trending_candidates_read_most_read_and_anniversaries(monkeypatch):
    body = {
        "mostread": {"articles": [{"title": "Great_Emu_War", "views": 90000}, {"title": "Main_Page", "views": 1}]},
        "onthisday": [{"text": "x", "pages": [{"title": "Boston_Molasses_Disaster", "titles": {"normalized": "Boston Molasses Disaster"}}]}],
    }

    class R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return body

    seen = []
    monkeypatch.setattr(growth.requests, "get", lambda url, headers, timeout: seen.append(url) or R())
    got = growth.trending_candidates(Config(), datetime(2026, 9, 29).date())
    assert got == [("Great Emu War", 90000), ("Boston Molasses Disaster", 0)]
    assert seen == ["https://en.wikipedia.org/api/rest_v1/feed/featured/2026/09/29"]
