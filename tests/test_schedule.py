import random
from datetime import datetime, timezone

import pytest

from fyt import pipeline, schedule, youtube
from fyt.config import Config
from fyt.store import Job, Uploads

MONDAY = datetime(2026, 9, 28, 19, 0, tzinfo=timezone.utc)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(youtube, "authorised", lambda: True)
    monkeypatch.setattr(schedule, "utcnow", lambda: MONDAY)
    monkeypatch.setattr(youtube, "recent_uploads", lambda: [])
    c = Config(jobs_dir=str(tmp_path), require_review=False)
    c.youtube.publish_jitter_minutes = 90
    c.growth.bonus_shorts_per_day = 0  # tested separately
    c.growth.bonus_longs_per_week = 0
    return c


class FakeChannel:
    """Stands in for making and uploading videos."""

    def __init__(self, monkeypatch, fail_make=0, fail_upload=0, quota_after=None):
        self.made, self.uploaded = [], []
        self.fail_make, self.fail_upload, self.quota_after = fail_make, fail_upload, quota_after
        monkeypatch.setattr(pipeline, "make_next", self.make_next)
        monkeypatch.setattr(pipeline, "upload_job", self.upload_job)

    def make_next(self, cfg, topics, category=None):
        if self.fail_make:
            self.fail_make -= 1
            return None
        job = Job.create(cfg, f"topic {len(self.made)}")
        job.file("video.mp4").write_bytes(b"x")
        job.file("script.json").write_text("{}", encoding="utf-8")
        job.update(status="approved")
        self.made.append(cfg.format)
        return job

    def upload_job(self, cfg, job, force=False, publish_at=None):
        if self.quota_after is not None and len(self.uploaded) >= self.quota_after:
            raise RuntimeError("quotaExceeded: The request cannot be completed because you have exceeded your quota.")
        if self.fail_upload:
            self.fail_upload -= 1
            raise RuntimeError("connection reset")
        self.uploaded.append((job.meta["format"], publish_at))
        job.update(status="uploaded", youtube_id=f"vid{len(self.uploaded)}")
        return f"vid{len(self.uploaded)}"


def test_slots_cover_the_buffer_and_the_weekly_long_video(cfg):
    slots = schedule.upcoming_slots(cfg, MONDAY)
    assert [(s.at.strftime("%a %H:%M"), s.kind) for s in slots] == [
        ("Mon 22:00", "short"),
        ("Tue 14:00", "short"),
        ("Tue 22:00", "short"),
        ("Wed 14:00", "short"),
    ]
    thursday = datetime(2026, 10, 1, 19, 0, tzinfo=timezone.utc)
    kinds = [(s.at.strftime("%a %H:%M"), s.kind) for s in schedule.upcoming_slots(cfg, thursday)]
    assert ("Sat 16:00", "long") in kinds  # made up to 3 days ahead


def test_fill_schedules_each_empty_slot_once(cfg, monkeypatch):
    ch = FakeChannel(monkeypatch)
    assert schedule.fill(cfg, now=MONDAY, rng=random.Random(1)) == 4
    assert ch.made == ["short"] * 4
    for (_, at), slot in zip(ch.uploaded, schedule.upcoming_slots(cfg, MONDAY)):
        assert slot.at <= at <= slot.at.replace(minute=30, hour=slot.at.hour + 1)  # random minute in the window
    assert schedule.fill(cfg, now=MONDAY) == 0  # nothing left to do
    assert not schedule.needed(cfg, MONDAY)
    _, soon = schedule.report(cfg, MONDAY)
    assert soon == []


def test_a_failed_video_is_retried_with_another_topic(cfg, monkeypatch):
    ch = FakeChannel(monkeypatch, fail_make=2)
    # Two videos fail; the later slots still get theirs, and the next run fills the rest.
    assert schedule.fill(cfg, now=MONDAY) == 2
    assert schedule.fill(cfg, now=MONDAY) == 2


