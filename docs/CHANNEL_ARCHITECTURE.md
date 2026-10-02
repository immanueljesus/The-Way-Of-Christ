# The Way of Christ: channel architecture

The plan for the channel this pipeline runs: what it promises, what it publishes, how every video
is structured and how it looks and sounds. The pipeline reads the parts that can be automated from
`channel.yaml` and `content/ideas.yaml`; the rest is guidance for you when reviewing videos.

## 1. Promise and creative principle

> **Biblical wisdom and Christian encouragement for the battles of everyday life.**

People come to *The Way of Christ* when they're tired, lost, afraid, discouraged, lonely, or simply
looking for strength, and leave **uplifted, strengthened and closer to God**.

The creative principle: **don't just tell them about faith. Make them feel faith.**
The channel is an *experience of faith*, not a lesson about faith. Every video should leave someone
thinking:

- "I needed to hear this."
- "God has not forgotten me."
- "I can keep going."
- "I am not alone."
- "There is still hope."

Not an informational Bible documentary, a lecture or an explainer. Narration, music, visuals, pacing,
Scripture and story work together to carry the viewer through a feeling.

## 2. Name and brand

**The Way of Christ.** The logo and banner set the tone: cinematic and powerful. Every video ends on a
closing card with the name and the line "You are not alone." (`channel.tagline`), in the same serif
lettering, over the last picture.

Brand voice: someone who has been where the viewer is, speaking to one person. Warm, deep, deliberate,
honest about pain, never preachy, never hype, never fear-driven.

## 3. Content pillars

| Pillar | Content |
|---|---|
| Jesus | Teachings, life of Jesus, sayings, parables |
| Bible | Verses, stories, overlooked passages, lessons |
| Prayer | Morning and night prayers, prayers for specific situations |
| Motivation | Discipline, courage, perseverance, overcoming failure |
| Hope | Loneliness, grief, rejection, uncertainty, waiting |
| Faith | Trusting God, doubt, spiritual growth |
| Wisdom | Biblical principles for relationships, work, money, character |
| Spiritual struggle | Temptation, fear, anger, forgiveness |
| Transformation | Redemption stories, second chances |
| Peace | Anxiety, rest, surrender, God's presence |
| Bible stories | Joseph, David, Moses, Peter, Paul, Esther, Ruth, Job, Daniel... |
| Did you know? | Historical and Biblical facts and context |

Each idea in `content/ideas.yaml` names its pillar.

## 4. Formats and lengths

| Layer | Length | Purpose | How the pipeline makes it |
|---|---|---|---|
| Shorts | 20-60 s (aim 45-55) | Discovery | `--format short`; 5-8 scenes, ~115 words |
| Medium | 2-6 min | Connection | long format, `minutes: 6` in the plan |
| Long | 8-15 min | Watch time, deeper relationship | long format, `minutes: 10-12` |
| Occasional long | 20-40 min | Bible stories, prayer, sleep, reflection | `python -m fyt --format long --minutes 30 make "idea:<id>"` |

Ideas list the formats they suit (`short`, `medium`, `long`, `sleep`).

## 5. Series (playlists)

- **When You Feel...** Alone, Like Giving Up, Forgotten, Afraid, Unworthy, Betrayed, Waiting...
- **Lessons From...** Joseph, David, Moses, Peter, Paul, Esther, Ruth, Job, Daniel, Jesus...
- **One Minute With Jesus** one saying of Jesus, explained in modern language (Shorts)
- **Before You Sleep** night prayers, verses and calm stories (Shorts and 20-40 min videos)
- **Start Your Day With God** morning prayer, today's Scripture, courage for the day
- **Did You Know?** Biblical facts, places and context
- **Prayers** prayers that belong to no other series

Every video is filed under its series playlist automatically (needs the full YouTube permission).

## 6. Content mix

