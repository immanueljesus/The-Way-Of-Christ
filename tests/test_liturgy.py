"""The Christian calendar engine: dates, campaigns and how they enter the schedule."""

from datetime import date, datetime, timezone

from fyt import catalog, liturgy, schedule
from fyt.config import Config, load_config


def test_easter_and_the_moveable_feasts():
    assert liturgy.western_easter(2026) == date(2026, 4, 5)
    assert liturgy.western_easter(2027) == date(2027, 3, 28)
    assert liturgy.orthodox_easter(2027) == date(2027, 5, 2)  # Western and Orthodox differ in 2027
    a = lambda k, y=2027: liturgy.anchor_date(k, y)  # noqa: E731
    assert a("ash_wednesday") == date(2027, 2, 10)
    assert a("palm_sunday") == date(2027, 3, 21)
    assert a("pentecost") == date(2027, 5, 16)
    assert a("advent", 2026) == date(2026, 11, 29)
    assert a("christ_the_king", 2026) == date(2026, 11, 22)
    assert a("may:sun:2") == date(2027, 5, 9)  # Mother's Day (US)
    assert a("nov:thu:4", 2026) == date(2026, 11, 26)
    assert a("12-25") == date(2027, 12, 25)


def test_holy_week_campaign_falls_on_the_right_days():
    cfg = load_config()
    got = {e.topic: e.on for e in liturgy.entries(cfg, date(2027, 3, 1), date(2027, 4, 10))}
    assert got["idea:easter-palm-sunday@2027"] == date(2027, 3, 21)
    assert got["idea:easter-maundy-thursday-night-betrayed@2027"] == date(2027, 3, 25)
    assert got["idea:easter-good-friday-it-is-finished@2027"] == date(2027, 3, 26)
    assert got["idea:easter-holy-saturday-silent@2027"] == date(2027, 3, 27)
    assert got["idea:easter-he-is-risen@2027"] == date(2027, 3, 28)
    assert min(got.values()) <= date(2027, 3, 14)  # anticipation starts two weeks before


def test_every_calendar_video_resolves_to_an_idea():
    cfg = load_config()
    year = liturgy.entries(cfg, date(2027, 1, 1), date(2027, 12, 31))
    assert len(year) >= 50
    for e in year:
        idea = catalog.get(cfg, e.topic)
        assert idea.title and idea.scriptures and idea.topic == e.topic
    gf = catalog.get(cfg, "idea:easter-good-friday-it-is-finished@2027")
    assert gf.music == "calm" and gf.series == "Holy Week & Easter"


def test_traditions_switch_events_on_and_off():
    cfg = load_config()

    def on():
        return {e.topic.split("@")[0] for e in liturgy.entries(cfg, date(2027, 8, 1), date(2027, 8, 31))}

    assert "idea:assumption-magnificat" not in on()  # catholic feasts are off by default
    cfg.liturgy.traditions.append("catholic")
    assert "idea:assumption-magnificat" in on()
    cfg.liturgy.enabled = False
    assert on() == set()


def test_campaign_videos_get_slots_a_week_ahead():
    cfg = load_config()
    now = datetime(2027, 3, 20, 0, 0, tzinfo=timezone.utc)
    slots = schedule.upcoming_slots(cfg, now)
    by_topic = {s.topic: s for s in slots if s.topic}
    gf = by_topic["idea:easter-good-friday-it-is-finished@2027"]
    assert gf.kind == "long" and gf.minutes == 8 and gf.at == datetime(2027, 3, 26, 15, 0, tzinfo=timezone.utc)
    palm = by_topic["idea:easter-palm-sunday@2027"]
    assert palm.kind == "short" and palm.at.hour == 17
    assert [s for s in slots if not s.topic and s.at.date() == date(2027, 3, 20)]  # evergreen keeps running


def test_seasons_lean_the_evergreen_picks(monkeypatch):
    cfg = load_config()
    assert liturgy.season(cfg, date(2027, 3, 3))["name"] == "Lent"
    assert liturgy.season(cfg, date(2027, 3, 23))["name"] == "Holy Week"
    assert liturgy.season(cfg, date(2027, 1, 3))["name"] == "Christmastide"  # across the new year
    items = [
        catalog.Idea(id="a", title="A", category="motivation", emotion="joy", formats=["short"]),
        catalog.Idea(id="b", title="B", category="motivation", emotion="forgiveness", formats=["short"]),
    ]
    monkeypatch.setattr(catalog, "load", lambda cfg: items)
    plain = Config(format="short")
    assert catalog.pick(plain, set(), category="motivation").id == "a"
    lent = liturgy.season(cfg, date(2027, 3, 3))
    assert catalog.pick(plain, set(), category="motivation", season=lent).id == "b"


def test_a_planned_video_is_made_for_its_slot(monkeypatch, tmp_path):
    from fyt import pipeline
    from fyt.store import Job, Topics

    cfg = Config(jobs_dir=str(tmp_path))
    made = []

    def make_topic(cfg, topic):
        made.append(topic)
        return Job.create(cfg, topic)

    monkeypatch.setattr(pipeline, "make_topic", make_topic)
    monkeypatch.setattr(pipeline, "make_next", lambda cfg, topics, category=None: "fallback")
    topics = Topics(cfg)
    job = pipeline.make_planned(cfg, topics, "idea:easter-he-is-risen@2027")
    assert made == ["idea:easter-he-is-risen@2027"] and job != "fallback"
    assert pipeline.make_planned(cfg, topics, "idea:easter-he-is-risen@2027") == "fallback"  # never twice
