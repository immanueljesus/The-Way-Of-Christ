"""Story-first: four content pillars, the evergreen / timely slate, visual styles, cuts and their analytics."""

from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

from fyt import catalog, growth, insights, llm, pipeline, schedule, slate
from fyt.config import Config, load_config
from fyt.models import Chapter, Script, ScriptScene
from fyt.store import Topics, Uploads

SEED = [
    ("David and Goliath: The Battle That Changed Everything", "1 Samuel 17", "cinematic"),
    ("Joseph: From Betrayal to the Throne of Egypt", "Genesis 37-50", "cinematic"),
    ("Daniel in the Lions' Den: The Night His Faith Was Tested", "Daniel 6", "cinematic"),
    ("The Prodigal Son: The Father's Unexpected Response", "Luke 15:11-32", "illustrated"),
    ("Jesus Calms the Storm: Why Were the Disciples Afraid?", "Mark 4:35-41", "cinematic"),
    ("The Good Samaritan: Who Is Your Neighbour?", "Luke 10:25-37", "illustrated"),
    ("Peter Denied Jesus. Then Jesus Met Him Again.", "Luke 22:54-62; John 21:15-19", "cinematic"),
    ("What Jesus Actually Taught About Loving Your Enemies", "Matthew 5:38-48", "documentary"),
]


@pytest.fixture
def cfg(tmp_path):
    c = load_config().model_copy(deep=True)
    c.jobs_dir = str(tmp_path)
    return c


# --- The backlog and the pillars ---


def test_the_backlog_seed_comes_first_in_its_order(cfg):
    used: set[str] = set()
    picked = []
    for _ in range(len(SEED)):
        idea = slate.pick_evergreen(cfg, used)
        picked.append((idea.title, idea.passage, idea.style))
        used.add(idea.topic)
    assert picked == SEED
    # After the seed: still backlog stories, every pillar and style valid, scored and anchored to Scripture.
    rest = [i for i in catalog.load(cfg) if i.backlog and i.topic not in used]
    assert 17 <= len(rest) <= 22  # about 25-30 in all
    assert {catalog.pillar_of(i) for i in rest} == set(catalog.PILLARS)
    for i in rest:
        assert i.style in slate.STYLES and i.question and i.passage and i.scriptures, i.id
        assert set(i.score) <= set(slate.SCORE_FIELDS)
    assert slate.pick_evergreen(cfg, used).backlog


def test_after_the_seed_the_evergreen_pick_balances_pillars_then_ranks_by_score(cfg, monkeypatch):
    items = [
        catalog.Idea(id="s-low", title="S low", category="bible_story", pillar="stories", backlog=True, score={"appeal": 1}),
        catalog.Idea(id="s-high", title="S high", category="bible_story", pillar="stories", backlog=True, score={"appeal": 5}),
        catalog.Idea(id="q", title="Q", category="jesus", pillar="questions", backlog=True),
        catalog.Idea(id="done", title="Done", category="bible_story", pillar="stories", formats=["long"]),
    ]
    monkeypatch.setattr(catalog, "load", lambda cfg: items)
    cfg.catalog.pillars = {"stories": 50, "questions": 50}
    assert slate.pick_evergreen(cfg, set()).id == "s-high"  # the higher score first
    assert slate.pick_evergreen(cfg, {"idea:done"}).id == "q"  # a story was just made: the pillar behind goes first
    # The season adds to the score: the idea whose feelings it shares goes first.
    items[0].emotion, items[1].emotion = "hope", "fear"
    assert slate.score(items[0], {"emotions": ["hope"]}) == slate.score(items[0]) + 2


def test_the_picker_keeps_the_four_pillars_in_balance(cfg):
    cfg = cfg.model_copy(update={"format": "short"})
    used: set[str] = set()
    made = Counter()
    for _ in range(40):
        idea = catalog.pick(cfg, used)
        made[catalog.pillar_of(idea)] += 1
        used.add(idea.topic)
    share = cfg.catalog.pillars
    for p, pct in share.items():
        assert abs(made[p] - 40 * pct / sum(share.values())) <= 2, made
    assert not [t for t in used if catalog.get(cfg, t).backlog]  # backlog stories wait for the evergreen slot