| Category | Share | In the catalog |
|---|---|---|
| Inspirational / motivational | 40% | `motivational` |
| Bible storytelling | 25% | `bible_story` |
| Prayer | 15% | `prayer` |
| Jesus-focused teaching | 10% | `jesus` |
| Bible facts, history, context | 10% | `facts` |

`catalog.mix` in `channel.yaml`. Slots without a fixed category take the category furthest below
its share.

## 7. Weekly schedule

Times are UTC (12:00 UTC is 8 am in New York; 01:00 UTC is 9 pm the evening before). Change them in
`schedule.plan` for your audience.

| Day | Slot | Content | Category |
|---|---|---|---|
| Monday | 12:00 | 30-60 s motivational Short | motivational |
| Tuesday | 16:00 | 5-8 min Bible story (6 min) | bible_story |
| Wednesday | 12:00 | Short prayer | prayer |
| Thursday | 12:00 | Jesus / Bible Short | jesus |
| Friday | 16:00 | 8-12 min inspirational video (10 min) | motivational |
| Saturday | 12:00 | Bible fact / story Short | facts |
| Sunday | 14:00 | Longer prayer and reflection (12 min) | prayer |
| Every day | 01:00 | Evening Short: cuts from the long videos first, then the mix | any |

That is 4 planned Shorts + 3 long videos + 7 evening Shorts a week. Once you trust the output, add
more `short_slots` (the API quota allows about 4 uploads a day).

## 8. The emotional journey (script structure)

Every video moves **struggle → uncertainty → faith → realization → hope → strength**, never
fact → explanation → conclusion. Each scene is tagged with its stage (`mood`), and the stage drives the
pace of the voice, the silence after the line, the music level and the colour of the picture.

| Stage | What the viewer feels | Words | Picture | Music |
|---|---|---|---|---|
| **Struggle** | "That's me." | Open inside the feeling, present tense, concrete: "It's late. The house is quiet..." | Darkness, rain, storms, a lone figure; cold, desaturated | Low, sparse |
| **Uncertainty** | The question they're afraid to ask | "Where are you, God?" Stay honest; don't rush to fix it | Fog, empty roads, crossroads | Low, waiting |
| **Faith** | "Someone else walked this" | Step *into* the Bible story: the dust, the dark, what they felt | Candlelight, prayer, ancient paths, the story's world | Beginning to build |
| **Realization** | The turn | The truth that changes everything, carried by Scripture, said slowly, then silence | Light breaking through darkness | Rises; swells in the pause |
| **Hope** | "I'm not forgotten" | Personal and tender: "Not tonight. Not ever." | Sunrise, open landscapes, golden light | Warm, fuller |
| **Strength** | "I can keep going" | Rise: a prayer or a declaration, and one line to carry | Summits, walking forward, the cross against the sky | Strongest, carries the ending |

Example, Joseph: not "Joseph was sold into slavery around..." but "You did everything right... and still,
nobody remembered you." Then into the pit, the caravan, the prison and the two silent years, until
Isaiah 49:15 lands: "Yes, these may forget, yet I will not forget you."

**Shorts** compress it: struggle (one line that names the feeling) → faith (the Bible moment, felt) →
realization (the verse, slowly) → hope/strength (one line to carry). No title card, no greeting.

**Prayer videos** are praying *together*: a quiet opening, a slow first-person prayer with room to
breathe, Scripture woven in word for word, a blessing spoken over the viewer, "Amen".

**Sleep / long reflection (20-40 min)** keep the same journey across chapters, gentler and slower.

How it's written: short spoken sentences, varied rhythm, "..." where the voice should breathe, repetition
that builds ("Not forgotten. Not abandoned. Not alone."). Banned: "in this video", "let's explore",
"scholars say", "historically", "fun fact", "did you know". Even a Bible fact is a doorway to a feeling.

These rules live in `fyt/llm.py` (`LONG_STRUCTURE`, `SHORT_STRUCTURE`, `PRAYER_STRUCTURE`, `SCRIPT_GUIDE`).

