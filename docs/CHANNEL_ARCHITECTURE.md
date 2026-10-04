# The Way of Christ: channel architecture

The plan for the channel this pipeline runs: what it promises, what it publishes, how every video
is structured and how it looks and sounds. The pipeline reads the parts that can be automated from
`channel.yaml` and `content/ideas.yaml`; the rest is guidance for you when reviewing videos.

## 1. Promise and creative principle

> **Stories, wisdom, prayer and inspiration rooted in Jesus Christ and the Bible, created to give
> people faith, courage, hope and perspective for everyday life.**

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

## 3. The content universe (pillars)

The channel is not "you are struggling → here is a verse" on repeat. It is a large Christian
inspirational universe: diverse subjects, a Biblical foundation, cinematic storytelling, inspiring music
and powerful narration. The viewer doesn't know exactly what the next video will be, but they know the
emotional experience they'll get.

| Pillar (`category`) | What it covers | Example |
|---|---|---|
| Jesus (`jesus`) | Life, teachings, miracles, parables | *Why Jesus Washed His Disciples' Feet* |
| Bible Stories (`bible_story`) | Characters and narratives, famous and lesser-known | *The Judge Who Sat Under a Palm Tree* (Deborah) |
| Motivation (`motivation`) | Courage, discipline, perseverance | *Don't Quit in the Middle of the Story* |
| Prayer (`prayer`) | Situational and devotional prayers | *A Prayer for Someone Starting Over* |
| Peace (`peace`) | Rest, reflection, surrender | *Be Still. God Is With You.* |
| Relationships (`relationships`) | Love, forgiveness, betrayal, family | *How Jesus Taught Us to Forgive* |
| Purpose (`purpose`) | Calling, direction, work, identity | *What If Your Waiting Season Has a Purpose?* |
| Spiritual Battles (`spiritual_battles`) | Temptation, doubt, fear | *Why Do I Keep Doing What I Don't Want to Do?* |
| Biblical Wisdom (`wisdom`) | Practical life lessons | *What Proverbs Says About Money* |
| Bible & History (`history`) | Context, places, customs, fascinating facts | *A Day in the Life of a Fisherman in Galilee* |
| Faith in Everyday Life (`everyday_life`) | Career, money, social media, aging, leadership... | *When Scrolling Makes You Feel Behind* |

**Emotional range.** Every idea names the feeling it carries (`emotion`): courage, love, grief, peace,
joy, curiosity, fear, strength, wisdom, hope, gratitude, temptation, forgiveness, purpose.

**Characters beyond the obvious.** Deborah, Bartimaeus, Stephen, Barnabas, Timothy, Lydia, the Roman
centurion, Jeremiah, Mary Magdalene, Caleb, Naomi, Abigail, Rahab, Joseph of Arimathea, Simon of
Cyrene, Onesimus, Mephibosheth, the widow of Zarephath, Habakkuk... alongside Joseph, David and Moses.
The picker never puts the same person or feeling back to back.

**Titles that don't sound like religious programming.** *Don't Quit in the Middle of the Story*, *He Was
Forgotten for Years* (then: Joseph), *Why Did Jesus Write in the Sand?* The video reveals the Bible
connection. Curiosity titles bring in people who would never search for a Bible video.

## 4. Formats and lengths

| Layer | Length | Purpose | How the pipeline makes it |
|---|---|---|---|
| Shorts | 20-60 s (aim 45-55) | Discovery | `--format short`; 5-8 scenes, ~115 words |
| Medium | 2-6 min | Connection | long format, `minutes: 6` in the plan |
| Long | 8-15 min | Watch time, deeper relationship | long format, `minutes: 10-12` |
| Occasional long | 20-40 min | Bible stories, prayer, sleep, reflection | `python -m fyt --format long --minutes 30 make "idea:<id>"` |

Ideas list the formats they suit (`short`, `medium`, `long`, `sleep`).

## 5. Series (playlists)

