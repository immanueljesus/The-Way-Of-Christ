# Faceless Christian YouTube pipeline

Automated videos for a faceless Christian encouragement channel:
**Biblical wisdom and Christian encouragement for the battles of everyday life.**

**topic → Scripture research → script → narration → storyboard → visuals → music → subtitles →
render → thumbnail → quote cards → QA → upload → Shorts cut from each long video**.

- **Start here:** [SETUP.md](SETUP.md) (what to fill in, and the new-account steps)
- **The channel plan:** [docs/CHANNEL_ARCHITECTURE.md](docs/CHANNEL_ARCHITECTURE.md) (name options,
  pillars, formats, series, weekly schedule, script templates, thumbnail and visual style)
- **The idea bank:** [content/ideas.yaml](content/ideas.yaml) (144 ideas, `python -m fyt ideas`)

```
content/ideas.yaml ─► exact Bible text (bible-api.com) + Wikipedia background + paintings
     ▲                         │
     │        script: Pain → Recognition → Scripture → Story → Meaning → Application → Hope → Prayer
     │                (Shorts: Hook → Story → Meaning → Scripture → Application), storyboard per scene
     │                         │  Scripture check: every on-screen verse matches the real text
     │        calm narration with word timings (Kokoro / Edge / ElevenLabs)
     │                         │
 analytics ◄─ YouTube upload ◄─ QA + review ◄─ Remotion render (artwork, cinematic footage,
 (views)      (video, thumbnail,                 serif captions, music) + thumbnail + quote cards
               captions, disclosure,             + extras.md: prayer, community post, Short ideas
               series playlist)
```

The visuals are **templates driven by the script** over the story's own artwork: classical
paintings from the idea's Wikipedia article, your own artwork in `assets/visuals/`, or cinematic
stock footage searched scene by scene. Scripture quotes, story timelines, "what we see / what God
sees" comparisons and application lists are animated on top, with word-highlighted captions.

## Quick start

Requirements: Python 3.10+, Node.js 18+.

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
(cd renderer && npm install)

# 1. Demo: no API keys, renders jobs/<id>/video.mp4 ("When You Feel Forgotten")
python -m fyt demo                  # 16:9
python -m fyt --format short demo   # 9:16 Short
python -m fyt --format short demo --voice kokoro   # with the free local Kokoro voice (~350 MB model, downloaded once)
python -m fyt --format short demo --voice edge     # free Microsoft neural voice (needs internet)