def test_every_shipped_idea_has_a_pillar_and_derived_pillars_make_sense():
    cfg = load_config()
    assert all(i.pillar in catalog.PILLARS for i in catalog.load(cfg))
    derive = lambda **kw: catalog.pillar_of(catalog.Idea(id="x", title="X", **kw))  # noqa: E731
    assert derive(category="bible_story") == "stories"
    assert derive(category="history") == "questions"
    assert derive(category="jesus", content_type="parable", arc="story") == "teachings"
    assert derive(category="motivation") == "struggles"
    assert catalog.get(cfg, "idea:sunday-gospel-ot29-A@2026").pillar == "teachings"


# --- The weekly slate ---


def test_the_calendar_never_takes_both_long_slots(cfg):
    """A year of weeks, Advent, Christmas, Lent, Holy Week and Easter included: every week the evergreen
    slot is a backlog story, the calendar only ever fills the timely slot, and no extra long slots appear."""
    cfg.schedule.long_lead_days = 7
    start = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)  # a Monday
    timely_with_calendar = 0
    for week in range(56):
        now = start + timedelta(weeks=week)
        longs = [s for s in schedule.upcoming_slots(cfg, now) if s.kind == "long" and s.at < now + timedelta(days=7)]
        evergreen = [s for s in longs if s.slate == "evergreen"]
        timely = [s for s in longs if s.slate == "timely"]
        assert len(evergreen) == 1 and len(timely) == 1, (now, longs)
        assert not evergreen[0].topic and not evergreen[0].options  # never chosen by the calendar
        others = [s for s in longs if not s.slate]
        assert all(s.minutes and s.minutes >= 18 and s.at.weekday() in (6, 0) for s in others)  # only the Sunday sleep video
        assert timely[0].options  # at least the coming Sunday's Gospel
        timely_with_calendar += any("sunday-gospel" not in o for o in timely[0].options)
    assert timely_with_calendar >= 8  # feasts and seasons do come through the timely slot


def test_the_timely_slot_follows_the_coming_sunday_gospel(cfg):
    options = slate.timely_options(cfg, date(2026, 10, 23))  # Friday before the 30th Sunday in Ordinary Time
    assert options[-1] == "idea:sunday-gospel-ot30-A@2026-long"
    idea = catalog.get(cfg, options[-1])
    assert idea.scriptures == ["Matthew 22:34-40"] and "long" in idea.formats


class Maker:
    """Stands in for making videos: records which topics were made."""

    def __init__(self, monkeypatch, fail=()):
        self.made, self.fail = [], set(fail)
        monkeypatch.setattr(pipeline, "make_topic", self.make_topic)

    def make_topic(self, cfg, topic):
        if topic in self.fail:
            raise RuntimeError("could not make it")
        self.made.append(topic)
        return pipeline.Job.create(cfg, topic)


def test_the_evergreen_slot_always_takes_the_backlog(cfg, monkeypatch):
    maker = Maker(monkeypatch)
    topics = Topics(cfg)
    long_cfg = cfg.model_copy(update={"format": "long"})
    for _ in range(3):
        pipeline.make_next(long_cfg, topics, slate=slate.EVERGREEN)
    assert [catalog.get(cfg, t).title for t in maker.made] == [t for t, _, _ in SEED[:3]]


def test_the_timely_slot_takes_an_evergreen_story_when_nothing_timely_can_be_made(cfg, monkeypatch):
    options = ("idea:easter-he-is-risen@2027", "idea:sunday-gospel-easter1-A@2027-long")
    maker = Maker(monkeypatch, fail={options[0]})
    topics = Topics(cfg)
    long_cfg = cfg.model_copy(update={"format": "long"})
    pipeline.make_timely(long_cfg, topics, options)
    assert maker.made == [options[1]]  # the feast failed: the Sunday Gospel instead
    pipeline.make_timely(long_cfg, topics, options[1:])  # already made: an evergreen story
    assert maker.made[-1] == "idea:story-david-and-goliath"


