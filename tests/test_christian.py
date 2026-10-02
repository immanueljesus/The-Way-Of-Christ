"""The Christian channel layer: Scripture checks, the idea catalog, the weekly plan and repurposing."""

from datetime import datetime, timezone

import pytest

from fyt import catalog, growth, llm, pipeline, schedule, scripture
from fyt.config import Config, PlanSlot, load_config
from fyt.models import Script, ScriptScene
from fyt.store import Topics
from fyt.youtube import build_body

MONDAY = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)


def script(*scenes: ScriptScene) -> Script:
    return Script(
        title="When You Feel Forgotten",
        description="D",
        tags=["a"],
        thumbnail_text="Not Forgotten",
        thumbnail_kicker="When You Feel...",
        thumbnail_query="q",
        scenes=list(scenes) or [ScriptScene(narration="n", type="statement", text="t")],
        sources=["Genesis 40:23"],
    )


# --- Scripture ---


def test_find_references():
    text = "See Genesis 50:20, 1 Peter 5:7 and Psalm 23:1-4; also Song of Solomon 2:4 and Genesis 50:20 again."
    assert scripture.find_references(text) == ["Genesis 50:20", "1 Peter 5:7", "Psalm 23:1-4", "Song of Solomon 2:4"]
    assert scripture.is_reference("Matthew 11:28") and not scripture.is_reference("C. S. Lewis")


def test_ranges_across_chapters_keep_their_end_chapter():
    text = "betrayal (Genesis 42:29–43:15). Then the meal (Genesis 43:16–44:34) and Genesis 42:1–28."
    assert scripture.find_references(text) == ["Genesis 42:29-43:15", "Genesis 43:16-44:34", "Genesis 42:1-28"]


def test_loose_scripture_quotes_are_replaced_with_the_real_verse():
    cfg = Config()
    passages = {
        "Genesis 50:20": scripture.Passage("Genesis 50:20", "As for you, you meant evil against me, but God meant it for good.", "WEB"),
        "Isaiah 41:10": scripture.Passage("Isaiah 41:10", "Don't you be afraid, for I am with you. " * 20, "WEB"),
    }
    s = script(
        ScriptScene(narration="n", type="quote", text="you meant evil against me, but God meant it for good", author="Genesis 50:20"),
        ScriptScene(narration="n", type="quote", text="God turns evil into good", author="Genesis 50:20"),
        ScriptScene(narration="n", type="quote", text="Fear not, I am always with you", author="Isaiah 41:10"),
        ScriptScene(narration="n", type="quote", text="Courage is fear that has said its prayers.", author="Dorothy Bernstein"),
    )
    fixed, problems = scripture.check_quotes(cfg, s, passages)
    assert fixed.scenes[0].text == s.scenes[0].text  # an exact part of the verse is fine
    assert fixed.scenes[1].text == passages["Genesis 50:20"].text  # a paraphrase is replaced
    assert problems == ["scene 3's quote doesn't match Isaiah 41:10 and the passage is too long to show"]
    assert fixed.scenes[3].text == s.scenes[3].text  # not Scripture: left alone


def test_unreachable_bible_api_leaves_quotes_alone(monkeypatch):
    def down(cfg, ref):
        raise ConnectionError("offline")

    monkeypatch.setattr(scripture, "fetch", down)
    s = script(ScriptScene(narration="n", type="quote", text="anything", author="John 3:16"))
    fixed, problems = scripture.check_quotes(Config(), s, {})
    assert fixed.scenes[0].text == "anything" and problems == []


def test_every_long_chapter_sees_the_verses():
    notes = "## Scripture (exact text)\n- John 3:16: \"For God so loved\"\n\n# Idea\nAngle\n\n# Article\n" + "text\n" * 50
    verses, rest = llm.scripture_section(notes)
    assert verses.startswith("## Scripture") and "John 3:16" in verses
    assert "Scripture" not in rest and rest.startswith("# Idea")


# --- Catalog ---


def test_the_shipped_catalog_is_valid():
    cfg = load_config()
    ideas = catalog.load(cfg)
    assert len(ideas) >= 100
    assert {i.category for i in ideas} <= set(cfg.catalog.mix)
    for i in ideas:
        assert set(i.formats) <= set(catalog.FORMATS), i.id
        assert i.scriptures, i.id
        for ref in i.scriptures:
            assert scripture.find_references(ref) == [ref], (i.id, ref)
        assert not i.series or i.series in cfg.growth.series, (i.id, i.series)


@pytest.fixture
def ideas(monkeypatch):
    items = [
        catalog.Idea(id="m1", title="M1", category="motivational", formats=["short", "medium"]),
        catalog.Idea(id="m2", title="M2", category="motivational", formats=["short", "long"]),
        catalog.Idea(id="p1", title="P1", category="prayer", formats=["short", "sleep"]),
        catalog.Idea(id="b1", title="B1", category="bible_story", formats=["medium", "long"]),
    ]
    monkeypatch.setattr(catalog, "load", lambda cfg: items)
    return items