- **Hard Seasons** Alone, Like Giving Up, Forgotten, Afraid, Unworthy, Betrayed, Waiting...
- **Lessons From...** Joseph, David, Moses, Peter, Paul, Esther, Ruth, Job, Daniel, Jesus...
- **One Minute With Jesus** one saying of Jesus, explained in modern language (Shorts)
- **Before You Sleep** night prayers, verses and calm stories (Shorts and 20-40 min videos)
- **Start Your Day With God** morning prayer, today's Scripture, courage for the day
- **Did You Know?** Biblical facts, places and context
- **Prayers** prayers that belong to no other series

Every video is filed under its series playlist automatically (needs the full YouTube permission).

## 6. Content mix

`catalog.mix` in `channel.yaml` (percent of videos per pillar):

| Bible stories | Jesus | Motivation | Prayer | Relationships | Purpose | Peace | Spiritual battles | Wisdom | History | Everyday life |
|---|---|---|---|---|---|---|---|---|---|---|
| 15 | 12 | 12 | 10 | 9 | 9 | 8 | 7 | 7 | 6 | 5 |

Slots without a fixed pillar take the one furthest below its share. Within a pillar, the next idea is the
one that doesn't repeat the last videos' person, feeling or story shape.

## 7. Weekly schedule (free)

Everything runs on GitHub Actions' free allowance, the free Groq and Pexels tiers, the free Kokoro voice,
free Creative Commons music and the free YouTube API quota.

| | Morning Short (8 am New York) | Long video (3 pm New York) | Evening Short (7 pm New York) |
|---|---|---|---|
| Monday | Jesus | | cut from a long video, else the content mix |
| Tuesday | Motivation | Bible story, 6 min | same |
| Wednesday | Prayer | | same |
| Thursday | Bible story | | same |
| Friday | Biblical wisdom | any pillar (content mix), 10 min | same |
| Saturday | Bible & history | | same |
| Sunday | Peace | | same |

A month: about 60 Shorts and 9 long videos, roughly 1,300 runner minutes, each going live at a random
minute up to 3 hours after its slot. Relationships, purpose, spiritual battles and everyday life arrive
through the evening Shorts and Friday's long video. Occasional 20-40 minute videos (*30 Minutes of
Peace With God*) are made by hand with `--minutes 30` to stay inside the free minutes.

## 8. Story shapes

Every video makes the viewer feel something, but not by the same road. Each idea has an `arc`:

| Shape | How it moves | Used for |
|---|---|---|
| **journey** | struggle → uncertainty → faith → realization → hope → strength | hurting seasons: fear, grief, waiting, failure |
| **story** | drop into the scene → the tension → the turn (with the verse) → the thread to today → the invitation | Bible stories, Jesus' moments, lesser-known characters |
| **curiosity** | the question → the world behind it → the surprising answer → why it matters | *Why Did Jesus Write in the Sand?*, history |
| **wisdom** | a modern situation → ancient wisdom → practice this week → blessing | Proverbs, everyday life, relationships |
| **prayer** | a quiet opening → praying together → the promise → blessing, Amen | prayers |
| **peace** | stillness: short lines, long silences, the promise spoken slowly | rest, sleep, *Be Still* |
| **joy** | remember → notice (the verse) → celebrate and give thanks | gratitude, *The Joy of the Lord* |

Each scene still carries a `mood` (struggle, uncertainty, faith, realization, hope, strength) that sets
the energy: the narrator's pace, the music level and the colour of the picture. Story videos also get the
whole Bible chapter as background, so the details stay true to the text.

How it's written: short spoken sentences, varied rhythm, "..." where the voice should breathe, repetition
written fresh for each video. Banned: "in this video", "let's explore", "scholars say", "fun fact", "did
you know". Even a Bible fact is a doorway to a feeling.

These rules live in `fyt/llm.py` (`LONG_STRUCTURE`, `STORY_STRUCTURE`, `CURIOSITY_STRUCTURE`,
`WISDOM_STRUCTURE`, `PEACE_STRUCTURE`, `JOY_STRUCTURE`, `PRAYER_STRUCTURE`, `SCRIPT_GUIDE`).

