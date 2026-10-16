"""YouTube Data API v3: OAuth, upload (video + thumbnail + captions), stats.

Setup (once): create an OAuth client of type "Desktop app" in Google Cloud with
the YouTube Data API v3 enabled, save it as secrets/client_secret.json, then run
`python -m fyt auth`.

Note: Google may lock uploads from an unaudited API project to private
(see README).
"""

from __future__ import annotations

import json
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fyt.config import ROOT, Config
from fyt.models import Script

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",  # captions + stats
    "https://www.googleapis.com/auth/yt-analytics.readonly",  # retention and % viewed (fyt/insights.py)
]
ANALYTICS_SCOPE = SCOPES[2]
SECRETS = ROOT / "secrets"
CLIENT_SECRET = SECRETS / "client_secret.json"
TOKEN = SECRETS / "token.json"
MIN_PUBLISH_LEAD_MINUTES = 15
RETRIABLE_STATUS = {500, 502, 503, 504}


def auth() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CLIENT_SECRET.exists():
        raise SystemExit(f"Missing {CLIENT_SECRET}. Download a Desktop OAuth client JSON from Google Cloud.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    print(f"Saved credentials to {TOKEN}")


def authorised() -> bool:
    """Whether uploads can run: a token from `fyt auth` or the YOUTUBE_TOKEN_JSON secret."""
    return TOKEN.exists() or bool(os.environ.get("YOUTUBE_TOKEN_JSON", "").strip())


FULL_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"


def _token_scopes() -> list[str]:
    try:
        raw = TOKEN.read_text(encoding="utf-8") if TOKEN.exists() else os.environ.get("YOUTUBE_TOKEN_JSON", "")
        scopes = json.loads(raw).get("scopes")
    except (OSError, ValueError):
        return []
    return scopes.split() if isinstance(scopes, str) else list(scopes or [])


def can_manage() -> bool:
    """Whether the token may do more than upload (caption tracks, playlists, stats).
    Tokens made with only the upload scope get 403 for those."""
    scopes = _token_scopes()  # unknown scopes: don't spend quota on calls that may be refused
    return FULL_SCOPE in scopes or "https://www.googleapis.com/auth/youtube" in scopes


def can_analyze() -> bool:
    """Whether the token may read YouTube Analytics (made by `fyt auth` after the analytics scope was added)."""
    return ANALYTICS_SCOPE in _token_scopes()


def add_to_playlist(video_id: str, name: str, privacy: str = "public") -> None:
    """File the video under a playlist with this name, creating it the first time."""
    yt = _service()
    playlist_id = None
    request = yt.playlists().list(part="snippet", mine=True, maxResults=50)
    while request is not None and playlist_id is None:
        resp = request.execute()
        playlist_id = next((p["id"] for p in resp.get("items", []) if p["snippet"]["title"] == name), None)
        request = yt.playlists().list_next(request, resp)
    if playlist_id is None:
        playlist_id = yt.playlists().insert(
            part="snippet,status", body={"snippet": {"title": name}, "status": {"privacyStatus": privacy}}
        ).execute()["id"]
    yt.playlistItems().insert(
        part="snippet", body={"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}
    ).execute()


def _service():
    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=_credentials(), cache_discovery=False)


def analytics_service():
    """The YouTube Analytics API (free; its quota is separate from the Data API's upload quota)."""
    from googleapiclient.discovery import build

    return build("youtubeAnalytics", "v2", credentials=_credentials(), cache_discovery=False)


def _credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    # In CI the token comes from a secret; locally from `fyt auth`.
    if not TOKEN.exists() and os.environ.get("YOUTUBE_TOKEN_JSON", "").strip():
        SECRETS.mkdir(exist_ok=True)
        TOKEN.write_text(os.environ["YOUTUBE_TOKEN_JSON"], encoding="utf-8")
    if not TOKEN.exists():
        raise SystemExit("Not authorised. Run `python -m fyt auth` first.")
    # No scopes here: refreshing then keeps whatever the login granted. Asking for
    # scopes the token wasn't granted (e.g. one made in the OAuth Playground)
    # fails with invalid_scope.
    creds = Credentials.from_authorized_user_file(str(TOKEN))
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def publish_time(cfg: Config, now: datetime | None = None, rng: random.Random | None = None) -> datetime | None:
    """When a scheduled upload goes public, or None to publish right away."""
    y = cfg.youtube
    if y.publish_delay_hours is None and not y.publish_jitter_minutes:
        return None
    delay = timedelta(hours=y.publish_delay_hours or 0)
    if y.publish_jitter_minutes:
        delay += timedelta(minutes=(rng or random).uniform(0, y.publish_jitter_minutes))
    # YouTube needs publishAt in the future, with some room for the upload itself.
    delay = max(delay, timedelta(minutes=MIN_PUBLISH_LEAD_MINUTES))
    return (now or datetime.now(timezone.utc)) + delay


def build_body(
    cfg: Config,
    script: Script,
    now: datetime | None = None,
    rng: random.Random | None = None,
    publish_at: datetime | None = None,
    localizations: dict[str, dict] | None = None,
) -> dict:
    """The videos.insert body. `localizations` ({language: {title, description, footer}}, from
    fyt/localize.py) become the video's translated titles and descriptions."""
    status = {
        "privacyStatus": cfg.youtube.privacy,
        "selfDeclaredMadeForKids": cfg.youtube.made_for_kids,
        "containsSyntheticMedia": cfg.youtube.contains_synthetic_media,
    }
    publish = publish_at or publish_time(cfg, now, rng)
    if publish is not None:
        status["privacyStatus"] = "private"  # required for scheduled publishing
        status["publishAt"] = publish.strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "snippet": {
            "title": script.title[:100],
            "description": full_description(cfg, script)[:5000],
            "tags": script.tags,
            "categoryId": cfg.youtube.category_id,
            "defaultLanguage": cfg.channel.language,
            "defaultAudioLanguage": cfg.channel.language,
        },
        "status": status,
    }
    if localizations:
        body["localizations"] = {
            lang: {
                "title": loc["title"][:100],
                "description": full_description(cfg, script, loc["description"], loc.get("footer", ""), lang)[:5000],
            }
            for lang, loc in localizations.items()
        }
    return body


