"""End-to-end orchestration. Each step writes its output into the job folder,
so a failed run can be inspected and individual steps re-run."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fyt import catalog, growth, llm, media, qa, render, scripture, tts, wiki, youtube
from fyt.config import Config
from fyt.models import Media, QuoteCardProps, RenderProps, Script, ThumbnailProps
from fyt.store import Job, Topics, Uploads, list_jobs
from fyt.timeline import build_props, to_srt


def log(job: Job, msg: str) -> None:
    print(f"[{job.id}] {msg}", flush=True)


def make_video(
    cfg: Config, topic: str, script: Script | None = None, voice: str | None = None, polish: bool | None = None
) -> Job:
    """Topic -> rendered video + thumbnail + captions, ready for review/upload.
    `polish` (default: when the script is written here) sharpens title, hook and thumbnail text."""
    job = Job.create(cfg, topic)
    try:
        _make(cfg, job, topic, script, voice, script is None if polish is None else polish)
    except Exception as e:
        job.update(status="failed", error=f"{type(e).__name__}: {e}")
        raise
    return job


def repair_script(script: Script) -> Script:
    """Free models sometimes leave a scene's narration empty. A Scripture scene then reads its verse
    aloud; any other empty scene is dropped (QA would reject the whole video for it)."""
    scenes = []
    for s in script.scenes:
        if s.narration.strip():
            scenes.append(s)
        elif s.type == "quote" and s.text:
            scenes.append(s.model_copy(update={"narration": s.text}))
    if len(scenes) == len(script.scenes) or not scenes:
        return script
    print(f"repaired the script: {len(script.scenes) - len(scenes)} empty scene(s) dropped")
    return script.model_copy(update={"scenes": scenes})


def research_notes(cfg: Config, job: Job, topic: str) -> tuple[str, str, "wiki.Article | None", list, "catalog.Idea | None", dict]:
    """Scripture research for a topic: (subject, notes, Wikipedia article, article images, catalog idea, passages).
    Notes start with the exact text of every Bible passage involved (see fyt/scripture.py)."""
    notes, article, images, idea, refs = "", None, [], None, []
    subject = topic
    if catalog.is_idea(topic):
        idea = catalog.get(cfg, topic)
        subject, refs = idea.title, list(idea.scriptures)
        notes = catalog.brief(idea, cfg)
        wiki_title = idea.wiki if cfg.catalog.use_wikipedia else None
    else:
        wiki_title = topic[len(wiki.PREFIX) :] if wiki.is_wiki_topic(topic) else None
    if wiki_title:
        log(job, f"fetching Wikipedia article {wiki_title!r}")
        try:
            article = wiki.fetch_article(cfg, wiki_title)
            images = wiki.fetch_images(cfg, article.title)
            log(job, f"{len(images)} article images available")
        except Exception as e:
            if idea is None:
                raise  # a wiki: topic has nothing else to go on
            log(job, f"warning: no Wikipedia background: {e}")
        if article:
            subject = subject if idea else article.title
            notes = (notes + "\n\n" + wiki.notes(article)).strip()
    if cfg.research and cfg.llm.provider == "anthropic" and article is None:
        log(job, "researching")
        notes = (notes + "\n\n" + llm.research(cfg, subject)).strip()
    # The idea's own passages always; ones merely mentioned in the background notes (often whole
    # chapters, e.g. "Genesis 42:29–43:15") only when short enough to quote, so they don't crowd
    # the notes the model sees.
    passages = scripture.fetch_all(cfg, refs[:8])
    extra = [r for r in scripture.find_references(notes) if r not in refs][: max(0, 12 - len(passages))]
    passages.update(
        {r: p for r, p in scripture.fetch_all(cfg, extra).items() if len(p.text) <= cfg.scripture.max_verse_chars}
    )
    if passages:
        log(job, f"fetched {len(passages)} Scripture passages ({cfg.scripture.translation})")
    # Stories and curiosities need the whole Bible scene, so the details stay true to the text:
    # the chapter around the idea's first passage, as background (only the verses above are quoted).
    context = ""
    if idea and idea.shape in ("story", "curiosity") and refs and article is None:
        m = scripture.REFERENCE.match(refs[0])
        chapter = f"{m[1]} {m[2]}" if m else ""
        try:
            whole = scripture.fetch(cfg, chapter) if chapter else None
        except Exception as e:
            log(job, f"warning: no chapter context: {e}")
            whole = None
        if whole:
            context = f"\n\n## The story as the Bible tells it ({chapter}; background, do not invent beyond it)\n{whole.text[:5000]}"
    notes = (scripture.notes(passages) + "\n\n" + notes + context).strip()
    return subject, notes, article, images, idea, passages


def _make(cfg: Config, job: Job, topic: str, script: Script | None, voice: str | None, polish: bool = False) -> None:
    images: list[wiki.WikiImage] = []
    idea = None
    passages: dict = {}
    if script is None:
        subject, notes, article, images, idea, passages = research_notes(cfg, job, topic)
        job.file("research.md").write_text(notes, encoding="utf-8")
        log(job, "writing script")
        menu = wiki.image_menu(images)
        prayer = bool(idea and idea.category == "prayer")
        shape = idea.shape if idea else "journey"
        script = llm.write_script(
            cfg, subject, notes, from_wikipedia=article is not None, images=menu, prayer=prayer, shape=shape
        )
        limit = llm.short_words(cfg) * 1.25 if cfg.format == "short" else None
        if limit and narration_words(script) > limit:
            log(job, f"script is {narration_words(script)} words; asking for a shorter one")
            feedback = (
                f"Your previous draft had {narration_words(script)} words of narration. "
                f"This is a Short: keep the total narration under {llm.short_words(cfg)} words."
            )
            script = llm.write_script(
                cfg, subject, notes, from_wikipedia=article is not None, images=menu, feedback=feedback, prayer=prayer,
                shape=shape,
            )
        script = repair_script(script)
        if article:
            script = wiki_attribute(script, article)
    if polish and cfg.growth.polish:
        log(job, "sharpening title, hook and thumbnail text")
        try:
            script = growth.polish(cfg, script)
        except Exception as e:  # the unpolished script is still fine
            log(job, f"warning: polish failed: {e}")
    if idea and idea.series:
        script = script.model_copy(update={"series": idea.series})
    script, verse_problems = scripture.check_quotes(cfg, script, passages)
    if passages and "Scripture quotations" not in script.description:
        script = script.model_copy(update={"description": script.description.rstrip() + "\n\n" + scripture.credit(cfg, passages)})
    job.file("script.json").write_text(script.model_dump_json(indent=2), encoding="utf-8")
    job.update(status="scripted", title=script.title)

    extras = None
    if cfg.repurpose and not topic.startswith(CUT):
        try:
            extras = growth.repurpose(cfg, script)
            job.file("extras.json").write_text(extras.model_dump_json(indent=2), encoding="utf-8")
        except Exception as e:  # nice-to-have; the video doesn't depend on it
            log(job, f"warning: no quote cards / prayer / community post: {e}")
    job.file("extras.md").write_text(growth.extras_markdown(script, extras), encoding="utf-8")

    problems = qa.check_script(cfg, script) + verse_problems
    if problems:
        job.update(status="qa_failed", problems=problems)
        raise RuntimeError("script failed QA: " + "; ".join(problems))

    provider = voice or cfg.voice.provider
    log(job, f"voicing {len(script.scenes)} scenes with {provider}")
    clips_dir = job.file("clips")
    clips_dir.mkdir(exist_ok=True)
    clips = [
        tts.synthesize(cfg, s.narration, clips_dir / f"{i:03}.wav", provider, speed=tts.scene_speed(cfg, s.mood))
        for i, s in enumerate(script.scenes)
    ]
    gaps = tts.scene_gaps(cfg, script.scenes, short=cfg.format == "short")
    spans = tts.join_clips(clips, gaps, job.public / "voice.wav")
    voice_src = None if provider == "silent" else "voice.wav"
    if voice_src:
        tts.master_voice(cfg, job.public / "voice.wav")

    log(job, "fetching visuals")
    scene_media, credits, used = scene_visuals(cfg, job, script, images, topic)
    scene_media = conform_clips(cfg, job, scene_media, spans)
    if credits:
        script = script.model_copy(
            update={"description": script.description.rstrip() + "\n\nImages from Wikimedia Commons:\n" + "\n".join(credits)}
        )
        job.file("script.json").write_text(script.model_dump_json(indent=2), encoding="utf-8")
    chapters = chapter_list(script, spans)
    if chapters:
        script = script.model_copy(update={"description": script.description.rstrip() + "\n\n" + chapters})
        job.file("script.json").write_text(script.model_dump_json(indent=2), encoding="utf-8")
    seconds = (spans[-1][1] if spans else 0) + max(cfg.tail_seconds, 4.0)
    feel = {"calm": "prayer", "cinematic": "motivation"}.get(idea.music, idea.category) if idea else None
    music = media.pick_music(cfg, job.public, category=feel, seconds=seconds)
    credit = media.music_credit(job.public) if music else ""
    if credit and credit not in script.description:
        script = script.model_copy(update={"description": script.description.rstrip() + "\n\nMusic: " + credit})
        job.file("script.json").write_text(script.model_dump_json(indent=2), encoding="utf-8")
    job.file("youtube.txt").write_text(youtube.upload_sheet(cfg, script), encoding="utf-8")

    props = build_props(cfg, script, spans, [c.words for c in clips], scene_media, voice_src, music)
    job.file("props.json").write_text(props.model_dump_json(indent=2), encoding="utf-8")
    job.file("captions.srt").write_text(to_srt(props.captions), encoding="utf-8")

    log(job, f"rendering {props.duration:.0f}s {cfg.format} video")
    video = render.render(job.file("props.json"), job.public, job.file("video.mp4"))
    if cfg.mix_loudness is not None and voice_src:
        render.normalize_loudness(video, cfg.mix_loudness)

    log(job, "rendering thumbnail")
    # The subject's own photo makes a better thumbnail than a stock one.
    bg = next((m for i, m in sorted(scene_media.items()) if m.kind == "image" and "wiki" in m.src), None)
    # Otherwise a still from the video's turning point onward (realization, hope): light, not darkness.
    if bg is None:
        late = [i for i, s in enumerate(script.scenes) if s.mood in ("realization", "hope", "strength")]
        order = late + [i for i in sorted(scene_media) if i not in late]
        bg = next((scene_media[i] for i in order if i in scene_media and scene_media[i].kind == "image"), None)
    if bg is None and cfg.stock_footage:
        try:
            bg = media.fetch_photo(cfg, script.thumbnail_query, job.public, "thumb-bg", used)
        except Exception as e:
            log(job, f"warning: no stock thumbnail background: {e}")
    thumb = ThumbnailProps(
        format=cfg.format,
        title=script.thumbnail_text,
        kicker=script.thumbnail_kicker.upper(),
        theme=cfg.theme.model_dump(),
        background=bg,
    )
    job.file("thumbnail.json").write_text(thumb.model_dump_json(indent=2), encoding="utf-8")
    render.render(job.file("thumbnail.json"), job.public, job.file("thumbnail.png"), still=True)
    if extras:
        quote_cards(cfg, job, extras, bg)

    problems = qa.check_render(cfg, props, video, voiced=provider != "silent")
    status = "qa_failed" if problems else ("ready" if cfg.require_review else "approved")
    job.update(status=status, problems=problems, duration=props.duration)
    log(job, f"done: {status}" + (f" -- {problems}" if problems else ""))


def quote_cards(cfg: Config, job: Job, extras: "growth.Extras", background: Media | None) -> None:
    """Square quote-card images (quote-1.png, ...) for the Community tab and other platforms."""
    for i, card in enumerate(extras.quote_cards, 1):
        props = QuoteCardProps(text=card.text, reference=card.reference, channel=cfg.channel.name, theme=cfg.theme.model_dump(), background=background)
        path = job.file(f"quote-{i}.json")
        path.write_text(props.model_dump_json(indent=2), encoding="utf-8")
        try:
            render.render(path, job.public, job.file(f"quote-{i}.png"), still=True, composition="QuoteCard")
        except Exception as e:
            log(job, f"warning: quote card {i} not rendered: {e}")
            return


def chapter_list(script: Script, spans: list[tuple[float, float]]) -> str:
    """YouTube chapter timestamps for the description, or "" when YouTube wouldn't accept them
    (it needs at least 3 chapters, the first at 0:00, each at least 10 seconds long)."""
    marks = [c for c in script.chapters or [] if 0 <= c.scene < len(spans)]
    if len(marks) < 3 or marks[0].scene != 0:
        return ""
    starts = [0.0] + [spans[c.scene][0] for c in marks[1:]]
    ends = starts[1:] + [spans[-1][1]]
    if any(e - s < 10 for s, e in zip(starts, ends)):
        return ""
    stamp = lambda t: f"{int(t) // 60}:{int(t) % 60:02}"  # noqa: E731
    return "Chapters:\n" + "\n".join(f"{stamp(t)} {c.title}" for t, c in zip(starts, marks))


def narration_words(script: Script) -> int:
    return sum(len(s.narration.split()) for s in script.scenes)


def scene_visuals(
    cfg: Config, job: Job, script: Script, images: list["wiki.WikiImage"], topic: str
) -> tuple[dict[int, Media], list[str], set[str]]:
    """Pick a visual for each scene: the article image the script chose, else stock
    footage for the scene's search query. Returns media per scene, image credits,
    and the stock ids used."""
    used: set[str] = set()
    scene_media: dict[int, Media] = {}
    credits: list[str] = []
    taken: set[int] = set()
    (job.public / "media").mkdir(parents=True, exist_ok=True)
    for i, s in enumerate(script.scenes):
        n = s.image
        if n is not None and 1 <= n <= len(images) and n not in taken:
            im = images[n - 1]
            ext = im.url.rsplit(".", 1)[-1].split("?")[0].lower()
            rel = f"media/wiki{n}.{ext if ext in ('jpg', 'jpeg', 'png', 'webp') else 'jpg'}"
            try:
                wiki.download_image(im, job.public / rel)
            except Exception as e:
                log(job, f"warning: could not download {im.title}: {e}")
            else:
                scene_media[i] = Media(src=rel, kind="image")
                credits.append(im.credit)
                taken.add(n)
                continue
        # Every moment gets a picture: the scene's own search, else imagery for its mood.
        # Data scenes (charts, numbers) read best on the plain background.
        wants_stock = s.type not in ("stat", "bars") and (s.broll_query or s.mood or s.type == "broll")
        if wants_stock:
            try:
                queries = [q for q in [s.broll_query, *media.mood_queries(s.mood, i)] if q] or [s.heading or topic]
                m = media.fetch_broll(cfg, queries, job.public, f"s{i + 1}", used)
            except Exception as e:  # stock footage is optional; fall back to the plain background
                log(job, f"warning: no stock footage for scene {i + 1}: {e}")
                m = None
            if m:
                scene_media[i] = m
    # Open on the subject: if the title scene has nothing, give it the first unused article image.
    if 0 not in scene_media and script.scenes and images:
        n = next((k for k in range(1, len(images) + 1) if k not in taken), None)
        if n is not None:
            im = images[n - 1]
            rel = f"media/wiki{n}.jpg"
            try:
                wiki.download_image(im, job.public / rel)
                scene_media[0] = Media(src=rel, kind="image")
                credits.append(im.credit)
            except Exception as e:
                log(job, f"warning: could not download {im.title}: {e}")
    log(job, f"visuals: {sum(1 for m in scene_media.values() if 'wiki' in m.src)} article images, "
        f"{sum(1 for m in scene_media.values() if 'wiki' not in m.src)} stock, "
        f"{len(script.scenes) - len(scene_media)} scenes on plain background")
    return scene_media, credits, used


CROSSFADE_SECONDS = 0.8  # renderer/src/scenes CROSSFADE: a scene runs on under the next one


def conform_clips(
    cfg: Config, job: Job, scene_media: dict[int, Media], spans: list[tuple[float, float]], tail: float | None = None
) -> dict[int, Media]:
    """Make every video clip safe for the renderer and long enough for its scene (see
    media.conform_clip). A clip that can't be converted becomes a still from it, or is dropped."""
    from fyt.render import dims

    width, height = dims(cfg.format)
    out = dict(scene_media)
    for i, m in scene_media.items():
        if m.kind != "video" or i >= len(spans):
            continue
        start = 0.0 if i == 0 else spans[i][0]
        end = spans[i + 1][0] if i + 1 < len(spans) else spans[-1][1] + (tail or cfg.tail_seconds) + 4
        seconds = end - start + CROSSFADE_SECONDS + 0.5
        src = job.public / m.src
        dst = src.with_name(src.stem + "-cfr.mp4")
        try:
            media.conform_clip(src, dst, seconds, width, height)
            out[i] = Media(src=str(Path(m.src).with_name(dst.name)).replace("\\", "/"), kind="video")
            src.unlink(missing_ok=True)
        except Exception as e:
            log(job, f"warning: clip for scene {i + 1} can't be used as video ({e}); using a still from it")
            still = src.with_suffix(".jpg")
            try:
                media.still_from_clip(src, still)
                out[i] = Media(src=str(Path(m.src).with_suffix(".jpg")).replace("\\", "/"), kind="image")
            except Exception:
                out.pop(i, None)
    return out


