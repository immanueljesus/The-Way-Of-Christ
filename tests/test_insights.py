"""The analytics feedback loop: YouTube Analytics -> weekly lessons -> topic, title and script choices."""

import json
from datetime import datetime, timedelta, timezone

from fyt import catalog, insights, llm, youtube
from fyt.config import Config
from fyt.models import Script
from fyt.store import Uploads

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def rows_and_meta():
    """Five Shorts (prayer holds viewers, motivation loses them) and three long videos."""
    shorts = [  # (id, category, title style, views, engaged)
        ("s1", "prayer", "prayer", 100, 50), ("s2", "prayer", "prayer", 100, 55), ("s3", "prayer", "prayer", 100, 52),
        ("s4", "motivation", "direct", 100, 30), ("s5", "motivation", "direct", 100, 35),
    ]
    rows = [{"id": i, "views": v, "view_pct": 80.0, "avg_seconds": 40, "engaged": e, "hook": None} for i, _, _, v, e in shorts]
    meta = {i: {"format": "short", "category": c, "title_style": t, "shape": "prayer" if c == "prayer" else "journey",
                "title": f"Short {i}"} for i, c, t, _, _ in shorts}
    for i, pct, hook in (("l1", 30.0, 0.5), ("l2", 40.0, 0.6), ("l3", 50.0, 0.7)):
        rows.append({"id": i, "views": 500, "view_pct": pct, "avg_seconds": 200, "engaged": 450, "hook": hook})
        meta[i] = {"format": "long", "category": "bible_story", "title_style": "cinematic", "shape": "story", "title": f"Long {i}"}
    rows.append({"id": "tiny", "views": 3, "view_pct": 99.0, "avg_seconds": 50, "engaged": 3, "hook": None})  # too few views
    meta["tiny"] = {"format": "short", "category": "wisdom"}
    return rows, meta


def config(tmp_path) -> Config:
    cfg = Config(jobs_dir=str(tmp_path))
    cfg.insights.min_videos = 2
    return cfg


def test_lessons_compare_each_video_with_its_own_format(tmp_path):
    cfg = config(tmp_path)
    lz = insights.lessons(cfg, *rows_and_meta(), NOW)
    assert lz["videos"] == 8  # the 3-view video says too little
    short = lz["formats"]["short"]
    assert short["median_swipe_away"] == 0.5 and lz["formats"]["long"]["median_hook_hold"] == 0.6
    assert lz["categories"]["prayer"]["lift"] > 1 > lz["categories"]["motivation"]["lift"]
    assert "wisdom" not in lz["categories"]
    assert lz["best"][0]["category"] in ("prayer", "bible_story")
    # Plain delivery notes, always with the Bible-first guard.
    assert "swipe away" in lz["notes"]["short"] and insights.GUARD in lz["notes"]["short"]
    assert "a tenth of the way in" in lz["notes"]["long"]


def test_stored_lessons_steer_mix_and_title_styles_within_bounds(tmp_path):
    cfg = config(tmp_path)
    assert insights.category_weights(cfg) == {} and insights.script_notes(cfg, "short") == ""  # before any refresh
    Uploads(cfg).set_note(insights.NOTE, json.dumps(insights.lessons(cfg, *rows_and_meta(), NOW)))
    w = insights.category_weights(cfg)
    assert w["motivation"] == cfg.insights.min_weight  # lost viewers: clamped, never zeroed
    assert 1 < w["prayer"] <= cfg.insights.max_weight
    prefer, avoid = insights.title_preferences(cfg)
    assert "direct" in avoid and "direct" not in prefer
    assert "swipe away" in insights.script_notes(cfg, "short")
    assert "Held viewers best" in insights.summary(cfg)
    assert "Content mix nudges" in insights.report(cfg)
    cfg.insights.enabled = False
    assert insights.category_weights(cfg) == {}


def test_weights_nudge_the_next_pillar(tmp_path):
    cfg = Config(jobs_dir=str(tmp_path), format="short")
    cfg.catalog.mix = {"prayer": 50, "motivation": 50}
    first = catalog.pick(cfg, set()).category
    other = "motivation" if first == "prayer" else "prayer"
    assert catalog.pick(cfg, set(), weights={other: 1.25, first: 0.8}).category == other