# 2. Real video from the idea bank
cp .env.example .env                # add GROQ_API_KEY (+ PEXELS_API_KEY for footage, FYT_CONTACT)
python -m fyt --format short make "idea:when-you-feel-forgotten"
python -m fyt --format long --minutes 6 make "idea:joseph-pit-to-palace"
python -m fyt --format long --minutes 30 make "idea:bible-verses-and-prayer-before-sleep"
python -m fyt make "When you feel like God is far away"   # any topic works too
```

Each job folder has `video.mp4`, `thumbnail.png`, `captions.srt`, `youtube.txt` (title,
description, tags), `extras.md` (storyboard, prayer, community post, pinned comment, 6 Short
ideas), `quote-1.png`... (quote cards) and `research.md` (the Scripture and background used).

Rendering uses Chromium through Remotion. It downloads its own copy on first run; set
`REMOTION_BROWSER_EXECUTABLE` to use an existing Chromium or headless shell instead.

## Uploading to YouTube

1. In Google Cloud Console, create a project, enable **YouTube Data API v3**, and create an
   **OAuth client ID** of type *Desktop app*, signed in with the channel's new email (see SETUP.md).
   Save the JSON as `secrets/client_secret.json`.
2. `python -m fyt auth` opens a browser. Sign in with the channel's Google account.
3. Review, then upload:
   ```bash
   python -m fyt jobs                          # list jobs + status
   python -m fyt approve <job-id> --upload     # after watching video.mp4
   ```

Things to know:
- **Unaudited API projects can only upload private videos.** Until Google audits your
  project, everything uploaded through it is locked to private. Apply through the
  [YouTube API audit form](https://support.google.com/youtube/contact/yt_api_form) early.
- **Custom thumbnails need a verified channel** (youtube.com/verify). Until then the upload
  still works and the thumbnail step is skipped with a warning.
- **Quota:** the default 10,000 units a day allows about 6 uploads a day. That's plenty.
- `contains_synthetic_media` sets YouTube's "altered or synthetic content" label. YouTube requires it
  for realistic synthetic content (real people made to say things, realistic AI footage of real places
  or events, AI music), not for AI-written scripts, stock footage or a narrator voice that imitates no
  one. It is off; turn it on if you add realistic AI-generated imagery, video or cloned voices.

## Running it automatically

```bash
python -m fyt ideas                       # the idea bank by category, format and series
python -m fyt topics next -n 5            # queue the next ideas, keeping the content mix
python -m fyt topics add "Your topic"     # or any topic of your own
python -m fyt topics ideate -n 20         # let the model propose more (uses what performed well)
python -m fyt run --count 1               # next topic -> video (uploads if require_review: false)
python -m fyt stats                       # views/likes of uploaded videos
```

With `require_review: true` (the setting in `channel.yaml` for a new channel), videos wait in
`jobs/` for approval. Setting it to `false` makes the pipeline fully hands-off. Only do that once
you trust the output.

## The weekly plan with GitHub Actions

`.github/workflows/daily-short.yml` (**Daily videos**) keeps the weekly plan from
`schedule.plan` in `channel.yaml` filled on the channel:

| Day (UTC) | Video |
|---|---|
| Mon 12:00 | motivational Short |
| Tue 16:00 | 6 minute Bible story |
| Wed 12:00 | short prayer |
| Thu 12:00 | Jesus / Bible Short |
| Fri 16:00 | 10 minute inspirational video |
| Sat 12:00 | Bible fact Short |
| Sun 14:00 | 12 minute prayer and reflection |
| daily 01:00 | evening Short: cuts from the long videos first, then the content mix |

Each slot takes the next unused idea of its category from `content/ideas.yaml`. The idea's
Scripture is fetched word for word, a Bible story's Wikipedia article adds background and
classical paintings (credited in the description), topped up with public-domain Bible paintings
from Wikimedia Commons when the idea has no article (`commons_art`). Paintings are mixed with
footage: scenes without one get your own artwork or Pexels footage for a search written for that
moment, picked at random among the best matches. Footage and paintings shown in the last
`media_repeat_days` days are skipped (remembered in `jobs/state.db`), so Shorts don't repeat clips.

**The schedule is off until you turn it on** (see [SETUP.md](SETUP.md) step 6). Until then:

**Manual upload:** add the `GROQ_API_KEY` secret (free key from
[console.groq.com/keys](https://console.groq.com/keys); scripts are written by an open model on
Groq, see `llm` in `channel.yaml`; for Claude set `provider: anthropic` and add
`ANTHROPIC_API_KEY` instead), run **Actions → Daily videos → Run workflow** (task `short` or
`long`, choose how many videos), and download the run's **Artifact**. Each job folder has the video,
thumbnail, captions, quote cards, `youtube.txt` with the title, description and tags to paste into
YouTube Studio, and `extras.md` with the prayer and community post.

**Automatic upload:** set `require_review: false`, uncomment the workflow's `schedule:` block, and
do this one-time setup:

1. Do the YouTube steps above on your own computer (`python -m fyt auth`), so
   `secrets/token.json` exists. In Google Cloud, set the OAuth consent screen's
   publishing status to **In production**; in *Testing* the token expires after 7 days
   and the daily upload starts failing.
2. In the GitHub repo, **Settings → Secrets and variables → Actions**, add:
   - `GROQ_API_KEY` (or `ANTHROPIC_API_KEY` if `llm.provider` is `anthropic`)
   - `YOUTUBE_TOKEN_JSON`: the full contents of `secrets/token.json`
   - `PEXELS_API_KEY` (optional, for stock footage)
   - variable `FYT_CONTACT`: the channel's email or repo URL
3. **Actions → Daily videos → Run workflow** to test it once. The rendered video is kept
   as a run artifact for a week.

**Reliable schedule:** every run (four a day) calls `python -m fyt fill`, which keeps the next two
days of publish slots filled. Each video is uploaded ahead of time with YouTube's scheduled
publishing and goes public at a random minute up to `youtube.publish_jitter_minutes` after its slot.
A failed video, a Groq or Pexels outage, or a run GitHub skips only shrinks that buffer; the next run
refills it. Other safeguards:
- Groq calls retry on errors and fall back to `llm.fallback_models`; Pexels calls retry, and a scene
  without footage uses the plain background instead of failing the video.
- A video whose upload fails is kept (`jobs/pending`, cached between runs) and uploaded by the next run.
- Uploads stay within the API quota (`schedule.max_uploads_per_day`).
- If a slot in the next 24 hours is still empty after a run, the run fails and opens an issue titled
  "Upload schedule needs attention", which GitHub emails to you. It closes itself once the schedule is full.
Each run's summary shows the coming slots and their videos. `python -m fyt buffer` shows the same locally.

**Growth features** (`growth` in `channel.yaml`):
- *Packaging:* after the script is written, a second pass rewrites the title, the thumbnail text and
  the opening line so the right person stops scrolling (no fear or clickbait), and gives each Short a
  last line that loops back into its hook.
- *Series:* each video is filed under its series ("When You Feel...", "Lessons From...", "One Minute
  With Jesus", "Before You Sleep", "Start Your Day With God", "Did You Know?", "Prayers"), named in
  its description and added to a playlist of that name.
- *Cuts:* each long video's strongest chapters become up to 6 Shorts that link to the full video. They
  take the next evening Short slots.
- *Repurposing:* every video also gets 3 quote cards, a prayer, a community post, a pinned comment and
  6 more Short ideas (`extras.md`).

**Caption tracks, playlists and stats** need a YouTube token with the full permission, not only
uploads. Run `python -m fyt auth` on your computer (it asks for both), then replace the
`YOUTUBE_TOKEN_JSON` secret with the new `secrets/token.json`. Until then those steps are skipped and
the videos still go out; captions are burned into the video anyway.

On Groq's free tier long videos are planned first and then written one chapter at a time (every
chapter sees the Scripture), because a whole 10 minute script doesn't fit in one request. The chapters
become timestamps in the description. A 10 minute video takes well over an hour to render on the free
runner, so `schedule.max_run_minutes` is 200.

## Monetization: read this before going hands-off

- **YouTube Partner Program:** 1,000 subscribers plus 4,000 public watch hours in 12 months,
  or 10M Shorts views in 90 days.
- **The "inauthentic content" policy** (formerly "repetitious content") demonetizes channels
  whose videos are mass-produced and interchangeable. This pipeline is built to avoid that:
  - every script is written fresh from its own Scripture, story and angle
  - visuals follow the story (paintings, artwork, footage chosen scene by scene)
  - series and a clear promise give every video its place
  - the review gate keeps weak videos off the channel

  Keep those in place. Uploading many near-identical videos a day is the fastest way to get
  rejected.
- **Scripture is never misquoted:** verses come word for word from the World English Bible (public
  domain), and every on-screen quote is checked against the real text before upload.
- **Music:** only put tracks in `assets/music/` that you are licensed to use on YouTube.
- **Stock footage from Pexels** is free for commercial use; Wikimedia paintings are credited
  automatically.

## Project layout

```
content/ideas.yaml   the idea bank: 144 ideas with category, series, formats, Scripture, artwork source
docs/                CHANNEL_ARCHITECTURE.md: the channel plan
fyt/                 Python pipeline
  cli.py             commands (python -m fyt --help)
  pipeline.py        orchestration: research_notes, make_video, upload_job, run_queue
  catalog.py         the idea bank: picking by content mix, plan category and length
  scripture.py       exact Bible text (bible-api.com) and the on-screen quote check
  llm.py             prompts: topic ideas, research, the emotional-arc script
  growth.py          packaging (title, hook, thumbnail), cuts, quote cards / prayer / community post
  tts.py             voices (kokoro / edge / elevenlabs / espeak / silent) + word timings
  media.py           your artwork, Pexels footage/photos, background music
  timeline.py        script + audio -> renderer props, SRT captions
  render.py          calls renderer/render.mjs
  qa.py              automatic checks on script and render
  schedule.py        the weekly plan and `fill`
  youtube.py         OAuth, upload (video, thumbnail, captions, playlists), stats
  store.py           topic queue (SQLite) + job folders
  wiki.py            Wikipedia background and paintings