def full_description(
    cfg: Config, script: Script, description: str | None = None, footer: str | None = None, language: str = "en"
) -> str:
    """The description as uploaded: the script's (or a translated) description, sources, series, footer."""
    from fyt.localize import LABELS

    sources, series = LABELS.get(language, LABELS["en"])
    out = (script.description if description is None else description).strip()
    if script.sources:
        out += f"\n\n{sources}:\n" + "\n".join(f"- {s}" for s in script.sources)
    if script.series:
        out += f"\n\n{series}: {script.series}"
    footer = cfg.channel.description_footer if footer is None else footer
    if footer.strip():
        out += "\n\n" + footer.strip()
    if cfg.format == "short":
        out += "\n\n#Shorts"
    return out


def upload_sheet(
    cfg: Config, script: Script, localizations: dict[str, dict] | None = None, thumbnails: list[str] | None = None
) -> str:
    """Title, description and tags to paste into YouTube Studio for a manual upload, plus the steps
    the API can't do (thumbnail Test & compare, a Short's related video)."""
    body = build_body(cfg, script, localizations=localizations)
    snippet = body["snippet"]
    out = (
        f"TITLE\n{snippet['title']}\n\n"
        f"DESCRIPTION\n{snippet['description']}\n\n"
        f"TAGS\n{', '.join(snippet['tags'])}\n\n"
        "Also: upload thumbnail.png as the thumbnail and captions.srt as subtitles. Under\n"
        "\"Altered or synthetic content\" answer No unless the video shows realistic AI-generated\n"
        "people, places or events (see youtube.contains_synthetic_media in channel.yaml).\n"
    )
    if thumbnails and len(thumbnails) > 1:
        out += (
            f"\nTHUMBNAIL TEST: in YouTube Studio open the video > Thumbnail > Test & compare, and add\n"
            f"{', '.join(thumbnails)}. YouTube shows each to viewers and keeps the one watched most.\n"
        )
    link = re.match(r"Full video: (https://youtu\.be/\S+)", script.description)
    if link and cfg.format == "short":
        out += (
            f"\nRELATED VIDEO: in YouTube Studio open this Short > Related video, and pick {link[1]}\n"
            "so the link to the full video shows on the Short itself.\n"
        )
    for lang, loc in (body.get("localizations") or {}).items():
        out += f"\nTITLE ({lang})\n{loc['title']}\n\nDESCRIPTION ({lang})\n{loc['description']}\n"
    return out