def test_failed_upload_is_kept_and_uploaded_by_the_next_run(cfg, monkeypatch):
    ch = FakeChannel(monkeypatch, fail_upload=1)
    schedule.fill(cfg, now=MONDAY)
    assert len(ch.made) == 4 and len(ch.uploaded) == 3
    assert len(schedule.pending_jobs(cfg)) == 1
    ch.made.clear()
    assert schedule.fill(cfg, now=MONDAY) == 1
    assert ch.made == []  # uploaded the kept video instead of making a new one
    assert schedule.pending_jobs(cfg) == []


def test_daily_quota_is_respected(cfg, monkeypatch):
    cfg.schedule.buffer_days = 4  # more slots than one day's quota
    ch = FakeChannel(monkeypatch)
    assert schedule.fill(cfg, now=MONDAY) == 4
    assert len(ch.made) == 4
    assert schedule.uploads_left_today(cfg, MONDAY) == 0
    assert schedule.needed(cfg, MONDAY) is False


def test_quota_error_stops_the_run_and_keeps_the_video(cfg, monkeypatch):
    ch = FakeChannel(monkeypatch, quota_after=1)
    schedule.fill(cfg, now=MONDAY)
    assert len(ch.made) == 2  # stopped making after the quota error
    assert len(schedule.pending_jobs(cfg)) == 1


def test_no_time_for_a_long_video_still_makes_shorts(cfg, monkeypatch):
    friday = datetime(2026, 10, 2, 6, 0, tzinfo=timezone.utc)
    ch = FakeChannel(monkeypatch)
    ticks = iter([0] + [60 * 60] * 50)  # an hour has passed at the first check
    schedule.fill(cfg, now=friday, clock=lambda: next(ticks))
    assert "long" not in ch.made and "short" in ch.made


def test_check_flags_an_empty_slot_in_the_next_day(cfg):
    _, soon = schedule.report(cfg, MONDAY)
    assert [s.at.strftime("%a %H:%M") for s in soon] == ["Mon 22:00", "Tue 14:00"]


def test_one_off_uploads_count_toward_the_quota(cfg):
    Uploads(cfg).record("short", "job", "vid", None)
    assert schedule.uploads_left_today(cfg, datetime.now(timezone.utc)) == 3


def test_a_lost_state_is_recovered_from_the_channel(cfg, monkeypatch):
    """A fresh state.db (e.g. the cache was reset) must not double-book slots already scheduled on YouTube."""
    desc = 'Intro.\n\nBased on the Wikipedia article "Vril" (https://en.wikipedia.org/wiki/Vril), licensed CC BY-SA 4.0.'
    monkeypatch.setattr(
        youtube,
        "recent_uploads",
        lambda: [
            {"id": "old1", "publish_at": "2026-09-28T22:40:00Z", "uploaded": "2026-09-28T19:30:00Z", "description": desc},
            {"id": "old2", "publish_at": "2026-09-29T14:16:00Z", "uploaded": "2026-09-28T19:40:00Z", "description": ""},
            {"id": "live", "publish_at": None, "uploaded": "2026-09-27T14:00:00Z", "description": ""},
        ],
    )
    ch = FakeChannel(monkeypatch)
    cfg.youtube.publish_jitter_minutes = 30  # keep each publish inside its hour (90 made this test flaky)
    assert schedule.fill(cfg, now=MONDAY) == 2  # Mon 22:00 and Tue 14:00 were already on the channel
    assert [at.strftime("%a %H") for _, at in ch.uploaded] == ["Tue 22", "Wed 14"]
    from fyt.store import Topics

    assert ("wiki:Vril", "done") in [(t, s) for _, t, s, _ in Topics(cfg).all()]
    assert schedule.uploads_left_today(cfg, MONDAY) == 0  # the two made Monday count toward the quota, plus two now


def test_slots_in_a_time_zone_follow_daylight_saving(cfg):
    cfg.schedule.timezone = "America/New_York"
    cfg.schedule.short_slots = ["19:00"]
    cfg.schedule.long_weekday = None
    summer = schedule.upcoming_slots(cfg, datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))
    winter = schedule.upcoming_slots(cfg, datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc))
    assert summer[0].at.hour == 23  # 7 pm EDT
    assert winter[0].at.hour == 0  # 7 pm EST is midnight UTC
