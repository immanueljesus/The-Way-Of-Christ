# Setup checklist for the new channel

This folder contains no credentials and is not linked to any Google, YouTube or GitHub account.
Everything below is done with the channel's **new email**, so nothing touches personal accounts.

## What you need to fill in

| Where | What | Notes |
|---|---|---|
| `channel.yaml` → `channel.name` | The channel name | Set to "The Way of Christ". Change it here if the handle differs. |
| `.env` (copy of `.env.example`) | `GROQ_API_KEY` | Free key from console.groq.com, created with the new email. |
| `.env` | `PEXELS_API_KEY` | Free, pexels.com/api. Optional but recommended for footage. |
| `.env` | `FYT_CONTACT` | The channel's email or the new GitHub repo URL. Wikipedia asks bots to identify themselves. |
| `.env` | `ANTHROPIC_API_KEY` | Only if you switch `llm.provider` to `anthropic` (Claude, with web research). |
| `secrets/client_secret.json` | Google OAuth client | From the new Google Cloud project (step 3). Never commit it. |
| `secrets/token.json` | YouTube login token | Created by `python -m fyt auth` (step 4). Never commit it. |
| `assets/music/cinematic/`, `assets/music/prayer/` | Licensed cinematic and calm tracks | See `assets/music/README.md`. |
| `schedule.plan` in `channel.yaml` | Publish times | UTC; adjust to your audience. |
| GitHub repo secrets | `GROQ_API_KEY`, `PEXELS_API_KEY`, `YOUTUBE_TOKEN_JSON` | Step 6. |
| GitHub repo variable | `FYT_CONTACT` | Step 6 (a variable, not a secret). |

`ELEVENLABS_API_KEY` and `voice.elevenlabs_voice_id` only matter if you switch the voice to ElevenLabs.

## Steps

1. **New accounts.** Create the Gmail address, then the YouTube channel on it (a Brand Account
   lets you add managers later). Verify the channel at youtube.com/verify so custom thumbnails work.

2. **Try it locally** (no keys needed):
   ```bash
   python -m venv .venv
   .venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
   pip install -r requirements.txt
   cd renderer && npm install && cd ..
   python -m fyt --format short demo --voice kokoro
   ```
   Then copy `.env.example` to `.env`, add `GROQ_API_KEY` and `FYT_CONTACT`, and make a real one:
   ```bash
   python -m fyt --format short make "idea:when-you-feel-forgotten"
   ```
   Watch `jobs/<id>/video.mp4`, read `jobs/<id>/extras.md` (storyboard, prayer, community post) and
   look at `thumbnail.png` and `quote-*.png`.

3. **Google Cloud project** (signed in with the new email): create a project, enable
   **YouTube Data API v3**, set up the OAuth consent screen (External; add the new email as a test
   user), and create an **OAuth client ID** of type *Desktop app*. Download the JSON and save it as
   `secrets/client_secret.json`.

4. **Authorise uploads:** `python -m fyt auth` opens a browser; sign in with the channel's account.
   It asks for upload and manage permissions (the second one is for captions, playlists and stats).
   Then review and upload by hand:
   ```bash
   python -m fyt jobs
   python -m fyt approve <job-id> --upload
   ```
   Unaudited API projects can only upload private videos until Google approves the
   [YouTube API audit](https://support.google.com/youtube/contact/yt_api_form). Apply early.

5. **New GitHub repo** under the new account: create it (private is fine), then push this folder.
   `.gitignore` already keeps `.env`, `secrets/`, `jobs/`, `.venv/`, `renderer/node_modules/` and
   music out of Git. Check `git status` before the first commit.

6. **Automation** (when you trust the videos):
   - In Google Cloud, set the OAuth consent screen's publishing status to **In production**
     (in *Testing* the token expires after 7 days).
   - In the repo: **Settings → Secrets and variables → Actions**. Secrets: `GROQ_API_KEY`,
     `PEXELS_API_KEY`, `YOUTUBE_TOKEN_JSON` (the full contents of `secrets/token.json`). Variables:
     `FYT_CONTACT`.
   - Run **Actions → Daily videos → Run workflow** with task `short` and upload off, and download
     the artifact to check it.
   - Set `require_review: false` in `channel.yaml`, and uncomment the `schedule:` block at the top of
     `.github/workflows/daily-short.yml`. From then on it keeps the weekly plan filled two days ahead.

## Useful commands

```bash
python -m fyt ideas                              # the idea catalog by category, format and series
python -m fyt topics next -n 5                   # queue the next ideas (keeps the content mix)
python -m fyt topics next -n 3 --category prayer
python -m fyt --format long --minutes 30 make "idea:bible-verses-and-prayer-before-sleep"
python -m fyt buffer                             # the coming publish slots and what fills them
```
