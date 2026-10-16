"""Advent calendar, weekly sleep videos, Shorts that point to their full video, thumbnail variants
for Test & compare, and Spanish titles and descriptions."""

import json
from collections import Counter
from datetime import date, datetime, timezone

import pytest

from fyt import catalog, growth, liturgy, llm, localize, pipeline, schedule, youtube
from fyt.config import Config, load_config, sleep_config
from fyt.models import Chapter, Media, Script, ScriptScene
from fyt.store import Job, Uploads
from fyt.timeline import build_props


def script(n=3, **update) -> Script:
    s = Script(
        title="The Prison Was Not Joseph's Ending",
        description="Joseph waited two years.\n\nKey Scriptures: Genesis 40:23; Isaiah 49:15\n\nChapters:\n0:00 Start\n1:10 The pit",
        tags=["joseph"], thumbnail_text="NOT FORGOTTEN", thumbnail_kicker="Joseph", thumbnail_query="prison light",
        scenes=[ScriptScene(narration=f"Line {i}.", type="broll", broll_query="road") for i in range(n)],
        sources=["Genesis 40:23"],
    )
    return s.model_copy(update=update)


# --- Advent calendar ------------------------------------------------------------


def test_advent_calendar_is_a_short_every_morning_from_1_to_24_december():
    cfg = load_config()
    days = [e for e in liturgy.entries(cfg, date(2026, 11, 20), date(2026, 12, 31)) if e.event == "advent_calendar"]
    assert [e.on for e in days] == [date(2026, 12, d) for d in range(1, 25)]
    assert {e.kind for e in days} == {"short"} and {e.time for e in days} == {"08:00"}
    for n, e in enumerate(days, 1):
        idea = catalog.get(cfg, e.topic)
        assert idea.title_prefix == f"Advent: Day {n} · " and idea.scriptures and idea.series
    # The campaign starts with the season itself (first Sunday of Advent, 29 November 2026).
    assert liturgy.anchor_date("advent", 2026) == date(2026, 11, 29)
    christmas = {e.topic.split("@")[0] for e in liturgy.entries(cfg, date(2026, 11, 29), date(2026, 12, 31))}
    assert "idea:advent-world-was-waiting" in christmas


def test_advent_shorts_take_the_morning_slot_instead_of_adding_uploads():
    cfg = load_config()
    now = datetime(2026, 11, 30, 12, 0, tzinfo=timezone.utc)
    slots = schedule.upcoming_slots(cfg, now)
    dec1 = [s for s in slots if s.at == datetime(2026, 12, 1, 13, 0, tzinfo=timezone.utc)]  # 08:00 in New York
    assert len(dec1) == 1 and dec1[0].topic == "idea:advent-day-01-the-first-promise@2026"
    assert dec1[0].label == "advent_calendar: The First Promise" and dec1[0].kind == "short"
    per_day = Counter(s.at.astimezone(schedule.ZoneInfo("America/New_York")).date() for s in slots)
    assert per_day[date(2026, 12, 1)] <= cfg.schedule.max_uploads_per_day


def test_christmas_story_long_videos_and_the_christmas_eve_prayer():
    cfg = load_config()
    longs = {e.topic.split("@")[0]: e for e in liturgy.entries(cfg, date(2026, 12, 1), date(2026, 12, 31)) if e.kind == "long"}
    for key in ("christmas-gabriel-two-announcements", "christmas-story-as-luke-tells-it", "christmas-simeon-and-anna",
                "christmas-eve-night-everything-changed", "christmas-eve-prayer"):
        assert "idea:" + key in longs
    prayer = catalog.get(cfg, longs["idea:christmas-eve-prayer"].topic)
    assert prayer.category == "prayer" and prayer.shape == "prayer" and prayer.music == "calm"
    # Christmas Eve has two long videos; they get different times, so neither replaces the other.
    now = datetime(2026, 12, 20, 12, 0, tzinfo=timezone.utc)
    eve = [s for s in schedule.upcoming_slots(cfg, now) if s.topic and "christmas-eve" in s.topic]
    assert len(eve) == 2 and len({s.at for s in eve}) == 2


def test_no_december_day_has_more_campaign_shorts_than_slots():
    cfg = load_config()
    untimed = Counter(e.on for e in liturgy.entries(cfg, date(2026, 11, 20), date(2027, 1, 10)) if e.kind == "short" and not e.time)
    assert max(untimed.values()) <= len(cfg.liturgy.short_times)