def wiki_attribute(script: Script, article: "wiki.Article") -> Script:
    """CC BY-SA requires attribution: put it in the description and sources."""
    description = script.description.rstrip()
    if article.attribution not in description:
        description += "\n\n" + article.attribution
    sources = script.sources if article.url in script.sources else [article.url, *script.sources]
    return script.model_copy(update={"description": description, "sources": sources})


def upload_job(cfg: Config, job: Job, force: bool = False, publish_at: datetime | None = None) -> str:
    status = job.meta.get("status")
    if status == "uploaded":
        raise SystemExit(f"{job.id} is already uploaded: https://youtu.be/{job.meta.get('youtube_id')}")
    if status not in ("approved", "upload_failed") and not force:
        raise SystemExit(f"{job.id} is '{status}'. Review it, then `python -m fyt approve {job.id}` (or --force).")
    script = Script.model_validate_json(job.file("script.json").read_text(encoding="utf-8"))
    cfg = cfg.model_copy(update={"format": job.meta.get("format", cfg.format)})  # e.g. #Shorts in the description
    video_id = youtube.upload(
        cfg, script, job.file("video.mp4"), job.file("thumbnail.png"), job.file("captions.srt"), publish_at=publish_at
    )
    job.update(status="uploaded", youtube_id=video_id, publish_at=publish_at.isoformat() if publish_at else None)
    if script.series and youtube.can_manage():
        try:
            youtube.add_to_playlist(video_id, script.series)
        except Exception as e:  # the video is up; the playlist is a nice-to-have
            print(f"warning: not added to the {script.series!r} playlist: {e}")
    if cfg.format == "long":
        queue_cuts(cfg, script, video_id)
    return video_id


