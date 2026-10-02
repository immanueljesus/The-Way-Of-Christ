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

## Fixes

- Bible references that span chapters ("Genesis 42:29–43:15") were cut to "Genesis 42:29-43" and failed to fetch; they now keep their end chapter. Passages only mentioned in the Wikipedia background are kept only when short enough to quote.
- Every file the pipeline reads or writes now uses UTF-8, so Windows (cp1252) no longer fails on characters like narrow spaces or curly quotes in a script.
- Stock clips are converted to 30 fps H.264 at the video's exact size before rendering, slowed (up to 2x) or looped to cover their scene, and replaced by a still if they can't be converted. Mixed Pexels clips (25/59.94 fps, 1080x2048) crashed Remotion with "No frame found at position".

## Music, length and polish (after the first automatic runs)

- **Music was missing** because `assets/music` is not committed, so GitHub Actions had no tracks. The
  pipeline now falls back to a free library (`content/music.yaml`): 13 cinematic and calm tracks by
  Kevin MacLeod, Creative Commons Attribution 4.0, downloaded on first use and cached between runs. The
  required credit is added to every description. Your own tracks in `assets/music/` still win.
- Every track is levelled to the same loudness, cut to the video, and (for cinematic tracks) started so
  the video's ending meets the music's peak instead of its fade-out. Music sits about 15 dB under the
  voice and swells in the pauses and at the end (`music_volume: 0.3`).
- Long videos: a chapter far under its length is rewritten longer, so 10-minute videos stop coming out
  at 5-6 minutes.
- A loose Scripture quote from a long passage is replaced by its closest single verse, not the whole
  passage (no more walls of text on screen).
- Shorts no longer end on a "loop" line that repeats the hook; they end on strength and the closing card.
- Off-brand stock results (brand logos, caps, parties, neon...) are skipped (`stock_skip_words`).
- The closing card fully covers the last scene's text.

## The content universe

- 11 pillars instead of 5 categories: Jesus, Bible stories, motivation, prayer, peace, relationships,
  purpose, spiritual battles, wisdom, Bible & history, faith in everyday life (`catalog.mix`).
- The idea bank grew from 144 to 219, re-filed into the pillars and tagged with an emotion, a Bible
  character and a story shape. The new ideas lean on lesser-known people (Deborah, Bartimaeus, Stephen,
  Barnabas, Lydia, Naomi, Abigail, Caleb...), curiosity topics (*Why Did Jesus Write in the Sand?*),
  practical wisdom (*What Proverbs Says About Money*) and everyday life (*When Scrolling Makes You Feel
  Behind*). Every reference was checked against the Bible text.
- Seven story shapes (journey, story, curiosity, wisdom, prayer, peace, joy), each with its own script
  structure, so videos stop following "struggle -> verse" every time. Story and curiosity videos get the
  whole Bible chapter as background so details stay true to the text.
- Titles are cinematic or curious, revealing the Bible connection inside the video.
- The picker avoids repeating the same person, feeling or shape back to back.
- The weekly plan gives each morning a different pillar; Friday's long video follows the mix.
- When a pillar runs low, the model writes new ideas in the same shape (free), keeping only ones whose
  Scripture exists; they are stored in `jobs/state.db` so GitHub keeps them.
- Empty narration from the model no longer fails a video: a Scripture scene reads its verse, other
  empty scenes are dropped.

## The Christian calendar engine

- `fyt/liturgy.py` computes the Christian year for any year (Western or Orthodox Easter and the
  moveable feasts, Advent, Christ the King, fixed feasts, Mother's/Father's Day, Thanksgiving).
- `content/calendar.yaml`: 67 campaign videos across Advent & Christmas, New Year, Epiphany, the
  Baptism of Jesus, Valentine's Day, Lent's six themed weeks, Holy Week & Easter, Ascension, Pentecost,
  Trinity, saints and heroes of faith, world moments and (off by default) Catholic feasts. Each event has
  videos before, on and after the day; every Scripture reference was checked.
- Campaign videos get their own publish slots, made up to a week ahead; long campaign videos take the
  day's long slot. A failed campaign video falls back to an evergreen one.
- Seasons lean the evergreen picks (Lent, Eastertide, Advent, new beginnings, summer stories...).
- Solemn days (Good Friday, Holy Saturday, All Souls) get calm music; Easter and Pentecost cinematic.
- `python -m fyt calendar` lists what's coming. Tests in `tests/test_liturgy.py`.
