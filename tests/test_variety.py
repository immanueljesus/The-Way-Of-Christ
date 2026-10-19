"""Visual variety: stock footage and paintings aren't repeated across recent videos, and
Bible paintings from Wikimedia Commons are mixed in with the footage."""

from fyt import media, pipeline, wiki
from fyt.catalog import Idea
from fyt.config import Config
from fyt.models import Script
from fyt.store import Job, MediaHistory


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def test_media_history_remembers_recent_media_only(tmp_path):
    cfg = Config(jobs_dir=str(tmp_path))
    h = MediaHistory(cfg)
    h.add({"123", "p9"})
    h.add(["old"], at="2000-01-01T00:00:00+00:00")
    assert MediaHistory(cfg).recent(60) == {"123", "p9"}
    assert h.recent(0) == set()


def test_stock_skips_clips_used_before_and_varies_the_pick(tmp_path, monkeypatch):
    videos = [
        {"id": n, "duration": 10, "url": f"https://pexels.com/video/clip-{n}/",
         "video_files": [{"file_type": "video/mp4", "width": 1080, "height": 1920, "link": f"https://v/{n}.mp4"}]}
        for n in range(1, 21)
    ]
    asked = []
    monkeypatch.setattr(media, "_get", lambda path, params: asked.append(params) or {"videos": videos})
    monkeypatch.setattr(media, "_download", lambda url, dst: dst.write_bytes(b"mp4"))
    cfg = Config(format="short")
    picks = set()
    for _ in range(30):
        used = {"1", "2", "3"}
        assert media._stock(cfg, "sunrise", tmp_path, "s1", used).kind == "video"
        (new,) = used - {"1", "2", "3"}
        assert int(new) <= 3 + media.PICK_FROM  # one of the best unused matches
        picks.add(new)
    assert len(picks) > 1  # the same search doesn't always give the same clip
    assert asked[0]["per_page"] == media.PER_PAGE


def test_mood_fallbacks_start_from_a_different_search_per_video():
    assert media.mood_queries("hope", 0, 1)[0] == media.mood_queries("hope", 1)[0]
    assert sorted(media.mood_queries("hope", 2, 3)) == sorted(media.MOOD_QUERIES["hope"])


def commons_page(title, license="Public domain", w=1200, h=1600, mime="image/jpeg", index=1):
    return {
        "title": title,
        "index": index,
        "imageinfo": [{
            "mime": mime, "width": w, "height": h,
            "url": f"https://upload.wikimedia.org/{title}",
            "thumburl": f"https://upload.wikimedia.org/thumb/{title}",
            "descriptionurl": f"https://commons.wikimedia.org/wiki/{title}",
            "extmetadata": {
                "ImageDescription": {"value": title.removeprefix("File:")},
                "Artist": {"value": "Rembrandt"},
                "LicenseShortName": {"value": license},
            },
        }],
    }


def test_search_art_keeps_free_unused_paintings(monkeypatch):
    pages = [
        commons_page("File:Storm on the Sea of Galilee.jpg", index=1),
        commons_page("File:Christ in the storm.jpg", license="CC BY-SA 4.0", index=2),
        commons_page("File:Modern photo.jpg", license="CC BY-NC 2.0", index=3),
        commons_page("File:Tiny.jpg", w=300, h=300, index=4),
        commons_page("File:Sea map.jpg", index=5),  # image_skip_words: map
        commons_page("File:Shown last week.jpg", index=6),
    ]
    calls = []

    def get(url, params, headers, timeout):
        assert "commons.wikimedia.org" in url and headers["User-Agent"]
        calls.append(params["gsrsearch"])
        return FakeResponse({"query": {"pages": pages}})

    monkeypatch.setattr(wiki.requests, "get", get)
    cfg = Config()
    cfg.wikipedia.image_skip_words = ["map"]
    art = wiki.search_art(cfg, ["Jesus storm", "Jesus"], limit=5, skip={"art:File:Shown last week.jpg"})
    assert sorted(a.title for a in art) == ["File:Christ in the storm.jpg", "File:Storm on the Sea of Galilee.jpg"]
    assert calls[0].startswith("Jesus storm painting")
    assert len(calls) == 2  # not enough from the first search: the broader one is tried too
    assert "Rembrandt" in art[0].credit


def test_art_queries_name_the_figure_and_the_story():
    idea = Idea(id="x", title="Why Jesus Slept in the Storm", category="jesus", character="Jesus")
    assert pipeline.art_queries(idea, idea.title) == ["Jesus Slept Storm", "Jesus"]
    idea = Idea(id="y", title="The Cupbearer Forgot Joseph", category="motivation", character="Joseph")
    assert pipeline.art_queries(idea, idea.title) == ["Cupbearer Forgot Joseph", "Joseph"]
    assert pipeline.art_queries(None, "Peace in the storm") == ["Peace storm"]