CUT = "cut:"


def queue_cuts(cfg: Config, script: Script, video_id: str) -> None:
    """Queue Shorts cut from a long video; they fill the next regular Short slots."""
    try:
        cuts = growth.cut_scripts(cfg, script, video_id, cfg.growth.cuts_per_long)
    except Exception as e:
        print(f"warning: no Shorts cut from {video_id}: {e}")
        return
    folder = cfg.jobs_path / "cuts"
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for i, cut in enumerate(cuts, 1):
        name = f"{video_id}-{i}"
        (folder / f"{name}.json").write_text(cut.model_dump_json(indent=2), encoding="utf-8")
        names.append(CUT + name)
    if names:
        Topics(cfg).add(names)
        print(f"queued {len(names)} Shorts cut from https://youtu.be/{video_id}")


def catalog_topic(cfg: Config, topics: Topics, category: str | None = None) -> tuple[int, str] | None:
    """The next idea from the curated list, queued and returned. Tops the list up first when it runs low."""
    used = set(topics.titles())
    if cfg.catalog.ideate_when_empty:
        try:
            catalog.top_up(cfg, used, category, topics.recent(12))
        except Exception as e:  # the curated list still works without new ideas
            print(f"warning: could not add new ideas: {e}")
    from fyt import liturgy

    season = liturgy.season(cfg, datetime.now().date()) if cfg.liturgy.season_bias else {}
    idea = catalog.pick(cfg, used, category=category, recent=topics.recent(8), season=season)
    if idea is None:
        return None
    topics.add([idea.topic])
    return topics.find(idea.topic)