def upload(
    cfg: Config,
    script: Script,
    video: Path,
    thumbnail: Path | None,
    srt: Path | None,
    publish_at: datetime | None = None,
    localizations: dict[str, dict] | None = None,
) -> str:
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    yt = _service()
    request = yt.videos().insert(
        part="snippet,status" + (",localizations" if localizations else ""),
        body=build_body(cfg, script, publish_at=publish_at, localizations=localizations),
        media_body=MediaFileUpload(str(video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True),
    )
    response, failures = None, 0
    while response is None:
        try:
            status, response = request.next_chunk()
        except (HttpError, OSError) as e:
            # A resumable upload picks up where it stopped; retry server errors and dropped connections.
            retriable = not isinstance(e, HttpError) or e.status_code in RETRIABLE_STATUS
            failures += 1
            if not retriable or failures > 5:
                raise
            wait = min(2**failures, 60)
            print(f"upload interrupted ({e}); retrying in {wait}s")
            time.sleep(wait)
            continue
        if status:
            print(f"upload {int(status.progress() * 100)}%")
    video_id = response["id"]
    print(f"uploaded https://youtu.be/{video_id}")

    if thumbnail and thumbnail.exists():
        try:
            yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumbnail))).execute()
        except HttpError as e:  # custom thumbnails need a phone-verified channel
            print(f"warning: thumbnail not set ({e.status_code}); verify the channel at youtube.com/verify")
    if srt and srt.exists() and cfg.youtube.upload_captions and can_manage():
        try:
            yt.captions().insert(
                part="snippet",
                body={"snippet": {"videoId": video_id, "language": cfg.channel.language, "name": "", "isDraft": False}},
                media_body=MediaFileUpload(str(srt), mimetype="application/octet-stream"),
            ).execute()
        except HttpError as e:  # the video is up; missing captions shouldn't fail the run
            print(f"warning: captions not uploaded ({e.status_code})")
    return video_id


def stats(video_ids: list[str]) -> list[dict]:
    yt = _service()
    out = []
    for i in range(0, len(video_ids), 50):
        resp = yt.videos().list(part="snippet,statistics", id=",".join(video_ids[i : i + 50])).execute()
        for item in resp.get("items", []):
            s = item.get("statistics", {})
            out.append(
                {
                    "id": item["id"],
                    "title": item["snippet"]["title"],
                    "views": int(s.get("viewCount", 0)),
                    "likes": int(s.get("likeCount", 0)),
                    "comments": int(s.get("commentCount", 0)),
                }
            )
    return out


def recent_uploads(limit: int = 100) -> list[dict]:
    """The channel's newest uploads, scheduled ones included: id, publish_at (or None), description.
    Costs a few quota units; needs more than the upload-only scope."""
    yt = _service()
    channel = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    uploads = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    ids: list[str] = []
    request = yt.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=50)
    while request is not None and len(ids) < limit:
        resp = request.execute()
        ids += [i["contentDetails"]["videoId"] for i in resp.get("items", [])]
        request = yt.playlistItems().list_next(request, resp)
    out = []
    for i in range(0, len(ids[:limit]), 50):
        resp = yt.videos().list(part="snippet,status", id=",".join(ids[i : i + 50])).execute()
        for item in resp.get("items", []):
            out.append(
                {
                    "id": item["id"],
                    "publish_at": item["status"].get("publishAt"),
                    "uploaded": item["snippet"].get("publishedAt"),
                    "description": item["snippet"].get("description", ""),
                }
            )
    return out
