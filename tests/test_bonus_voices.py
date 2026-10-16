"""Bonus videos (follow-ups to winners, rising topics) within the free budget, and the voice cast."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from fyt import bonus, catalog, insights, llm, pipeline, schedule, scripture, tts
from fyt.config import Config, load_config
from fyt.store import Job, Uploads

NOW = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def cfg(tmp_path):
    c = load_config().model_copy(deep=True)
    c.jobs_dir = str(tmp_path)
    c.require_review = False
    return c


def fake_idea(monkeypatch, refs=("John 11:35",)):
    """The model plans a bonus idea; its passages 'exist' without calling bible-api."""
    asked = []

    def structured(cfg, system, user, schema, max_tokens=0):
        asked.append(system + user)
        return bonus.BonusIdea(title=f"Jesus Wept, Part {len(asked)}", angle="He stood at the grave and cried.",
                               scriptures=list(refs), arc="story", emotion="grief")

    monkeypatch.setattr(llm, "structured", structured)
    monkeypatch.setattr(scripture, "fetch_all", lambda cfg, rs: {r: object() for r in rs if r != "Hezekiah 1:1"})
    return asked


# --- Winners -------------------------------------------------------------------------


def test_a_winning_short_gets_a_follow_up_short_and_a_long_version(cfg, monkeypatch):
    Uploads(cfg).set_note(insights.NOTE, json.dumps({"updated": NOW.isoformat(), "winners": [
        {"id": "WIN1", "title": "The Cupbearer Forgot Joseph", "lift": 1.6, "topic": "idea:when-you-feel-forgotten", "category": "motivation"},
        {"id": "MEH", "title": "Fine", "lift": 1.21, "topic": None, "category": "prayer"},
    ]}))
    monkeypatch.setattr(insights, "refresh", lambda cfg, now: None)
    cfg.bonus.trends = False  # tested below
    asked = fake_idea(monkeypatch)
    assert bonus.scan(cfg, NOW) == 2
    items = bonus.queue(cfg)
    assert [i["kind"] for i in items] == ["short", "long"] and items[1]["minutes"] == cfg.bonus.long_minutes
    assert "Genesis 40:23" in asked[0] and "SAME passage" in asked[0]  # built on the winner's own passage
    ideas = {i.topic: i for i in catalog.load(cfg)}
    short = ideas[items[0]["topic"]]
    assert short.id.startswith("bonus-") and short.series == "Hard Seasons" and short.scriptures == ["John 11:35"]
    assert short.formats == ["short"] and ideas[items[1]["topic"]].formats == ["medium", "long"]
    # Bonus ideas never leak into the regular schedule's picks.
    assert all(not catalog.pick(cfg.model_copy(update={"format": "short"}), set(), category=c).id.startswith("bonus-")
               for c in ("motivation", "jesus"))
    assert bonus.scan(cfg, NOW) == 0  # once a day
    assert bonus.scan(cfg, NOW, force=True) == 0  # and never twice for the same winner


def test_ideas_without_real_scripture_are_dropped(cfg, monkeypatch):
    fake_idea(monkeypatch, refs=("Hezekiah 1:1",))
    assert bonus.write_idea(cfg, "task", "context", "short", "wisdom") is None


# --- Rising topics -------------------------------------------------------------------


def test_spike_compares_the_last_two_days_with_the_month():
    assert bonus.spike([100] * 28 + [300, 250]) == 2.75
    assert bonus.spike([100] * 5) == 0.0


def test_rising_article_uses_an_unused_catalog_idea_first(cfg, monkeypatch):
    cfg.bonus.watch_articles = ["Book of Jonah"]
    views = {"Joseph (Genesis)": [1000] * 28 + [3500, 3000]}
    monkeypatch.setattr(bonus, "daily_views", lambda cfg, title, today=None: views.get(title, [1000] * 30))
    monkeypatch.setattr(llm, "structured", lambda *a, **k: pytest.fail("no model call needed"))
    assert "Book of Jonah" in bonus.watchlist(cfg) and "Joseph (Genesis)" in bonus.watchlist(cfg)
    assert bonus.queue_trends(cfg, NOW, set(), set()) == 1
    (item,) = bonus.queue(cfg)
    idea = catalog.get(cfg, item["topic"])
    assert idea.wiki == "Joseph (Genesis)" and "short" in idea.formats and "x3.25" in item["reason"]


def test_new_search_suggestions_count_only_after_a_baseline(cfg, monkeypatch):
    cfg.bonus.suggest_seeds = ["prayer for"]
    today = ["prayer for healing", "prayer for peace"]
    monkeypatch.setattr(bonus, "suggestions", lambda seed: today)
    assert bonus.new_suggestions(cfg, NOW) == []  # the first day sets the baseline
    today = ["prayer for healing", "prayer for the storm tonight"]
    assert bonus.new_suggestions(cfg, NOW + timedelta(days=1)) == ["prayer for the storm tonight"]


def test_a_rising_search_that_fits_becomes_a_bonus_short(cfg, monkeypatch):
    from fyt import growth

    monkeypatch.setattr(bonus, "rising_articles", lambda cfg, now: [])
    monkeypatch.setattr(bonus, "new_suggestions", lambda cfg, now: ["prayer for the storm tonight", "celebrity gossip"])
    monkeypatch.setattr(growth, "score_topics", lambda cfg, c, extra="": {"prayer for the storm tonight": 9, "celebrity gossip": 0})
    fake_idea(monkeypatch)
    assert bonus.queue_trends(cfg, NOW, set(), set()) == 1
    assert bonus.queue(cfg)[0]["reason"] == "rising search: prayer for the storm tonight"


# --- Budget ----------------------------------------------------------------------------


def test_minutes_budget_follows_the_measured_pace(cfg):
    mid = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
    bonus.record_minutes(cfg, mid, 930)  # 62 a day so far: ~1,920 projected for October
    assert not bonus.minutes_allow(cfg, mid, 15)
    other = cfg.model_copy(update={"jobs_dir": cfg.jobs_dir + "-2"})
    bonus.record_minutes(other, mid, 750)  # 50 a day: ~1,550 projected, room for bonuses
    assert bonus.minutes_allow(other, mid, 15) and not bonus.minutes_allow(other, mid, 400)
    early = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    assert not bonus.minutes_allow(other, early, 15)  # no pace yet: assume a busy month


def test_weekly_and_monthly_caps(cfg):
    for _ in range(cfg.bonus.shorts_per_week):
        Uploads(cfg).record("bonus-short", "j", "v", None, at=(NOW - timedelta(days=2)).isoformat())
    assert not bonus.caps_allow(cfg, "short", NOW)
    assert bonus.caps_allow(cfg, "short", NOW + timedelta(days=6))
    assert bonus.caps_allow(cfg, "long", NOW)


def test_run_makes_queued_bonuses_only_within_budget(cfg, monkeypatch):
    bonus.enqueue(cfg, NOW, "idea:when-you-feel-forgotten", "short", "test")
    made, uploaded = [], []

    def make_topic(vcfg, topic):
        job = Job.create(vcfg, topic)
        job.update(status="approved")
        made.append((vcfg.format, topic))
        return job

    monkeypatch.setattr(pipeline, "make_topic", make_topic)
    monkeypatch.setattr(schedule, "_upload", lambda cfg, job, slot, rng, now, kind=None: uploaded.append(kind) or True)
    monkeypatch.setattr(bonus, "minutes_allow", lambda cfg, now, cost: False)
    assert bonus.run(cfg, NOW, None, lambda: 0.0, 0.0, budget=2) == 0 and len(bonus.queue(cfg)) == 1  # waits
    assert schedule.needed(cfg, NOW) in (True, False)  # still answers while a bonus waits
    monkeypatch.setattr(bonus, "minutes_allow", lambda cfg, now, cost: True)
    assert bonus.run(cfg, NOW, None, lambda: 0.0, 0.0, budget=0) == 0  # no quota left today
    assert bonus.run(cfg, NOW, None, lambda: 0.0, 0.0, budget=2) == 1
    assert made == [("short", "idea:when-you-feel-forgotten")] and uploaded == ["bonus-short"] and bonus.queue(cfg) == []
    bonus.enqueue(cfg, NOW, "idea:x", "short", "old")
    assert bonus.run(cfg, NOW + timedelta(days=cfg.bonus.follow_up_days + 1), None, lambda: 0.0, 0.0, 2) == 0  # expired


def test_fill_records_its_runner_minutes(cfg):
    bonus.record_minutes(cfg, NOW, 12.5)
    bonus.record_minutes(cfg, NOW, 10)
    assert Uploads(cfg).note("minutes-2026-10") == "22.5"
    assert "22 of 2000" in bonus.report(cfg, NOW)


# --- Voices ------------------------------------------------------------------------------


def test_each_series_keeps_its_narrator():
    cfg = load_config()
    short, long = cfg.model_copy(update={"format": "short"}), cfg.model_copy(update={"format": "long", "target_minutes": 8})
    sleep = cfg.model_copy(update={"format": "long", "target_minutes": 30})
    assert tts.cast_voice(short, None, "motivation") == "en-US-EmmaMultilingualNeural"
    assert tts.cast_voice(long, None, "motivation") == cfg.voice.edge_voice  # Emma reads encouragement Shorts only
    assert tts.cast_voice(short, "Prayers", "prayer") == tts.cast_voice(sleep, None, "bible_story") == "en-US-AvaMultilingualNeural"
    assert tts.cast_voice(long, "Lessons From...", "bible_story") == "en-US-BrianMultilingualNeural"
    assert tts.cast_voice(short, None, "jesus") == "en-US-AndrewMultilingualNeural"
    assert tts.cast_voice(Config(), "Anything", "jesus") == Config().voice.edge_voice  # no cast: one voice
    assert tts.is_female("en-US-AvaMultilingualNeural") and not tts.is_female("en-US-BrianMultilingualNeural")


def test_backup_voice_keeps_the_narrators_gender_and_is_counted(monkeypatch, tmp_path):
    cfg = tts.with_voice(load_config(), "en-US-AvaMultilingualNeural")
    used = []
    monkeypatch.setitem(tts.PROVIDERS, "edge", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("403")))
    monkeypatch.setitem(tts.PROVIDERS, "kokoro", lambda cfg, text, out, speed=1.0: used.append(cfg.voice.kokoro_voice) or "clip")
    monkeypatch.setattr(tts.time, "sleep", lambda s: None)
    tts.FALLBACKS.clear()
    assert tts.synthesize(cfg, "Peace.", Path(tmp_path / "a.wav"), "edge") == "clip"
    assert used == [cfg.voice.kokoro_female] and len(tts.FALLBACKS) == 1