def test_fill_records_which_slate_each_long_video_came_from(cfg, monkeypatch):
    from fyt import youtube

    monday = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(youtube, "authorised", lambda: True)
    monkeypatch.setattr(youtube, "recent_uploads", lambda: [])
    monkeypatch.setattr(schedule, "utcnow", lambda: monday)
    calls = []

    def fake(kind):
        def make(cfg, topics, *a, **kw):
            calls.append((kind, cfg.format, kw.get("slate")))
            job = pipeline.Job.create(cfg, f"t{len(calls)}")
            job.update(status="approved")
            return job
        return make

    monkeypatch.setattr(pipeline, "make_next", fake("next"))
    monkeypatch.setattr(pipeline, "make_timely", fake("timely"))
    monkeypatch.setattr(pipeline, "make_planned", fake("planned"))
    monkeypatch.setattr(pipeline, "upload_job", lambda cfg, job, publish_at=None: f"V{job.id[-2:]}")
    cfg.bonus.winners = cfg.bonus.trends = False
    cfg.insights.enabled = False
    cfg.schedule.long_lead_days = 5  # Tuesday's and Friday's long videos both in reach
    cfg.schedule.max_run_minutes = 10_000
    cfg.schedule.max_uploads_per_day = 50
    schedule.fill(cfg, monday)
    assert ("next", "long", "evergreen") in calls  # Tuesday: the backlog
    assert ("timely", "long", None) in calls  # Friday: the week's calendar video or Sunday Gospel
    assert not [c for c in calls if c[1] == "long" and c[0] == "planned"]  # the calendar has no long slot of its own
    jobs = pipeline.list_jobs(cfg)
    assert {j.meta.get("slate") for j in jobs if j.meta.get("format") == "long"} == {"evergreen", "timely"}


# --- Visual styles ---


def test_each_style_sets_length_and_look_within_its_range(cfg):
    long_cfg = cfg.model_copy(update={"format": "long"})
    ideas = {i.id: i for i in catalog.load(cfg) if i.backlog}
    joseph = slate.style_config(long_cfg, ideas["story-joseph-betrayal-to-throne"])
    assert joseph.target_minutes == 9 and joseph.letterbox  # cinematic, its own length
    prodigal = slate.style_config(long_cfg, ideas["story-prodigal-son-father"])
    assert prodigal.target_minutes == 5 and not prodigal.letterbox and prodigal.art_images == 10  # illustrated
    enemies = slate.style_config(long_cfg, ideas["story-love-your-enemies"])
    assert 6 <= enemies.target_minutes <= 10  # documentary
    short = cfg.model_copy(update={"format": "short"})
    assert slate.style_config(short, ideas["story-joseph-betrayal-to-throne"]) is short  # Shorts keep their own
    sleep = cfg.model_copy(update={"format": "long", "target_minutes": 30})
    assert slate.style_config(sleep, ideas["story-joseph-betrayal-to-throne"]) is sleep
    assert slate.style_of(catalog.Idea(id="h", title="H", category="history")) == "documentary"
    assert "ILLUSTRATED" in slate.style_note(ideas["story-prodigal-son-father"], long_cfg)


# --- Scripts ---


def test_every_story_script_has_the_six_beats_and_marks_what_is_imagined():
    film = llm.structure_for("story", short=False)
    beats = ["Hook", "Setup", "Escalation", "Turning point", "Resolution", "Reflection"]
    assert [film.index(b) for b in beats] == sorted(film.index(b) for b in beats)
    assert "ONE dramatic question" in film and "5-15 seconds" in film
    assert "marked as imagined" in llm.BIBLE_FIRST
    assert "Hook" not in llm.structure_for("prayer", short=False)


def test_unmarked_invented_detail_fails_the_faithfulness_check():
    ok = llm.Faithfulness(faithful=True)
    assert llm.faithfulness_problems(ok) == []
    invented = llm.Faithfulness(faithful=True, unmarked_inventions=["Goliath's mother begging him not to fight"])
    assert llm.faithfulness_problems(invented) == [
        "invented detail told as Scripture (mark it as imagined or cut it): Goliath's mother begging him not to fight"]
    bent = llm.Faithfulness(faithful=False, problems=["promises victory over every problem"])
    assert llm.faithfulness_problems(bent) == ["promises victory over every problem"]


# --- Shorts cut from each long story ---


def scenes(n):
    return [ScriptScene(narration=f"Line {i} of the story.", type="broll", mood="faith") for i in range(n)]


def test_cuts_come_from_different_moments_of_the_story():
    assert growth.spread([3, 4, 2, 6], 6, 3) == [3, 6, 4]  # 4 and 2 sit next to 3; 6 doesn't
    assert growth.spread([2, 4, 6], 6, 2) == [2, 4]
    assert growth.spread([9, 1], 6, 3) == [1]