def test_series_titles_keep_their_prefix_and_kicker():
    s = pipeline.with_title_prefix(script(), "Advent: Day 3 · ")
    assert s.title == "Advent: Day 3 · The Prison Was Not Joseph's Ending" and s.thumbnail_kicker == "Advent: Day 3"
    again = pipeline.with_title_prefix(script(title="Advent: Day 3 - Comfort, Comfort My People"), "Advent: Day 3 · ")
    assert again.title == "Advent: Day 3 · Comfort, Comfort My People"
    assert len(pipeline.with_title_prefix(script(title="word " * 30), "Advent: Day 3 · ").title) <= 100


# --- Weekly sleep video -----------------------------------------------------------


def test_sleep_slot_is_made_as_a_calm_low_frame_rate_video():
    cfg = load_config()
    slot = next(s for s in schedule.upcoming_slots(cfg, datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)) if (s.minutes or 0) >= 18)
    assert slot.at == datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)  # Sunday 8 pm in New York
    vcfg = schedule.slot_config(cfg, slot)
    assert vcfg.is_sleep and not vcfg.captions and vcfg.voice.words_per_minute == cfg.sleep.words_per_minute
    assert schedule.make_minutes(slot, cfg) < cfg.schedule.max_run_minutes  # fits the free runner
    props = build_props(vcfg, script(1), [(0.0, 2.0)], [[]], {}, None, None)
    assert props.fps == cfg.sleep.fps
    assert build_props(cfg.model_copy(update={"format": "long"}), script(1), [(0.0, 2.0)], [[]], {}, None, None).fps == 30
    assert sleep_config(cfg) is cfg  # Shorts and ordinary long videos are untouched


def test_sleep_slot_picks_a_sleep_idea_and_the_writer_knows_it(monkeypatch):
    cfg = sleep_config(load_config().model_copy(update={"format": "long", "target_minutes": 30}))
    cfg.jobs_dir = "nonexistent-jobs-for-test"
    idea = catalog.pick(cfg, set(), category="peace")
    assert "sleep" in idea.formats
    assert sum(1 for i in catalog.load(cfg) if i.series == "Fall Asleep in God's Word") >= 12
    cfg.llm.provider = "openai"
    seen = []
    monkeypatch.setattr(llm, "write_long_script", lambda cfg, topic, notes, guide, *a, **k: seen.append(guide))
    llm.write_script(cfg, "Psalm 23", "notes")
    assert "fall asleep" in seen[0].lower() and "no call to subscribe" in seen[0]


# --- Shorts cut from a long video ---------------------------------------------------


def test_cut_shorts_end_calmly_and_lead_with_the_link(monkeypatch):
    long = script(6, chapters=[Chapter(title="Start", scene=0), Chapter(title="The pit", scene=2), Chapter(title="The palace", scene=4)],
                  description="Joseph waited.\n\nScripture quotations are from the World English Bible.")
    monkeypatch.setattr(llm, "structured", lambda *a, **k: growth.CutChoice(chapters=[2, 3]))
    cuts = growth.cut_scripts(Config(), long, "LONG123", 2)
    for c in cuts:
        assert c.scenes[-1].narration.endswith(tuple(growth.CUT_ENDINGS))
        assert c.description.splitlines()[0] == "Full video: https://youtu.be/LONG123"
        assert "Scripture quotations" in c.description
    assert cuts[0].scenes[-1].narration != cuts[1].scenes[-1].narration  # the closing line varies
    sheet = youtube.upload_sheet(Config(format="short"), cuts[0])
    assert "RELATED VIDEO" in sheet and "https://youtu.be/LONG123" in sheet
    body = youtube.build_body(Config(format="short"), cuts[0])
    assert body["snippet"]["description"].startswith("Full video: https://youtu.be/LONG123")


# --- Thumbnail variants -------------------------------------------------------------


def test_three_thumbnails_for_test_and_compare():
    cfg = Config(format="long")
    a, b = Media(src="media/s1.jpg", kind="image"), Media(src="media/s5.jpg", kind="image")
    thumbs = pipeline.thumbnail_variants(cfg, script(thumbnail_variants=["HE REMEMBERED", "TWO YEARS"]), a, b)
    assert [t.title for t in thumbs] == ["NOT FORGOTTEN", "HE REMEMBERED", "TWO YEARS"]
    assert [t.background for t in thumbs] == [a, b, a] and [t.layout for t in thumbs] == ["side", "side", "center"]
    plain = pipeline.thumbnail_variants(cfg, script(), a, None)  # no alternatives: still three distinct looks
    assert len({(t.title, t.layout, t.background.src) for t in plain}) == 2 and len(plain) == 3
    assert len(pipeline.thumbnail_variants(cfg, script(), a, b, n=1)) == 1