### Scripture rules (enforced)

- The exact text of every passage an idea names is fetched before writing (World English Bible,
  public domain) and given to the scriptwriter; only those words may be quoted.
- After writing, every on-screen Scripture quote is checked against the real verse. A loose quote is
  replaced by its closest exact verse; one that can't be fixed fails QA and the video is not uploaded.
- Paraphrases are said as paraphrases, with the reference. No invented verses or events, no words put
  in Jesus' mouth. Mainstream, non-denominational teaching; no politics, prosperity promises, guilt,
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
- Mastering: a slightly lowered pitch, low-end warmth, a touch of room, levelled loudness
  (`edge_pitch`, `warmth`, `room`, `loudness`).
- Voice: Microsoft's free neural voice Andrew (`edge`, en-US-AndrewMultilingualNeural), with exact
  word timings for the subtitles. If it fails, that scene falls back to Kokoro (free, offline). Other
  free options: Brian, Christopher (deeper), Ryan (British). ElevenLabs is the paid upgrade.

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

`content/ideas.yaml` holds 219 curated ideas across all 11 pillars, every emotion and every story
shape, including dozens of lesser-known Bible people and the curiosity topics. `python -m fyt ideas` shows the
counts. When a pillar runs low (fewer than 4 unused ideas), the model writes 8 new ideas for it in the
same shape, using the pillar's best ideas as examples; only ideas whose Scripture references exist in the
Bible are kept. They are stored in `jobs/state.db` with the queue, so GitHub keeps them between runs.
Curated ideas always go first, so add your own to `content/ideas.yaml` at any time.

## 16. Monetisation and trust

- YouTube Partner Program: 1,000 subscribers plus 4,000 watch hours in 12 months, or 10M Shorts
  views in 90 days.
- The "inauthentic content" policy targets mass-produced, interchangeable videos. What keeps this
  channel safe: every script is written fresh from its own Scripture and story, visuals follow the
  story, series give each video a place, and the review gate keeps weak videos off the channel.
- YouTube's "altered or synthetic content" label (`contains_synthetic_media`) is off: it is required for
  realistic synthetic content (real people saying things they didn't, realistic AI footage of real places
  or events, AI music), and these videos use stock footage, artwork, licensed music and a narrator voice
  that imitates no one. Turn it on if realistic AI-generated imagery or cloned voices are ever added.
- Scripture is quoted from a public-domain translation (World English Bible), credited in each
  description. Don't switch to NIV/ESV text without a licence.

## 17. The Christian calendar

Two engines run side by side: **evergreen** videos (watchable any day) and **Christian calendar**
campaigns (`content/calendar.yaml`, `fyt/liturgy.py`). Roughly 70% evergreen, 20% seasonal, 10% world
moments, so someone discovering the channel in August doesn't see a page of Easter videos.

**Every event is a campaign, not a single upload:** videos 7-14 days **before** (anticipation), **on the
day** (the emotional centrepiece) and 1-7 days **after** (reflection). Dates are computed for every year
(Easter by the computus, Western or Orthodox), so the same framework returns each year as new videos:

| Event | Before | On the day | After |
|---|---|---|---|
| Advent & Christmas | *The World Was Waiting*, *400 Years of Silence*, *Mary Said Yes*, *Joseph's Difficult Decision*, *Why Bethlehem?* | Christmas Eve: *The Night Everything Changed* (long); Christmas: *A Savior Is Born* | *Why Did God Come to Us?*, *The Meaning of Emmanuel* |
| Lent (6 themed weeks) | Ash Wednesday: *Remember You Are Dust* | repentance, temptation, sacrifice, forgiveness, faith, the cross | leads into Holy Week |
| Holy Week & Easter | *Why Did Jesus Have to Enter Jerusalem?*, *The Road to Jerusalem*, Palm Sunday | Maundy Thursday (long), **Good Friday: *It Is Finished*** (long; minimal narration, dark, calm music), Holy Saturday: *When God Seems Silent*, **Easter: *He Is Risen*** (the biggest production, 10 min) | *What the Resurrection Means for Your Life*, *Why the Disciples Were Changed Forever* |
| Pentecost | *The Disciples Were Afraid*, *Jesus Told Them to Wait* | ***And Then the Fire Came*** (long) | *What Pentecost Means Today* |
| Feasts | Epiphany, Baptism of Jesus, Ascension, Trinity, All Saints, All Souls, Christ the King | | |
| Saints & heroes of faith | St Patrick, Bonhoeffer, Dominic Savio, Peter & Paul, Monica, Augustine, Mother Teresa, Francis, Nicholas | | |
| World moments | New Year, Valentine's Day, Mother's Day (Hannah), graduation, Father's Day, Thanksgiving | | |