def test_title_styles_viewers_stay_with_go_first_but_none_disappear():
    assert llm.choose_title_style("journey") == "verse"
    assert llm.choose_title_style("journey", prefer=["question"]) == "question"
    assert llm.choose_title_style("journey", avoid=["verse"]) == "direct"
    # Avoided styles stay available when everything else was used recently.
    assert llm.choose_title_style("prayer", recent=["prayer"], avoid=["prayer"]) == "prayer"


def test_script_writer_hears_the_lessons(monkeypatch):
    cfg = Config(format="short")
    cfg.llm.provider = "openai"
    seen = []
    script = Script(title="t", description="d", tags=[], thumbnail_text="x", thumbnail_kicker="k", thumbnail_query="q",
                    scenes=[], sources=[])
    monkeypatch.setattr(llm, "_openai_structured", lambda cfg, system, user, schema, max_tokens=0: seen.append(system) or script)
    llm.write_script(cfg, "topic", "notes", lessons="- Open on the moment.\n" + insights.GUARD)
    assert "What this channel's viewers have shown" in seen[0] and insights.GUARD in seen[0]
    llm.write_script(cfg, "topic", "notes")
    assert "What this channel's viewers have shown" not in seen[1]


class FakeAnalytics:
    """Stands in for the YouTube Analytics API (reports().query(...).execute())."""

    def __init__(self, engaged=True):
        self.engaged, self.queries = engaged, []

    def reports(self):
        return self

    def query(self, **kw):
        self.queries.append(kw)
        if "engagedViews" in kw["metrics"] and not self.engaged:
            raise RuntimeError("Unknown identifier (engagedViews)")
        if kw["metrics"] == "audienceWatchRatio":
            body = {"rows": [[0.0, 1.0], [0.1, 0.62], [0.2, 0.5]]}
        else:
            names = kw["metrics"].split(",")
            body = {
                "columnHeaders": [{"name": "video"}] + [{"name": n} for n in names],
                "rows": [["L1", 400, 41.5, 180] + ([360] if "engagedViews" in names else []),
                         ["S1", 900, 85.0, 40] + ([500] if "engagedViews" in names else [])],
            }
        return type("Req", (), {"execute": lambda self_: body})()


def test_fetch_reads_views_and_retention_and_survives_missing_engaged_views(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    Uploads(cfg).record("long", "j1", "L1", None)
    Uploads(cfg).record("short", "j2", "S1", None)
    fake = FakeAnalytics()
    monkeypatch.setattr(youtube, "analytics_service", lambda: fake)
    rows = {r["id"]: r for r in insights.fetch(cfg, NOW)}
    assert rows["S1"]["engaged"] == 500 and abs(insights.swipe_away(rows["S1"]) - 4 / 9) < 1e-9
    assert rows["L1"]["hook"] == 0.62 and rows["S1"]["hook"] is None  # retention read for long videos only
    assert fake.queries[0]["endDate"] == "2026-10-17"
    fake = FakeAnalytics(engaged=False)
    monkeypatch.setattr(youtube, "analytics_service", lambda: fake)
    rows = {r["id"]: r for r in insights.fetch(cfg, NOW)}
    assert rows["S1"]["engaged"] is None and insights.swipe_away(rows["S1"]) is None


def test_refresh_runs_weekly_and_needs_the_analytics_permission(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    rows, meta = rows_and_meta()
    for vid, m in meta.items():
        Uploads(cfg).describe(vid, **m)
    monkeypatch.setattr(insights, "fetch", lambda cfg, now: rows)
    monkeypatch.setattr(youtube, "can_analyze", lambda: False)
    assert insights.refresh(cfg, NOW) is None  # no permission yet: skipped, nothing breaks
    monkeypatch.setattr(youtube, "can_analyze", lambda: True)
    assert insights.refresh(cfg, NOW)["videos"] == 8
    assert insights.refresh(cfg, NOW + timedelta(days=3)) is None  # learned this week already
    assert insights.refresh(cfg, NOW + timedelta(days=7, minutes=1)) is not None