def test_polish_writes_alternative_thumbnail_texts(monkeypatch):
    reply = {"titles": [], "best_title": "The Prison Was Not Joseph's Ending", "thumbnail_text": "NOT FORGOTTEN",
             "thumbnail_alternatives": ["not forgotten", "HE REMEMBERED", "TWO YEARS", "EXTRA"], "hook": "", "series": ""}
    monkeypatch.setattr(llm, "structured", lambda cfg, system, user, schema, max_tokens=0: schema.model_validate(reply))
    out = growth.polish(Config(format="long"), script())
    assert out.thumbnail_variants == ["HE REMEMBERED", "TWO YEARS"]


def test_upload_sheet_lists_the_thumbnail_test():
    sheet = youtube.upload_sheet(Config(format="long"), script(), thumbnails=list(pipeline.THUMBNAILS))
    assert "Test & compare" in sheet and "thumbnail-c.png" in sheet


# --- Spanish titles and descriptions ----------------------------------------------------


SPANISH = {
    "title": "La prisión no fue el final de José",
    "description": "José esperó dos años.\n\nEscrituras clave: Génesis 40:23; Isaías 49:15\n\nCapítulos:\n0:00 Inicio\n1:10 El pozo",
    "footer": "Si necesitabas escuchar esto hoy, suscríbete.",
}


def test_translation_is_kept_only_when_references_links_and_timestamps_survive(monkeypatch):
    cfg = Config()
    cfg.channel.description_footer = "If you needed this, subscribe."
    monkeypatch.setattr(llm, "structured", lambda *a, **k: localize.Localized(**SPANISH))
    assert localize.translate(cfg, script(), "es").title == SPANISH["title"]
    lost = dict(SPANISH, description="José esperó dos años. Escrituras: Génesis 40")
    monkeypatch.setattr(llm, "structured", lambda *a, **k: localize.Localized(**lost))
    assert localize.translate(cfg, script(), "es") is None
    assert localize.problems("See https://youtu.be/x and John 3:16", "Juan 3:16") == ["missing link https://youtu.be/x"]


def test_localize_skips_the_channel_language_and_failures(monkeypatch):
    cfg = Config()
    cfg.localize.languages = ["en", "es", "fr"]

    def structured(cfg, system, user, schema, max_tokens=0):
        if "French" in system or "fr" in system.split("into ")[1][:3]:
            raise RuntimeError("rate limited")
        return localize.Localized(**SPANISH)

    monkeypatch.setattr(llm, "structured", structured)
    assert list(localize.localize(cfg, script())) == ["es"]


def test_upload_body_carries_spanish_localizations():
    cfg = Config(format="short")
    cfg.channel.description_footer = "Subscribe."
    body = youtube.build_body(cfg, script(series="Hard Seasons"), localizations={"es": SPANISH})
    es = body["localizations"]["es"]
    assert es["title"] == SPANISH["title"]
    assert "Fuentes:\n- Genesis 40:23" in es["description"] and "Serie: Hard Seasons" in es["description"]
    assert es["description"].endswith(SPANISH["footer"] + "\n\n#Shorts")
    assert body["snippet"]["description"].endswith("Subscribe.\n\n#Shorts")
    assert "localizations" not in youtube.build_body(cfg, script())


def test_upload_job_sends_localizations_records_the_video_and_skips_cuts_for_sleep(tmp_path, monkeypatch):
    cfg = Config(jobs_dir=str(tmp_path))
    job = Job.create(cfg.model_copy(update={"format": "long"}), "idea:fall-asleep-psalm-23")
    job.file("script.json").write_text(script().model_dump_json(), encoding="utf-8")
    job.file("localizations.json").write_text(json.dumps({"es": SPANISH}), encoding="utf-8")
    job.update(status="approved", category="peace", shape="peace", title_style="verse", minutes=30)
    sent = {}
    monkeypatch.setattr(youtube, "upload", lambda cfg, s, v, t, c, publish_at=None, localizations=None: sent.update(loc=localizations) or "VID1")
    monkeypatch.setattr(youtube, "can_manage", lambda: False)
    monkeypatch.setattr(pipeline, "queue_cuts", lambda *a: pytest.fail("sleep videos aren't cut into Shorts"))
    assert pipeline.upload_job(cfg, job) == "VID1"
    assert sent["loc"] == {"es": SPANISH}
    assert Uploads(cfg).described()["VID1"] == {
        "topic": "idea:fall-asleep-psalm-23", "title": script().title, "format": "long", "category": "peace",
        "shape": "peace", "emotion": None, "title_style": "verse", "minutes": 30,
    }