About 60 campaign videos a year (11 of them long). Long videos are cut into Shorts like any other, so
Easter alone yields a dozen or more Shorts.

**Made in advance.** Campaign videos are scripted, voiced, rendered and scheduled up to a week ahead
(`liturgy.lead_days`), so Good Friday's video is ready days before. A campaign long video takes that
day's long slot or gets its own at 3 pm New York time; campaign Shorts get their own slots at noon and 5 pm New York time
on top of the day's regular Shorts. If a campaign video fails, the slot still gets an evergreen video.

**Seasons.** Between events the evergreen picks lean towards the season (`seasons` in calendar.yaml): Lent
favours forgiveness and spiritual battles, Eastertide joy and hope, Advent hope and peace, January new
beginnings, the summer Bible stories and practical faith, November gratitude and remembrance.

**Traditions.** `liturgy.traditions` in channel.yaml chooses what is included: ecumenical, western,
world and saints by default; add `catholic` for Marian feasts, Corpus Christi and the Sacred Heart;
set `liturgy.easter: orthodox` to follow the Orthodox Easter date.

`python -m fyt calendar --days 120` lists the coming campaign videos.

## 18. Bible first, emotion second (editorial rule)

**Never bend Scripture to fit the content idea. Find the truth in Scripture first, then build the video
around it.** Every script goes through these steps:

1. **Biblical source:** the one passage the video rests on (book, chapter, verses).
2. **Context:** what happens immediately before and after (story and curiosity videos get the whole chapter).
3. **Original meaning:** what the passage actually says.
4. **Central truth:** one sentence (written by the editor in `truth` where it matters, otherwise by the
   study step).
5. **Modern connection:** the human experience that connects naturally.
6. **Story:** made cinematic.
7. **Application:** offered as application, never as the passage's meaning.
8. **No overpromising:** never "God will fix everything", "this verse guarantees your breakthrough" or
   "enough faith gets you what you want"; instead "you can bring your fear to God", "God's presence does
   not depend on your circumstances", "faith does not mean knowing how the story ends".

In the pipeline: `study_passage` writes steps 1-5 before anything else; the script is written on that
study; `check_faithfulness` then reviews the script against the study and the exact verses (bent meaning,
merged teachings such as Matthew 13 vs 17, invented events, overpromises, a saint's video drifting away
from the saint). A failed script is rewritten once with the reviewer's notes, then rejected; a rejected
script is never uploaded.

**A title language, not a title template.** Ten styles rotate so neighbouring videos never share a shape:
cinematic (*The Night Peter Realized What He Had Done*), direct (*Stand Firm*), curiosity (*Why Did Jesus
Sleep During the Storm?*), biblical question (*What Does Jesus Mean by "Take Up Your Cross"?*), character
(*Moses: The Man Who Didn't Think He Was Ready*), verse-centred (*"My Grace Is Sufficient for You": What Paul
Learned About Weakness*), practical wisdom (*What Proverbs Actually Says About Money*), prayer, history and
seasonal. The formula "When [feeling], Remember [person or thing]" is banned outright.

**Not every video is motivational.** Some are beautiful, thought-provoking, educational, mysterious,
challenging, peaceful or joyful, as the passage calls for, and all of them point to Christ. The idea bank
includes parables, miracles, Bible questions and verse-centred videos alongside stories and wisdom.