def test_a_cut_waits_until_its_long_video_is_live(cfg, monkeypatch):
    long = Script(
        title="Daniel", description="The story.", tags=[], thumbnail_text="PRAY OR DIE", thumbnail_kicker="Daniel",
        thumbnail_query="lions", scenes=scenes(9), sources=[],
        chapters=[Chapter(title="The trap", scene=0), Chapter(title="The window", scene=3), Chapter(title="The den", scene=6)],
    )
    monkeypatch.setattr(llm, "structured", lambda *a, **k: growth.CutChoice(chapters=[2, 3]))
    live = datetime(2026, 10, 27, 19, 0, tzinfo=timezone.utc)
    pipeline.queue_cuts(cfg, long, "DAN1", live, pillar="stories", style="cinematic")
    topics = Topics(cfg)
    assert pipeline.next_cut(cfg, topics, live - timedelta(hours=1)) is None  # the full video isn't out yet
    _, topic = pipeline.next_cut(cfg, topics, live + timedelta(hours=3))
    assert topic == "cut:DAN1-1"
    assert pipeline.cut_parent(cfg, topic) == {"video_id": "DAN1", "publish_at": live.isoformat(), "pillar": "stories",
                                                "style": "cinematic"}
    cut = pipeline.load_script(cfg.jobs_path / "cuts" / "DAN1-1.json")
    assert cut.description.startswith("Full video: https://youtu.be/DAN1")


def test_story_first_shorts_are_cuts_first_even_without_a_category(cfg, monkeypatch):
    short = cfg.model_copy(update={"format": "short"})
    topics = Topics(cfg)
    topics.add(["cut:VID-1"])
    assert pipeline.next_topic(short, topics, at=datetime(2026, 11, 1, tzinfo=timezone.utc))[1] == "cut:VID-1"


# --- Thumbnails and analytics ---


def test_a_story_thumbnail_names_its_conflict_in_a_few_words(monkeypatch):
    cfg = Config(format="long")
    s = Script(title="Daniel", description="d", tags=[], thumbnail_text="Faith", thumbnail_kicker="Daniel",
               thumbnail_query="q", scenes=scenes(2), sources=[])
    reply = growth.Polish(titles=["Daniel in the Lions' Den"], best_title="Daniel in the Lions' Den",
                          thumbnail_text="PRAY OR DIE", hook="A law was written to trap one man.")
    seen = {}
    monkeypatch.setattr(llm, "structured", lambda cfg, guide, user, schema, **k: seen.update(guide=guide) or reply)
    assert growth.polish(cfg, s, story=True).thumbnail_text == "PRAY OR DIE"
    assert "central conflict" in seen["guide"]
    reply.thumbnail_text = "A NIGHT OF FAITH AND LIONS AND PRAYER"
    assert growth.polish(cfg, s, story=True).thumbnail_text == "Faith"  # too many words: kept as it was


def test_insights_compare_pillars_and_styles(tmp_path):
    cfg = Config(jobs_dir=str(tmp_path))
    rows, meta = [], {}
    for i, (pillar, style, pct, ctr, hold, browse) in enumerate([
        ("stories", "cinematic", 50.0, 0.08, 0.7, 0.5), ("stories", "cinematic", 48.0, 0.06, 0.6, 0.4),
        ("teachings", "illustrated", 30.0, 0.04, 0.5, 0.2), ("questions", "documentary", 40.0, None, None, None),
    ]):
        rows.append({"id": f"v{i}", "views": 500, "view_pct": pct, "avg_seconds": 200 + i, "engaged": 450, "hook": hold,
                     "ctr": ctr, "hold30": hold, "browse": browse, "suggested": 0.1, "subscribed": 0.3})
        meta[f"v{i}"] = {"format": "long", "pillar": pillar, "style": style, "slate": "evergreen" if i < 2 else "timely"}
    lz = insights.lessons(cfg, rows, meta, datetime(2026, 11, 1, tzinfo=timezone.utc))
    stories = lz["pillars"]["stories"]
    assert stories["videos"] == 2 and stories["ctr"] == 0.07 and stories["hold30"] == 0.65 and stories["browse"] == 0.45
    assert lz["pillars"]["questions"]["ctr"] is None  # unknown stays unknown
    assert lz["styles"]["cinematic"]["lift"] > lz["styles"]["illustrated"]["lift"]
    assert set(lz["slates"]) == {"evergreen", "timely"}
    Uploads(cfg).set_note(insights.NOTE, __import__("json").dumps(lz))
    cfg.insights.min_videos = 2
    assert insights.pillar_weights(cfg) == {"stories": pytest.approx(min(1.25, stories["lift"]))}
    report = insights.report(cfg)
    assert "Content pillars" in report and "Visual styles" in report and "cinematic" in report