def next_topic(
    cfg: Config, topics: Topics, ideate_when_empty: int = 10, category: str | None = None
) -> tuple[int, str] | None:
    """The next topic to make, refilling the queue when it runs dry. A slot that asks for a
    category (the weekly plan) gets an idea from that category first."""
    nxt = None
    if cfg.source == "catalog" and category:
        nxt = catalog_topic(cfg, topics, category)
    if nxt is not None:
        return nxt
    if cfg.format == "long" and cfg.source == "wikipedia":
        nxt = long_topic(cfg, topics)
    elif cfg.format == "long":  # Shorts cut from long videos only fill Short slots
        nxt = topics.next_pending(exclude_prefix=CUT)
    else:
        nxt = topics.next_pending(prefix=CUT) or topics.next_pending(exclude_prefix=CUT)
    if nxt is None and cfg.source == "catalog":
        nxt = catalog_topic(cfg, topics)
    if nxt is None and ideate_when_empty:
        if cfg.seed_topics:
            topics.add(cfg.seed_topics)
        nxt = topics.next_pending()
        if nxt is None and cfg.source == "wikipedia":
            titles = growth.pick_topics(cfg, min(ideate_when_empty, 3), set(topics.titles()), performance=performance_summary(cfg))
            topics.add([wiki.topic_for(t) for t in titles])
            nxt = topics.next_pending()
        if nxt is None and (cfg.source != "catalog" or cfg.catalog.ideate_when_empty):
            topics.add(llm.ideate_topics(cfg, ideate_when_empty, topics.titles(), performance_summary(cfg)))
            nxt = topics.next_pending(exclude_prefix=CUT)
    return nxt