def test_scene_visuals_skip_and_remember_what_was_shown(monkeypatch, tmp_path):
    cfg = Config(jobs_dir=str(tmp_path / "jobs"))
    MediaHistory(cfg).add({"111"})
    images = [wiki.WikiImage("File:A.jpg", "https://x/A.jpg", "https://c/A", "storm", "", "Public domain")]
    monkeypatch.setattr(wiki, "download_image", lambda im, dst: dst.write_bytes(b"jpg"))
    seen_used = []

    def broll(cfg, q, public, name, used):
        seen_used.append(set(used))
        used.add("222")
        return media.Media(src=f"media/{name}.mp4", kind="video")

    monkeypatch.setattr(media, "fetch_broll", broll)
    s = Script.model_validate({
        "title": "t", "description": "d", "tags": [], "thumbnail_text": "x", "thumbnail_kicker": "y",
        "thumbnail_query": "z", "sources": [],
        "scenes": [
            {"narration": "a", "type": "broll", "image": 1},
            {"narration": "b", "type": "broll", "broll_query": "boat storm"},
        ],
    })
    job = Job(tmp_path / "job")
    job.public.mkdir(parents=True)
    scene_media, credits, _ = pipeline.scene_visuals(cfg, job, s, images, "topic")
    assert scene_media[0].kind == "image" and scene_media[1].kind == "video"
    assert "111" in seen_used[0]  # footage from a recent video isn't picked again
    assert MediaHistory(cfg).recent(60) >= {"111", "222", "art:File:A.jpg"}


def test_shorts_cut_every_few_seconds_long_videos_hold_the_shot():
    short = Config(format="short")
    assert pipeline.shot_count(short, 2.5) == 1
    assert pipeline.shot_count(short, 7) == 2
    assert pipeline.shot_count(short, 20) == short.max_shots
    assert pipeline.shot_count(Config(format="long"), 20) == 1
    assert pipeline.shot_count(Config(format="short", shot_seconds=0), 20) == 1


def test_scene_shots_follow_a_painting_with_a_close_up_then_footage(monkeypatch, tmp_path):
    cfg = Config(format="short", jobs_dir=str(tmp_path / "jobs"))
    fetched = []

    def broll(cfg, q, public, name, used):
        fetched.append(name)
        used.add(f"id-{name}")
        return media.Media(src=f"media/{name}.mp4", kind="video")

    monkeypatch.setattr(media, "fetch_broll", broll)
    s = Script.model_validate({
        "title": "t", "description": "d", "tags": [], "thumbnail_text": "x", "thumbnail_kicker": "y",
        "thumbnail_query": "z", "sources": [],
        "scenes": [
            {"narration": "a", "type": "broll", "image": 1, "broll_query": "boat storm"},
            {"narration": "b", "type": "broll", "broll_query": "sunrise"},
            {"narration": "c", "type": "quote", "text": "q", "broll_query": "candle"},
        ],
    })
    scene_media = {
        0: media.Media(src="media/wiki1.jpg", kind="image"),
        1: media.Media(src="media/s2.mp4", kind="video"),
        2: media.Media(src="media/s3.mp4", kind="video"),
    }
    spans = [(0.0, 10.0), (10.5, 13.0), (13.5, 20.0)]  # scene 1: ~10.5 s, scene 2: 3 s
    job = Job(tmp_path / "job")
    job.public.mkdir(parents=True)
    shots = pipeline.scene_shots(cfg, job, s, scene_media, spans, set())
    assert shots[0][0].src == "media/wiki1.jpg" and shots[0][0].detail  # close-up of the painting
    assert shots[0][1].kind == "video" and fetched == ["s1c"]
    assert 1 not in shots and 2 not in shots  # short scene keeps one shot; text scenes stay still
    assert "id-s1c" in MediaHistory(cfg).recent(60)


def test_render_props_carry_the_extra_shots():
    from fyt.timeline import build_props

    s = Script.model_validate({
        "title": "t", "description": "d", "tags": [], "thumbnail_text": "x", "thumbnail_kicker": "y",
        "thumbnail_query": "z", "sources": [],
        "scenes": [{"narration": "a", "type": "broll"}, {"narration": "b", "type": "broll"}],
    })
    m = media.Media(src="media/a.jpg", kind="image")
    extra = [media.Media(src="media/a.jpg", kind="image", detail=True)]
    props = build_props(Config(format="short"), s, [(0, 5), (5, 9)], [[], []], {0: m}, None, None, shots={0: extra, 1: extra})
    assert props.scenes[0].shots == extra
    assert props.scenes[1].shots is None  # no picture, no shots
