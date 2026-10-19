"""Sunday Gospel videos: which Sunday a date is in the Roman Lectionary, and its Gospel."""

from datetime import date

import pytest

from fyt import catalog, lectionary, liturgy
from fyt.config import load_config


@pytest.mark.parametrize(
    "day, name, cycle, gospel",
    [
        ("2025-10-19", "29th Sunday in Ordinary Time", "C", ["Luke 18:1-8"]),  # the widow and the judge
        ("2026-10-25", "30th Sunday in Ordinary Time", "A", ["Matthew 22:34-40"]),
        ("2024-12-01", "First Sunday of Advent", "C", ["Luke 21:25-28", "Luke 21:34-36"]),
        ("2026-11-29", "First Sunday of Advent", "B", ["Mark 13:33-37"]),  # the new year starts at Advent
        ("2025-01-19", "2nd Sunday in Ordinary Time", "C", ["John 2:1-11"]),  # the wedding at Cana
        ("2024-01-14", "2nd Sunday in Ordinary Time", "B", ["John 1:35-42"]),  # Baptism on Monday 8 Jan
        ("2026-01-11", "The Baptism of the Lord", "A", ["Matthew 3:13-17"]),
        ("2026-02-15", "6th Sunday in Ordinary Time", "A", ["Matthew 5:17-37"]),
        ("2026-03-29", "Palm Sunday of the Passion of the Lord", "A", ["Matthew 26:14-27:66"]),
        ("2026-04-12", "Second Sunday of Easter", "A", ["John 20:19-31"]),
        ("2026-05-31", "The Most Holy Trinity", "A", ["John 3:16-18"]),
        ("2023-11-26", "Our Lord Jesus Christ, King of the Universe", "A", ["Matthew 25:31-46"]),
        ("2025-11-02", "All Souls", "C", ["John 6:37-40"]),  # a feast takes the Sunday's place
        ("2025-12-28", "The Holy Family", "A", ["Matthew 2:13-15", "Matthew 2:19-23"]),
    ],
)
def test_sunday_and_its_gospel(day, name, cycle, gospel):
    s = lectionary.sunday(date.fromisoformat(day))
    assert (s.name, s.cycle, s.gospel) == (name, cycle, gospel)


def test_every_sunday_of_three_years_has_a_gospel():
    d = date(2026, 1, 4)
    while d < date(2029, 1, 1):
        if lectionary.which(d)[0] != "christmas":  # Christmas Day itself is left to the calendar campaign
            assert lectionary.sunday(d), d
        d = date.fromordinal(d.toordinal() + 7)


def test_sunday_gospel_shorts_come_out_on_friday_and_resolve_to_ideas():
    cfg = load_config()
    cfg.liturgy.sunday_gospel = True
    got = [e for e in liturgy.entries(cfg, date(2026, 10, 19), date(2026, 11, 30)) if e.event == "sunday_gospel"]
    assert got[0].on == date(2026, 10, 23) and got[0].topic == "idea:sunday-gospel-ot30-A@2026"
    assert all(e.on.weekday() == 4 and e.kind == "short" for e in got)
    idea = catalog.get(cfg, got[0].topic)
    assert idea.scriptures == ["Matthew 22:34-40"] and idea.series == "Sunday Gospel"
    assert "30th Sunday in Ordinary Time" in idea.angle and "Year A" in idea.angle


def test_sundays_a_campaign_covers_are_left_to_it():
    cfg = load_config()
    cfg.liturgy.sunday_gospel = True
    topics = [e.topic for e in liturgy.entries(cfg, date(2027, 3, 20), date(2027, 3, 31))]
    assert not any("sunday-gospel-easter1" in t for t in topics)  # Easter has its own videos
    cfg.liturgy.sunday_gospel = False
    assert not any("sunday-gospel" in e.topic for e in liturgy.entries(cfg, date(2026, 10, 19), date(2026, 11, 30)))
