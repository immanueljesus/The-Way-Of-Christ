# What changed: from "weird facts" to a Christian encouragement channel

The pipeline, commands and GitHub workflow work as before; the content, prompts and look were
reoriented, and a few pieces were added. Nothing here is linked to any account.

## New

| File | What it does |
|---|---|
| `content/ideas.yaml` | 144 curated ideas (48 motivational, 38 Bible stories, 22 prayers, 18 Jesus, 18 Did-you-know), each with category, pillar, series, formats, Scripture references and an optional Wikipedia article for background and paintings |
| `fyt/catalog.py` | Picks the next idea by the slot's category, the content mix (40/25/15/10/10) and the video length |
| `fyt/scripture.py` | Fetches the exact text of every Bible reference (World English Bible, public domain) before writing, and checks every on-screen Scripture quote against it afterwards (fixes loose quotes, fails QA if it can't) |
| `renderer/src/QuoteCard.tsx` | 1080×1080 quote cards (`quote-1.png`...) for the Community tab |
| `docs/CHANNEL_ARCHITECTURE.md` | The channel plan: name options, pillars, formats, series, mix, weekly schedule, script templates, thumbnail and visual style, repurposing, pipeline map |
| `SETUP.md` | Everything you must fill in, and the new-account steps |
| `assets/music/README.md`, `assets/visuals/README.md` | What music to add, and how to add your own artwork |
| `tests/test_christian.py` | Tests for the new pieces (Scripture check, catalog, weekly plan, extras) |

## Changed

- **Prompts** (`fyt/llm.py`, `fyt/growth.py`): scripts follow Pain → Recognition → Scripture → Story →
  Meaning → Application → Hope → Scripture/prayer (Shorts: Hook → Story → Meaning → Scripture →
  Application; prayers have their own structure). Warm, calm, non-preachy tone; strict Scripture rules;
  cinematic shots instead of sunset clichés; honest, non-fearful titles and thumbnails. Research, topic
  ideas and topic ranking are faith-focused.
- **Storyboard**: each scene now has a `visual_prompt` (one cinematic shot description).
- **Repurposing** (`growth.repurpose`): each video gets `extras.md` with the storyboard, 3 quote cards,
  a prayer, a community post, a pinned comment and 6 Short ideas. Long videos are cut into up to 6
  Shorts (`cuts_per_long: 6`).
- **Weekly plan** (`schedule.plan`): fixed slots with a category and length (Mon motivational Short,
  Tue 6 min Bible story, Wed prayer Short, Thu Jesus Short, Fri 10 min inspirational, Sat fact Short,
  Sun 12 min prayer and reflection) plus a daily evening Short.
- **Lengths**: `--minutes` for 20-40 minute sleep, prayer and story videos; scripts are sized by
  `voice.words_per_minute` (135 for the calm narrator).
- **Visuals**: Wikipedia paintings for Bible stories (with a skip list to keep the look consistent),
  your own artwork from `assets/visuals/` matched by file name, then Pexels footage. New warm
  candlelight theme with serif type; audio visualizer off.
- **Voice**: Kokoro `am_michael` at 0.9x with longer pauses.
- **Descriptions**: Scripture translation credit and a channel footer are added automatically.
- **Demo** (`fixtures/`): "When You Feel Forgotten" (Joseph) instead of compound interest.
- **Workflow**: the automatic schedule is commented out until you turn it on; timeouts raised for
  10-12 minute videos; quote cards and extras kept in the artifacts; `FYT_CONTACT` variable added.
- **Bonus trending videos** are off (evergreen channel).
- `requirements.txt`: `tzdata` on Windows (the schedule's time zones failed without it).
- A flaky schedule test was made deterministic.

## Account-specific details removed

- The Wikipedia user agent pointed at the old GitHub repo (`flyfir248/FacelessYT`); it now uses
  `FYT_CONTACT` from `.env` or the workflow variable.
- The channel name is now "The Way of Christ".
- There were no keys, tokens or OAuth files in the folder (`secrets/` holds only `.gitkeep`).

## Second pass: an experience of faith, not a lesson

Following the creative direction "don't just tell them about faith, make them feel faith":

- **Scripts** follow struggle → uncertainty → faith → realization → hope → strength. Every scene is
  tagged with its stage (`mood`) and a `pause_after`; the prompts ban lecture language and bring the
  viewer into the Bible story in the present tense. Charts, lists and timelines are avoided.
- **Narration** (`fyt/tts.py`): pace per stage, pauses per scene, longer breaths after lines ending in
  "...", and mastering for a deeper, warmer voice. ElevenLabs gets expressive voice settings.
- **Music** (`fyt/timeline.py`): a volume curve that ducks under the words, swells in the pauses and
  rises with the journey to its fullest at the end; tracks are chosen by the video's category.
- **Visuals** (`renderer/`, `fyt/media.py`): imagery behind every scene, with fallbacks per stage
  (storms, fog, candlelight, light breaking through, sunrise, summits, the cross); a colour grade that
  warms from cold struggle to golden strength with light rays at the turn; 0.8 s dissolves; slow push-ins.
- **Presentation**: letterbox on long videos, film-like subtitles that step aside for on-screen
  Scripture, slow serif titles, and a closing "THE WAY OF CHRIST / You are not alone." card.
- Narration is normalised to -16 LUFS and every finished video to -14 LUFS (YouTube's playback level).
- Wikimedia requests now retry when rate-limited.
- `tests/test_experience.py` covers the pacing, pauses, music curve, closing card and music choice.