renderer/            Remotion (React) video templates
  src/scenes/        scene templates: title, statement, stat, bars, list, quote, timeline, comparison, broll
  src/components/    background, captions, audio visualizer
  src/QuoteCard.tsx  square quote cards
  render.mjs         CLI renderer (video, thumbnail, quote card, --frame preview)
assets/music/        your licensed music (not committed)
assets/visuals/      your own artwork, matched to scenes by file name
fixtures/            demo scripts used by `fyt demo`
jobs/<id>/           per-video outputs: research.md, script.json, extras.md, video.mp4, thumbnail.png,
                     quote-N.png, captions.srt, youtube.txt
```

A job folder keeps every intermediate file. You can edit `script.json` and rebuild with
`python -m fyt make "<topic>" --script jobs/<id>/script.json`, or preview a single frame:
`node renderer/render.mjs --frame 300 --props jobs/<id>/props.json --public jobs/<id>/public --out preview.png`.

Design and tweak templates live with `cd renderer && npm run studio`.

## Adding a scene template

1. Add the type to `SceneType` in `fyt/models.py` and `renderer/src/types.ts`.
2. Write the component in `renderer/src/scenes/index.tsx` and add it to `registry`.
3. Describe it in `SCRIPT_GUIDE` in `fyt/llm.py` so the scriptwriter knows when to use it.

## Tests

```bash
python -m pytest -q tests
(cd renderer && npm run typecheck)
```