### Scripture rules (enforced)

- The exact text of every passage an idea names is fetched before writing (World English Bible,
  public domain) and given to the scriptwriter; only those words may be quoted.
- After writing, every on-screen Scripture quote is checked against the real verse. A loose quote is
  replaced by the exact verse; one that can't be fixed fails QA and the video is not uploaded.
- Paraphrases are said as paraphrases, with the reference. No invented verses, no words put in
  Jesus' mouth. Mainstream, non-denominational teaching; no politics, prosperity promises, guilt,
  fear tactics or medical advice.

## 9. Visuals, editing and pacing

**Cinematic and immersive.** Most of a video is full-screen imagery with the words spoken over it; text
appears only for the lines that must land and for Scripture.

- **Imagery**: sweeping landscapes, light breaking through darkness, Biblical environments, people
  walking through hard circumstances, moments of solitude, storms, mountains, sunrise, the cross. The
  scriptwriter writes a filmable search for every scene; when stock libraries have nothing for it
  (there is no footage of "Joseph in prison"), the scene falls back to imagery for its stage of the
  journey (`MOOD_QUERIES` in `fyt/media.py`).
- **Sources, in order**: classical paintings from the Bible story's Wikipedia article (credited
  automatically), your own artwork in `assets/visuals/` (e.g. AI-generated cinematic scenes in one
  consistent style, matched by file name), then Pexels footage.
- **Colour grade by stage**: cold, dark and desaturated in the struggle; warming through faith; light
  rays breaking in at the realization; golden in hope and strength.
- **Editing rhythm**: slow 0.8 s dissolves between scenes (never hard cuts), a slow push-in on every
  shot, longer holds after the lines that land (`pause_after`, longest after the turning point), a
  3-second ending where the music carries the last picture and the closing card.
- **Letterbox**: long videos get cinematic 2.39:1 bars; subtitles sit in the lower bar like a film.
- **Type**: serif, unhurried. Titles surface slowly with wide letter-spacing; key lines appear word by
  word; Scripture in italics with the reference beneath.
- **Subtitles**: quiet, film-like, sentence case; each phrase fades in and words brighten as they are
  spoken. They step aside while a Scripture or key line is on screen, so the viewer reads one thing.
- **Storyboard**: every scene also gets a one-sentence shot description (`visual_prompt`) in
  `extras.md`, ready for an AI image or video generator.

