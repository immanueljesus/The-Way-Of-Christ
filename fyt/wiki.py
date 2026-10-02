"""Wikipedia as a content source: pick a niche article, fetch its text.

Articles become research notes; the script is written fresh from them in the
channel's own words. Wikipedia text is CC BY-SA 4.0, so every video built from
an article carries an attribution line in its description.
"""

from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from fyt.config import Config

PREFIX = "wiki:"


def user_agent() -> str:
    """Wikimedia asks every client to name itself with a way to reach its operator.
    Set FYT_CONTACT (an email or your repo URL) in .env or the workflow."""
    return f"FaithChannelBot/0.1 ({os.environ.get('FYT_CONTACT') or 'set FYT_CONTACT to your email or repo URL'})"


@dataclass
class Article:
    title: str
    url: str
    text: str

    @property
    def attribution(self) -> str:
        return f'Based on the Wikipedia article "{self.title}" ({self.url}), licensed CC BY-SA 4.0.'


def is_wiki_topic(topic: str) -> bool:
    return topic.startswith(PREFIX)


def topic_for(title: str) -> str:
    return PREFIX + title


def _api(cfg: Config, **params) -> dict:
    for attempt in range(4):  # Wikimedia rate-limits anonymous clients; wait and retry on 429
        r = requests.get(
            f"https://{cfg.wikipedia.lang}.wikipedia.org/w/api.php",
            params={"format": "json", "formatversion": 2, **params},
            headers={"User-Agent": user_agent()},
            timeout=30,
        )
        if getattr(r, "status_code", 200) != 429 or attempt == 3:
            break
        time.sleep(min(60, float(r.headers.get("retry-after") or 10 * (attempt + 1))))
    r.raise_for_status()
    body = r.json()
    if "error" in body:
        raise RuntimeError(f"Wikipedia API error: {body['error'].get('info')}")
    return body


def fetch_article(cfg: Config, title: str) -> Article:
    page = _api(
        cfg,
        action="query",
        prop="extracts|info",
        explaintext=1,
        inprop="url",
        redirects=1,
        titles=title,
    )["query"]["pages"][0]
    if page.get("missing") or not page.get("extract"):
        raise RuntimeError(f"Wikipedia has no article named {title!r}")
    text = _strip_tail(page["extract"])[: cfg.wikipedia.max_chars]
    return Article(title=page["title"], url=page["fullurl"], text=text)


def _strip_tail(text: str) -> str:
    """Drop reference-only sections that add noise to the notes."""
    for heading in ("\n== See also ==", "\n== References ==", "\n== Notes ==", "\n== External links ==", "\n== Further reading =="):
        i = text.find(heading)
        if i != -1:
            text = text[:i]
    return text.strip()


def candidates(cfg: Config) -> list[str]:
    """Article titles from the configured list pages and categories."""
    w = cfg.wikipedia
    titles: list[str] = list(w.articles)
    for page in w.list_pages:
        body = _api(cfg, action="parse", page=page, prop="links", redirects=1)
        titles += [link["title"] for link in body["parse"]["links"] if link["ns"] == 0 and link.get("exists", True)]
    for cat in w.categories:
        cont: dict = {}
        while True:
            body = _api(
                cfg,
                action="query",
                list="categorymembers",
                cmtitle=cat if cat.startswith("Category:") else f"Category:{cat}",
                cmtype="page",
                cmnamespace=0,
                cmlimit=500,
                **cont,
            )
            titles += [m["title"] for m in body["query"]["categorymembers"]]
            if "continue" not in body:
                break
            cont = body["continue"]
    seen, unique = set(), []
    for t in titles:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def pick_articles(cfg: Config, n: int, used: set[str], rng: random.Random | None = None) -> list[str]:
    """Up to n unused article titles with enough text to make a video from."""
    pool = [t for t in candidates(cfg) if topic_for(t) not in used]
    (rng or random).shuffle(pool)
    picked: list[str] = []
    for title in pool:
        if len(picked) >= n:
            break
        try:
            article = fetch_article(cfg, title)
        except Exception as e:
            print(f"skipping {title}: {e}")
            continue
        if len(article.text) >= cfg.wikipedia.min_chars and topic_for(article.title) not in used:
            picked.append(article.title)
    return picked


def notes(article: Article) -> str:
    return f"# {article.title}\nSource: {article.url}\n\n{article.text}"


@dataclass
class WikiImage:
    title: str  # "File:..."
    url: str  # resized image URL
    page: str  # file description page (for credits)
    description: str
    artist: str
    license: str

    @property
    def credit(self) -> str:
        who = f"{self.artist}, " if self.artist else ""
        return f"{self.title.removeprefix('File:')} ({who}{self.license or 'see page'}): {self.page}"


SKIP_WORDS = ("logo", "icon", "symbol", "signature", "wiki", "commons-", "question_book", "edit-clear", "ambox")


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def fetch_images(cfg: Config, title: str, limit: int = 8) -> list[WikiImage]:
    """Photos used in the article, largest first, sized for the video."""
    body = _api(
        cfg,
        action="query",
        generator="images",
        titles=title,
        redirects=1,
        gimlimit=50,
        prop="imageinfo",
        iiprop="url|size|mime|extmetadata",
        iiurlwidth=1280,
    )
    images = []
    for page in body.get("query", {}).get("pages", []):
        info = (page.get("imageinfo") or [{}])[0]
        name = page.get("title", "")
        if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue  # skips SVG diagrams, maps-as-SVG, audio, video
        if min(info.get("width", 0), info.get("height", 0)) < 400:
            continue
        if any(w in name.lower() for w in SKIP_WORDS):
            continue
        meta = info.get("extmetadata", {})
        about = (name + " " + _plain(meta.get("ImageDescription", {}).get("value", ""))).lower()
        if any(w.lower() in about for w in cfg.wikipedia.image_skip_words):
            continue
        images.append(
            WikiImage(
                title=name,
                url=info.get("thumburl") or info["url"],
                page=info.get("descriptionurl", ""),
                description=_plain(meta.get("ImageDescription", {}).get("value", ""))[:120]
                or name.removeprefix("File:").rsplit(".", 1)[0].replace("_", " "),
                artist=_plain(meta.get("Artist", {}).get("value", ""))[:80],
                license=_plain(meta.get("LicenseShortName", {}).get("value", "")),
            )
        )
    images.sort(key=lambda im: len(im.description), reverse=True)  # described images first
    return images[:limit]


def image_menu(images: list[WikiImage]) -> str:
    """The numbered list the scriptwriter picks from."""
    return "\n".join(f"{i}. {im.description}" for i, im in enumerate(images, 1))


def download_image(image: WikiImage, dst: Path) -> None:
    for attempt in range(4):  # upload.wikimedia.org rate-limits bursts of downloads
        with requests.get(image.url, headers={"User-Agent": user_agent()}, stream=True, timeout=60) as r:
            if r.status_code == 429 and attempt < 3:
                time.sleep(min(60, float(r.headers.get("retry-after") or 10 * (attempt + 1))))
                continue
            r.raise_for_status()
            with dst.open("wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
            return