def make_planned(cfg: Config, topics: Topics, topic: str, category: str | None = None) -> Job | None:
    """Make a specific video (a Christian-calendar campaign video) for its slot. If it fails,
    the slot still gets a video: the next evergreen idea."""
    found = topics.find(topic)
    if found and topics.status(found[0]) == "done":
        print(f"{topic} was already made; using the next idea for this slot")
        return make_next(cfg, topics, category=category)
    topics.add([topic])
    topic_id, _ = topics.find(topic)
    topics.set(topic_id, "in_progress")
    try:
        job = make_topic(cfg, topic)
    except Exception as e:
        topics.set(topic_id, "failed")
        print(f"::warning::calendar video failed: {topic}: {e}; using the next idea for this slot")
        return make_next(cfg, topics, category=category)
    topics.set(topic_id, "done", job.id)
    return job


def make_next(cfg: Config, topics: Topics, attempts: int = 3, category: str | None = None) -> Job | None:
    """Make a video from the next topic that works, trying up to `attempts` topics."""
    for _ in range(attempts):
        try:
            nxt = next_topic(cfg, topics, category=category)
        except Exception as e:  # Wikipedia or the LLM is down
            print(f"::warning::could not pick a topic: {e}")
            return None
        if nxt is None:
            print("no topics available")
            return None
        topic_id, topic = nxt
        topics.set(topic_id, "in_progress")
        try:
            job = make_topic(cfg, topic)
        except Exception as e:
            topics.set(topic_id, "failed")
            print(f"::warning::failed: {topic}: {e}")
            continue
        topics.set(topic_id, "done", job.id)
        return job
    return None