Palette: deep umber (#120d09, #3a2616), gold (#e8b86d), soft sky (#7fa7c4), cream (#fbf6ee); Georgia
serif. No audio visualizer.

## 10. Thumbnail style

- One cinematic image: the story's key moment (a painting or artwork), dark, with one pool of light.
- 2-4 words of emotional text in large cream serif capitals, e.g. **NOT FORGOTTEN**, **THE PIT
  WASN'T THE END**, **GOD SEES YOU**. It adds to the title rather than repeating it.
- A small gold label above it with the series or Bible figure: **WHEN YOU FEEL...**, **JOSEPH**.
- No shocked faces, red arrows, fake "God is warning you" text or clickbait.
- Shorts use the vertical version with the text in the lower third.

Rendered by `renderer/src/Thumbnail.tsx` from `thumbnail_text` and `thumbnail_kicker`.

## 11. Narration and music

**Narration**: warm, deep, deliberate, emotionally engaging; never an educational voiceover.
- Pace follows the journey (`voice.mood_speed`): slowest at the realization, lifting into strength.
- Pauses: a breath between sentences, a longer one after lines that trail off ("..."), and a silence
  after each scene set by the script or its stage (`voice.mood_pause`).
- Mastering: pitched down 1.5 semitones for depth, low-end warmth and a touch of room
  (`depth_semitones`, `warmth`, `room`).
- Voice: Kokoro `am_michael` (free). For the most emotional read, use ElevenLabs with a deep, warm
  narrator voice; `elevenlabs_stability: 0.35` and `elevenlabs_style: 0.35` allow more expression.

**Music is a major part of the experience**: inspiring, cinematic, emotional Christian-style
instrumentals that build gradually and become powerful at the key moments.
- The music follows the journey (`music_dynamics`): low under the struggle, rising through faith and
  realization to its fullest at strength, swelling in every pause where a line lands, and carrying the
  ending after the last word.
- It ducks under the narration so every word stays clear.
- Tracks are chosen per video: prayers and sleep videos get calm piano/ambient tracks, everything else
  cinematic, building tracks (`music_moods`, matched by file or folder name in `assets/music/`).
- Only licensed tracks (see `assets/music/README.md`).

## 12. One video, many pieces

Every master video becomes:

| Piece | Where it comes from |
|---|---|
| The long video | the pipeline |
| Up to 6 Shorts | the strongest chapters, cut automatically after upload (`growth.cuts_per_long: 6`), each linking to the full video; they fill the evening Short slots |
| 3 quote cards | `quote-1.png`...`quote-3.png` (1080×1080) for the Community tab and other platforms |
| A prayer | `extras.md`, e.g. "A Prayer When Life Feels Unfair" |
| A community post | `extras.md`, a question that invites people to share |
| A pinned comment | `extras.md` |
| 6 more Short ideas | `extras.md`, to queue with `python -m fyt topics add "..."` |

Community posts and quote cards are posted by hand in YouTube Studio (the API can't post them).

## 13. Evergreen first

The Bible doesn't go out of date, so the channel focuses on evergreen emotional problems
("When God Seems Silent" works in 2026 and 2032), not Christian news or controversy. Trending
bonus videos are switched off.

## 14. The production pipeline

```
content/ideas.yaml (144 ideas)  ──►  topic (weekly plan category / content mix)
        │
        ▼
Scripture research: exact verse text (bible-api.com) + Wikipedia background + paintings
        │                                           (+ Claude web research if enabled)
        ▼
script: emotional arc, scene templates, storyboard shot per scene   (fyt/llm.py)
        │   packaging pass: title, hook, thumbnail text, loop line  (fyt/growth.py)
        │   Scripture check: on-screen quotes = the real verses     (fyt/scripture.py)
        ▼
narration (Kokoro / Edge / ElevenLabs, word timings)                (fyt/tts.py)
        ▼
visuals: paintings → your artwork → cinematic stock                 (fyt/pipeline.py, fyt/media.py)
        ▼
music + word-by-word subtitles + render (Remotion)                  (renderer/)
        ▼
thumbnail + quote cards + extras.md (prayer, community post, 6 Short ideas)
        ▼
QA → review (fyt approve) or scheduled upload with AI disclosure    (fyt/qa.py, fyt/youtube.py)
        ▼
playlist by series → 6 Shorts cut from each long video → next slots (fyt/schedule.py)
```

## 15. Idea bank

`content/ideas.yaml` holds 144 ideas: 48 motivational, 38 Bible stories, 22 prayers, 18 Jesus
teachings and 18 Did-you-know facts, covering every series. `python -m fyt ideas` shows the counts;
add your own at any time. When the list runs out, the model proposes new topics in the same niche.

## 16. Monetisation and trust

- YouTube Partner Program: 1,000 subscribers plus 4,000 watch hours in 12 months, or 10M Shorts
  views in 90 days.
- The "inauthentic content" policy targets mass-produced, interchangeable videos. What keeps this
  channel safe: every script is written fresh from its own Scripture and story, visuals follow the
  story, series give each video a place, and the review gate keeps weak videos off the channel.
- The AI-voice disclosure (`contains_synthetic_media`) stays on.
- Scripture is quoted from a public-domain translation (World English Bible), credited in each
  description. Don't switch to NIV/ESV text without a licence.
