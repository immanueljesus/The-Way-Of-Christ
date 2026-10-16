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

## Voice and AI label

- The narrator is now Microsoft's free neural voice Andrew (Edge TTS), more natural than Kokoro, with exact
  word timings. A scene whose online voice fails falls back to Kokoro.
- YouTube's "altered or synthetic content" label is off (`contains_synthetic_media: false`) and the
  "Narration is AI-generated" line is gone from descriptions. YouTube requires the label for realistic
  synthetic content (real people saying things they didn't, realistic AI footage of real places or events,
  AI music); these videos use stock footage, artwork, licensed music and a narrator voice that imitates no
  one. Turn it back on if realistic AI imagery or cloned voices are ever added.

## Western publish times

- Slots are now set in New York time and follow daylight saving (`schedule.timezone`): morning Shorts at
  8 am (UK/EU lunchtime), long videos at 3 pm (UK/EU evening, US afternoon), evening Shorts at 7 pm (US
  prime time), campaign Shorts at noon and 5 pm. Each goes live within the hour after its slot.

## Bible first, emotion second

- New editorial rule in every script: a study of the passage (context, original meaning, one-sentence
  central truth, what the video must not say) comes first; the script is built on it; a faithfulness
  review afterwards rejects bent meanings, merged teachings, invented events and overpromises (one
  rewrite, then the video is rejected). `bible_first: true` in channel.yaml.
- Ten title styles rotate; "When [feeling], Remember [person or thing]" is banned (and never kept by the
  polish step). Shorts cut from long videos get proper titles too.
- The idea bank: 49 formula titles rewritten to passage-led titles, ideas narrowed to one passage per
  teaching (the mustard-seed faith of Matthew 17 and the mustard-seed parable of Matthew 13 are now
  separate videos), editor's central truths on the sensitive ones (Moses, Philippians 4, Elijah,
  2 Corinthians 12, Isaiah 55...), and 25 new ideas: parables, miracles, Bible questions and
  verse-centred videos. The "When You Feel..." series is now "Hard Seasons".
- Saints' videos stay about the saint (St Francis no longer drifts into a generic money message).

## Analytics loop, Advent, sleep videos, thumbnail tests and Spanish

- **Analytics feedback loop** (`fyt/insights.py`, `python -m fyt insights`): once a week `fill` reads the
  free YouTube Analytics API (average % viewed, how many are still watching a tenth of the way into long
  videos, and Shorts swipe-away = 1 − engaged views / views). Each video is compared with its format's
  median and grouped by pillar, story shape and title style (recorded at upload). The lessons nudge the
  content mix (×0.8–×1.25 per pillar), try the title styles viewers stayed with first, feed plain notes
  on the hook and pacing into the script prompt, and replace raw view counts in topic ideation. They never
  touch what a passage says or how the faithfulness review judges a script. Needs the new read-only
  analytics permission (run `fyt auth` again, update `YOUTUBE_TOKEN_JSON`); without it everything else
  runs as before.
- **Advent calendar** (`content/calendar.yaml`, `advent_calendar`): 24 daily Shorts, "Advent: Day 1 · …"
  to "Advent: Day 24 · …", 1–24 December, following the four candles (hope, peace, joy, love) through
  the promises of Christmas, each on its own verified passage, with the editor's central truth on the
  sensitive ones (Genesis 3:15, Luke 1:37, 2 Corinthians 8:9…). They take the 08:00 morning Short slot,
  so daily uploads stay within the API quota. Calendar videos can now set their own `time` and a
  `title_prefix` (kept on the final title and used as the thumbnail kicker). The first-Sunday video
  (29 November 2026) still opens the season.
- **Christmas story long videos**: Gabriel's two announcements (7 Dec), the whole of Luke 2:1-20 (19 Dec),
  Simeon and Anna (28 Dec), beside the existing ones, plus **A Christmas Eve Prayer** (10 min, calm,
  9 pm New York on 24 December, after the 3 pm Christmas Eve story).
- **Weekly sleep video**: Sunday 8 pm New York, 30 minutes, "Fall asleep in God's Word". Videos of 18+
  minutes are made as sleep videos (`sleep` in channel.yaml): a slower voice with long pauses, calm
  music, no burned-in captions, no Shorts cut from them, and 12 frames a second so they render on the
  free runner in about the time a 9-minute video takes. 12 new sleep ideas (Psalms 23, 91, 121, 139,
  John 14, the Beatitudes, Romans 8, Isaiah 40, Matthew 6, Ruth, the calming of the storm…).
- **Shorts cut from long videos** end on a calm line pointing to the full video (three wordings in
  rotation, with a pause before the closing card); the link stays the first line of the description,
  the Scripture credit is kept, and `youtube.txt` reminds you to set the Short's *Related video*.
- **Three thumbnails per long video**: `thumbnail.png` (uploaded), `thumbnail-b.png` (another picture
  and a second text) and `thumbnail-c.png` (centred layout and a third text), for YouTube Studio's
  Test & compare. The polish step now writes the two extra texts.
- **Spanish titles and descriptions** (`fyt/localize.py`, `localize.languages: [es]`): uploaded as
  YouTube localizations. Bible verses are never re-translated by the model (a quoted verse becomes its
  reference); a translation that drops a reference, link or chapter timestamp is not used. The video
  itself stays English; a full Spanish channel is a later step.