def make_topic(cfg: Config, topic: str) -> Job:
    """A queued topic -> video. Cuts from long videos come with their script ready."""
    if not topic.startswith(CUT):
        return make_video(cfg, topic)
    path = cfg.jobs_path / "cuts" / f"{topic[len(CUT):]}.json"
    job = make_video(cfg, topic, script=load_script(path), polish=True)
    path.unlink(missing_ok=True)
    return job


def run_queue(cfg: Config, count: int = 1, ideate_when_empty: int = 10) -> list[Job]:
    """Take the next topics from the queue, build videos, upload the ones that need no review."""
    topics = Topics(cfg)
    done: list[Job] = []
    for _ in range(count):
        nxt = next_topic(cfg, topics, ideate_when_empty)
        if nxt is None:
            print("no topics available")
            break
        topic_id, topic = nxt
        topics.set(topic_id, "in_progress")
        try:
            job = make_topic(cfg, topic)
        except Exception as e:
            topics.set(topic_id, "failed")
            print(f"failed: {topic}: {e}")
            continue
        topics.set(topic_id, "done", job.id)
        if job.meta.get("status") == "approved":
            if not youtube.authorised():
                print("::warning::not uploaded: add the YOUTUBE_TOKEN_JSON secret to turn on uploads")
                job.update(status="ready")
            else:
                try:
                    upload_job(cfg, job)
                    Uploads(cfg).record(cfg.format, job.id, job.meta["youtube_id"], None)
                except Exception as e:  # keep the video; it is still saved with the run
                    print(f"::error::upload failed for {job.id}: {e}")
                    job.update(status="upload_failed", upload_error=str(e)[:500])
        done.append(job)
    return done