def test_pick_follows_the_mix_the_slot_and_the_length(ideas):
    cfg = Config(format="short")
    cfg.catalog.mix = {"motivational": 50, "prayer": 50, "bible_story": 0}
    assert catalog.pick(cfg, set()).id == "m1"
    assert catalog.pick(cfg, {"idea:m1"}).id == "p1"  # motivational is now ahead of its share
    assert catalog.pick(cfg, set(), category="prayer").id == "p1"
    long = cfg.model_copy(update={"format": "long"})
    assert catalog.pick(long, set(), minutes=10).id == "m2"
    assert catalog.pick(long, set(), minutes=30).id == "p1"  # sleep-length prayer
    assert catalog.pick(long, set(), category="bible_story", minutes=6).id == "b1"


def test_a_plan_slot_gets_an_idea_from_its_category(ideas, tmp_path):
    cfg = Config(jobs_dir=str(tmp_path), source="catalog", format="short")
    topics = Topics(cfg)
    topics.add(["cut:VID-1"])
    picked = pipeline.next_topic(cfg, topics, category="prayer")
    assert picked[1] == "idea:p1"
    topics.set(picked[0], "done")
    assert pipeline.next_topic(cfg, topics)[1] == "cut:VID-1"  # daily slot: cuts first
    long = cfg.model_copy(update={"format": "long", "target_minutes": 6})
    assert pipeline.next_topic(long, topics)[1] == "idea:m1"  # cuts never fill long slots; m1 fits a 6 minute video


# --- Weekly plan ---


def test_plan_slots_carry_category_and_length():
    cfg = Config()
    cfg.schedule.short_slots = ["01:00"]
    cfg.schedule.long_weekday = None
    cfg.schedule.buffer_days = cfg.schedule.long_lead_days = 2
    cfg.schedule.plan = [
        PlanSlot(weekday=0, time="12:00", kind="short", category="motivational"),
        PlanSlot(weekday=1, time="16:00", kind="long", category="bible_story", minutes=6),
        PlanSlot(weekday=1, time="01:00", kind="short", category="prayer"),  # same time as a daily slot
    ]
    got = [(s.at.strftime("%a %H:%M"), s.kind, s.category, s.minutes) for s in schedule.upcoming_slots(cfg, MONDAY)]
    assert got == [
        ("Mon 01:00", "short", None, None),
        ("Mon 12:00", "short", "motivational", None),
        ("Tue 01:00", "short", "prayer", None),
        ("Tue 16:00", "long", "bible_story", 6),
    ]
    long = schedule.upcoming_slots(cfg, MONDAY)[3]
    assert schedule.slot_config(cfg, long).target_minutes == 6
    assert schedule.make_minutes(long, cfg) == 60


def test_shipped_channel_config_loads_with_the_weekly_plan():
    cfg = load_config()
    assert cfg.source == "catalog" and len(cfg.schedule.plan) == 7
    assert {p.category for p in cfg.schedule.plan} <= set(cfg.catalog.mix)


# --- Packaging ---


def test_extras_markdown_has_storyboard_and_pieces():
    s = script(ScriptScene(narration="Joseph | waited.", type="broll", broll_query="prison cell", visual_prompt="Dim cell"))
    extras = growth.Extras(
        quote_cards=[growth.QuoteCard(text="Not forgotten.", reference="Isaiah 49:15")],
        prayer_title="A Prayer When You Feel Forgotten",
        prayer="Lord... Amen.",
        community_post="Have you ever felt forgotten?",
        pinned_comment="You are seen.",
        short_ideas=["The pit wasn't the end."],
    )
    md = growth.extras_markdown(s, extras)
    assert '- "Not forgotten." (Isaiah 49:15)' in md
    assert "## A Prayer When You Feel Forgotten" in md
    assert "| 1 | broll | Joseph / waited. | Dim cell | prison cell |" in md
    assert "## Storyboard" in growth.extras_markdown(s, None)


def test_description_footer_is_added():
    cfg = Config()
    cfg.channel.description_footer = "Subscribe for encouragement."
    body = build_body(cfg, script())
    assert body["snippet"]["description"].endswith("Subscribe for encouragement.")


def test_job_files_are_utf8_whatever_the_system_encoding(tmp_path):
    """Windows defaults to cp1252, which can't hold characters models often write ( , curly quotes)."""
    from fyt.pipeline import load_script
    from fyt.store import Job

    job = Job.create(Config(jobs_dir=str(tmp_path)), "idea:x")
    s = script(ScriptScene(narration="God sees you “now”.", type="statement", text="t"))
    job.update(title="Not forgotten")
    job.file("script.json").write_text(s.model_dump_json(indent=2), encoding="utf-8")
    assert load_script(job.file("script.json")).scenes[0].narration == s.scenes[0].narration
    assert Job(job.path).meta["title"] == "Not forgotten"
