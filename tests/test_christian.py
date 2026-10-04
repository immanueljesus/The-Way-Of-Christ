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
    assert cfg.source == "catalog"
    assert {p.weekday for p in cfg.schedule.plan if p.kind == "short"} == set(range(7))  # a Short every morning
    assert len([p for p in cfg.schedule.plan if p.kind == "long"]) == 2
    assert {p.category for p in cfg.schedule.plan if p.category} <= set(cfg.catalog.mix)
    assert len({p.category for p in cfg.schedule.plan if p.kind == "short"}) == 7  # a different pillar each morning


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


def test_a_loose_quote_of_a_long_passage_becomes_its_closest_verse():
    passage = scripture.Passage(
        "Isaiah 40:29-31", "He gives power to the weak. ... They will run, and not be weary.", "WEB",
        verses=[("Isaiah 40:29", "He gives power to the weak."), ("Isaiah 40:30", "Even the youths faint."),
                ("Isaiah 40:31", "They will mount up with wings like eagles. They will run, and not be weary.")],
    )
    s = script(ScriptScene(narration="n", type="quote", text="soar on wings like eagles", author="Isaiah 40:29-31"))
    fixed, problems = scripture.check_quotes(Config(), s, {"Isaiah 40:29-31": passage})
    assert fixed.scenes[0].author == "Isaiah 40:31" and fixed.scenes[0].text.startswith("They will mount up")
    assert problems == []


# --- The content universe ---


def test_the_catalog_spans_the_universe():
    ideas = catalog.load(load_config())
    assert {i.category for i in ideas} >= {
        "jesus", "bible_story", "motivation", "prayer", "peace", "relationships", "purpose",
        "spiritual_battles", "wisdom", "history", "everyday_life",
    }
    assert {i.shape for i in ideas} == set(catalog.ARCS)
    assert len({i.emotion for i in ideas}) >= 12
    people = {i.character for i in ideas}
    assert {"Deborah", "Bartimaeus", "Stephen", "Barnabas", "Lydia", "Naomi"} <= people
    assert all(i.arc in ("", *catalog.ARCS) for i in ideas)


def test_pick_avoids_repeating_the_last_character_and_feeling(monkeypatch):
    items = [
        catalog.Idea(id="j1", title="J1", category="bible_story", character="Joseph", emotion="hope", formats=["short"]),
        catalog.Idea(id="j2", title="J2", category="bible_story", character="Joseph", emotion="courage", formats=["short"]),
        catalog.Idea(id="d1", title="D1", category="bible_story", character="Deborah", emotion="hope", formats=["short"]),
        catalog.Idea(id="r1", title="R1", category="bible_story", character="Ruth", emotion="love", formats=["short"]),
    ]
    monkeypatch.setattr(catalog, "load", lambda cfg: items)
    cfg = Config(format="short")
    assert catalog.pick(cfg, set(), category="bible_story").id == "j1"  # nothing recent: list order
    assert catalog.pick(cfg, {"idea:j1"}, category="bible_story", recent=["idea:j1"]).id == "r1"  # new person, new feeling


def test_each_story_shape_gets_its_own_structure():
    from fyt import llm

    assert llm.structure_for("journey", False) == llm.LONG_STRUCTURE
    assert llm.structure_for("journey", True) == llm.SHORT_STRUCTURE
    assert llm.structure_for("story", False) == llm.STORY_STRUCTURE
    assert "Shorts version" in llm.structure_for("curiosity", True)
    assert llm.structure_for("anything", False, prayer=True) == llm.PRAYER_STRUCTURE
    assert len({llm.structure_for(a, False) for a in catalog.ARCS}) == len(catalog.ARCS)