def long_topic(cfg: Config, topics: Topics) -> tuple[int, str] | None:
    """A fresh article with enough material for a long video. The queue is filled with
    Short-sized articles, so long videos pick their own."""
    titles = growth.pick_topics(
        cfg, 1, set(topics.titles()), min_chars=cfg.wikipedia.long_min_chars, performance=performance_summary(cfg)
    )
    if not titles:
        return None
    topics.add([wiki.topic_for(titles[0])])
    return topics.find(wiki.topic_for(titles[0]))


def performance_summary(cfg: Config, limit: int = 10) -> str:
    """Top uploaded videos by views, fed back into topic ideation."""
    uploaded = {j.meta["youtube_id"] for j in list_jobs(cfg) if j.meta.get("youtube_id")}
    uploaded |= set(Uploads(cfg).video_ids())
    if not uploaded or not youtube.can_manage():  # reading stats needs more than the upload scope
        return ""
    try:
        rows = youtube.stats(list(uploaded))
    except Exception as e:  # stats are a nice-to-have
        print(f"warning: could not fetch stats: {e}")
        return ""
    rows.sort(key=lambda r: r["views"], reverse=True)
    return "\n".join(f"- {r['title']}: {r['views']} views, {r['likes']} likes" for r in rows[:limit])


def load_script(path: Path) -> Script:
    return Script.model_validate(json.loads(path.read_text(encoding="utf-8")))
