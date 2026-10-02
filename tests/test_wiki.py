import random

from fyt import pipeline, wiki
from fyt.config import Config
from fyt.models import Script


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def fake_api(monkeypatch, pages):
    """pages: title -> extract text. The list page links to every title."""

    def get(url, params, headers, timeout):
        assert "wikipedia.org" in url and headers["User-Agent"]
        if params["action"] == "parse":
            links = [{"ns": 0, "title": t, "exists": True} for t in pages] + [{"ns": 4, "title": "Wikipedia:Foo"}]
            return FakeResponse({"parse": {"links": links}})
        title = params["titles"]
        if title not in pages:
            return FakeResponse({"query": {"pages": [{"title": title, "missing": True}]}})
        url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")
        return FakeResponse({"query": {"pages": [{"title": title, "fullurl": url, "extract": pages[title]}]}})

    monkeypatch.setattr(wiki.requests, "get", get)


def test_fetch_article_strips_reference_sections(monkeypatch):
    fake_api(monkeypatch, {"Boston Molasses Disaster": "Intro.\n\n== History ==\nFacts.\n\n== References ==\nJunk"})
    a = wiki.fetch_article(Config(), "Boston Molasses Disaster")
    assert a.text == "Intro.\n\n== History ==\nFacts."
    assert a.url.endswith("/Boston_Molasses_Disaster")
    assert "CC BY-SA 4.0" in a.attribution


def test_pick_articles_skips_used_and_stubs(monkeypatch):
    long = "x" * 5000
    fake_api(monkeypatch, {"Used one": long, "Stub": "short", "Fresh": long, "Also fresh": long})
    used = {wiki.topic_for("Used one")}
    picked = wiki.pick_articles(Config(), 5, used, random.Random(0))
    assert sorted(picked) == ["Also fresh", "Fresh"]


def test_wiki_attribution_added_once():
    a = wiki.Article(title="Tardigrade", url="https://en.wikipedia.org/wiki/Tardigrade", text="...")
    s = Script.model_validate(
        {
            "title": "t",
            "description": "About water bears.",
            "tags": [],
            "thumbnail_text": "x",
            "thumbnail_kicker": "y",
            "thumbnail_query": "z",
            "sources": [],
            "scenes": [{"narration": "Hi.", "type": "title", "heading": "Hi"}],
        }
    )
    once = pipeline.wiki_attribute(s, a)
    twice = pipeline.wiki_attribute(once, a)
    assert twice.description.count("CC BY-SA 4.0") == 1
    assert twice.sources == [a.url]


def test_upload_sheet_has_title_description_and_credit():
    from fyt import youtube

    a = wiki.Article(title="Tardigrade", url="https://en.wikipedia.org/wiki/Tardigrade", text="...")
    s = Script.model_validate(
        {
            "title": "The animal that survives space",
            "description": "About water bears.",
            "tags": ["tardigrade", "science"],
            "thumbnail_text": "x",
            "thumbnail_kicker": "y",
            "thumbnail_query": "z",
            "sources": [],
            "scenes": [{"narration": "Hi.", "type": "title", "heading": "Hi"}],
        }
    )
    cfg = Config(format="short")
    sheet = youtube.upload_sheet(cfg, pipeline.wiki_attribute(s, a))
    assert sheet.startswith("TITLE\nThe animal that survives space\n")
    assert "CC BY-SA 4.0" in sheet and "#Shorts" in sheet and "tardigrade, science" in sheet


def test_fetch_images_keeps_real_photos(monkeypatch):
    def img(title, mime="image/jpeg", w=2000, h=1500, desc=""):
        return {
            "title": title,
            "imageinfo": [
                {
                    "mime": mime,
                    "width": w,
                    "height": h,
                    "url": f"https://upload.wikimedia.org/{title}",
                    "thumburl": f"https://upload.wikimedia.org/thumb/{title}",
                    "descriptionurl": f"https://commons.wikimedia.org/wiki/{title}",
                    "extmetadata": {
                        "ImageDescription": {"value": desc},
                        "Artist": {"value": "<a href='x'>Jane Doe</a>"},
                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                    },
                }
            ],
        }

    pages = [
        img("File:Tank ruins 1919.jpg", desc="<b>Ruins</b> of the molasses tank, 1919"),
        img("File:Map.svg", mime="image/svg+xml"),
        img("File:Tiny.jpg", w=200, h=150),
        img("File:Commons-logo.png", mime="image/png"),
        img("File:Harbor.jpg"),
    ]
    monkeypatch.setattr(
        wiki.requests, "get", lambda url, params, headers, timeout: FakeResponse({"query": {"pages": pages}})
    )
    images = wiki.fetch_images(Config(), "Boston Molasses Disaster")
    assert [i.title for i in images] == ["File:Tank ruins 1919.jpg", "File:Harbor.jpg"]
    assert images[0].description == "Ruins of the molasses tank, 1919"
    assert images[0].url.startswith("https://upload.wikimedia.org/thumb/")
    assert "Jane Doe" in images[0].credit and "CC BY-SA 4.0" in images[0].credit
    assert wiki.image_menu(images).startswith("1. Ruins of the molasses tank, 1919\n2. Harbor")


def test_scene_visuals_uses_chosen_images_then_stock(monkeypatch, tmp_path):
    from fyt import media
    from fyt.store import Job

    images = [
        wiki.WikiImage("File:A.jpg", "https://x/A.jpg", "https://c/A", "tank", "Jane", "CC BY 4.0"),
        wiki.WikiImage("File:B.jpg", "https://x/B.jpg", "https://c/B", "harbor", "", "Public domain"),
    ]
    monkeypatch.setattr(wiki, "download_image", lambda im, dst: dst.write_bytes(b"jpg"))
    stock = []
    monkeypatch.setattr(media, "fetch_broll", lambda cfg, q, public, name, used: stock.append(q) or None)
    s = Script.model_validate(
        {
            "title": "t",
            "description": "d",
            "tags": [],
            "thumbnail_text": "x",
            "thumbnail_kicker": "y",
            "thumbnail_query": "z",
            "sources": [],
            "scenes": [
                {"narration": "a", "type": "title", "heading": "a", "image": 2},
                {"narration": "b", "type": "statement", "text": "b", "image": 2, "broll_query": "flood street"},
                {"narration": "c", "type": "stat", "value": 21, "image": 9},
            ],
        }
    )
    job = Job(tmp_path / "job")
    job.public.mkdir(parents=True)
    scene_media, credits, _ = pipeline.scene_visuals(Config(), job, s, images, "topic")
    assert scene_media[0].src == "media/wiki2.jpg"
    assert 1 not in scene_media and stock == [["flood street"]]  # image 2 already used -> stock
    assert 2 not in scene_media  # out-of-range image, data scene: plain background
    assert credits == ["B.jpg (Public domain): https://c/B"]