def test_a_pillar_running_low_gets_new_ideas(monkeypatch, tmp_path):
    from fyt import llm

    items = [catalog.Idea(id="w1", title="W1", category="wisdom", formats=["short"])]
    real_load = catalog.load
    cfg = Config(jobs_dir=str(tmp_path))
    cfg.catalog.path = str(tmp_path / "none.yaml")
    asked = []

    def ideate(cfg, category, n, avoid, people, examples=""):
        asked.append((category, people))
        return [
            llm.NewIdea(id="proverbs-on-sleep", title="Why Rest Is Holy", category=category, emotion="peace",
                        arc="wisdom", scriptures=["Psalm 127:2"], angle="a", formats=["short", "huge"]),
            llm.NewIdea(id="bad-ref", title="No Verse", category=category, emotion="hope", arc="journey",
                        scriptures=["somewhere in Psalms"], angle="a", formats=["short"]),
        ]

    monkeypatch.setattr(llm, "ideate_catalog", ideate)
    monkeypatch.setattr(scripture, "fetch_all", lambda cfg, refs: {r: scripture.Passage(r, "text", "WEB") for r in refs})
    assert catalog.top_up(cfg, set(), "wisdom", []) == 1
    got = {i.id: i for i in real_load(cfg)}
    assert got["proverbs-on-sleep"].formats == ["short"] and got["proverbs-on-sleep"].generated
    assert "bad-ref" not in got  # ideas without a real reference are dropped
    monkeypatch.setattr(catalog, "load", lambda cfg: items + list(got.values()) * 5)
    assert catalog.top_up(cfg, set(), "wisdom", []) == 0  # enough ideas left: nothing asked
    assert len(asked) == 1


def test_empty_narration_is_repaired():
    from fyt.pipeline import repair_script

    s = script(
        ScriptScene(narration="A line.", type="broll"),
        ScriptScene(narration="", type="quote", text="A gentle answer turns away wrath.", author="Proverbs 15:1"),
        ScriptScene(narration=" ", type="statement", text="t"),
    )
    fixed = repair_script(s)
    assert [x.narration for x in fixed.scenes] == ["A line.", "A gentle answer turns away wrath."]


# --- Bible first, emotion second ---


def test_no_formula_titles_in_the_idea_bank():
    from fyt import llm

    cfg = load_config()
    ideas = catalog.load(cfg)
    assert not [i.title for i in ideas if llm.title_banned(i.title)]
    starts = [" ".join(i.title.lower().strip("'\"").split()[:2]) for i in ideas]
    assert max(starts.count(w) for w in set(starts)) < len(ideas) / 10  # no opening dominates
    mustard = [i for i in ideas if "mustard" in i.title.lower()]
    assert all(len({r.split(":")[0] for r in i.scriptures}) == 1 for i in mustard)  # 13 and 17 stay apart


def test_formula_titles_are_banned():
    from fyt import llm

    assert llm.title_banned("When Doubt Feels Heavy, Remember the Mustard Seed")
    assert llm.title_banned("When the Night Whispers, Rise")
    assert not llm.title_banned("Moses Didn't Think He Was Ready")
    assert not llm.title_banned("Remember What God Has Already Done")


def test_title_styles_rotate():
    from fyt import llm

    assert llm.choose_title_style("story", "", []) == "cinematic"
    assert llm.choose_title_style("story", "", ["cinematic"]) == "character"
    assert llm.choose_title_style("curiosity", "history", []) == "history"
    assert llm.choose_title_style("story", "", [], seasonal=True) == "seasonal"
    assert "Remember" in llm.title_rule("verse")  # the rule names the banned formula


def test_the_editors_truth_reaches_the_script_notes():
    idea = catalog.get(load_config(), "idea:moses-burning-bush")
    assert "I will be with you" in idea.truth
    assert "Central truth" in catalog.brief(idea, load_config())


def test_an_unfaithful_script_is_rewritten_then_rejected(monkeypatch, tmp_path):
    import pytest

    from fyt import llm, pipeline
    from fyt.store import Job

    cfg = Config(jobs_dir=str(tmp_path))
    job = Job.create(cfg, "t")
    verdicts = [llm.Faithfulness(faithful=False, problems=["merges Matthew 13 and 17"]),
                llm.Faithfulness(faithful=True, problems=[])]
    monkeypatch.setattr(llm, "check_faithfulness", lambda *a: verdicts.pop(0))
    asked = []
    monkeypatch.setattr(llm, "write_script", lambda *a, **k: asked.append(k["feedback"]) or script())
    out = pipeline.keep_faithful(cfg, job, script(), "study", "verses", "s", "n", "", False, False, "story", "cinematic")
    assert out.title and "merges Matthew 13 and 17" in asked[0]
    verdicts[:] = [llm.Faithfulness(faithful=False, problems=["promises a breakthrough"])] * 2
    with pytest.raises(RuntimeError, match="bends the passage"):
        pipeline.keep_faithful(cfg, job, script(), "study", "verses", "s", "n", "", False, False, "story", "cinematic")
