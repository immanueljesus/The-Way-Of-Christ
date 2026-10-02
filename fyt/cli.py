"""Command line: python -m fyt <command>. Run with --help for details."""

from __future__ import annotations

import argparse
from pathlib import Path

from fyt import pipeline, tts
from fyt.config import ROOT, load_config
from fyt.store import Topics, find_job, list_jobs


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="fyt", description="Faceless Christian YouTube video pipeline")
    p.add_argument("--config", help="channel config (default: channel.yaml)")
    p.add_argument("--format", choices=["long", "short"], help="override the configured format")
    p.add_argument("--minutes", type=float, help="length of long videos, e.g. 30 for a sleep or prayer video")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="render the bundled demo script offline (no API keys needed)")
    d.add_argument("--voice", default="silent", choices=list(tts.PROVIDERS))

    m = sub.add_parser("make", help="build one video for a topic (no upload)")
    m.add_argument("topic", help='a topic, "idea:<id>" from content/ideas.yaml, or "wiki:<Article title>"')
    m.add_argument("--script", type=Path, help="use an existing script.json instead of calling Claude")
    m.add_argument("--no-research", action="store_true", help="skip web research")
    m.add_argument("--voice", choices=list(tts.PROVIDERS))

    t = sub.add_parser("topics", help="manage the topic queue")
    tsub = t.add_subparsers(dest="action", required=True)
    tsub.add_parser("list")
    ta = tsub.add_parser("add")
    ta.add_argument("topic", nargs="+")
    ti = tsub.add_parser("ideate", help="ask Claude for new topics")
    ti.add_argument("-n", type=int, default=10)
    tc = tsub.add_parser("next", help="queue the next ideas from content/ideas.yaml (keeps the content mix)")
    tc.add_argument("-n", type=int, default=5)
    tc.add_argument("--category", help="only this category, e.g. prayer or bible_story")
    tw = tsub.add_parser("wiki", help="queue niche Wikipedia articles (or name specific ones)")
    tw.add_argument("title", nargs="*", help="article titles; omit to pick from the configured sources")
    tw.add_argument("-n", type=int, default=5)

    r = sub.add_parser("run", help="build the next N queued topics (uploads if review is off)")
    r.add_argument("--count", type=int, default=1)
    r.add_argument("--no-upload", action="store_true", help="only make the videos, even if review is off")

    sub.add_parser("fill", help="make and schedule videos for the empty publish slots (see `schedule`)")
    b = sub.add_parser("buffer", help="show the coming publish slots and which are filled")
    b.add_argument("--check", action="store_true", help="exit with an error if a slot in the next 24 hours is empty")
    b.add_argument("--needed", action="store_true", help="print yes/no: whether `fill` has work to do")

    sub.add_parser("ideas", help="summarise the idea catalog (content/ideas.yaml)")
    sub.add_parser("jobs", help="list jobs and their status")
    a = sub.add_parser("approve", help="mark a reviewed job as approved")
    a.add_argument("job")
    a.add_argument("--upload", action="store_true", help="upload right away")
    u = sub.add_parser("upload", help="upload an approved job")
    u.add_argument("job")
    u.add_argument("--force", action="store_true", help="upload even if not approved")
    sub.add_parser("auth", help="authorise YouTube uploads (opens a browser)")
    sub.add_parser("stats", help="show views for uploaded videos")

    args = p.parse_args(argv)
    cfg = load_config(args.config)
    if args.format:
        cfg.format = args.format
    if args.minutes:
        cfg.target_minutes = args.minutes

    if args.cmd == "demo":
        cfg.stock_footage = False
        cfg.repurpose = False
        cfg.target_minutes = 0.5  # the demo script is short
        script = pipeline.load_script(ROOT / "fixtures" / f"demo_script_{cfg.format}.json")
        job = pipeline.make_video(cfg, "demo: when you feel forgotten", script=script, voice=args.voice)
        print(f"\nVideo: {job.file('video.mp4')}\nThumbnail: {job.file('thumbnail.png')}")
    elif args.cmd == "make":
        if args.no_research:
            cfg.research = False
        script = pipeline.load_script(args.script) if args.script else None
        job = pipeline.make_video(cfg, args.topic, script=script, voice=args.voice)
        print(f"\nVideo: {job.file('video.mp4')}\nReview it, then: python -m fyt approve {job.id} --upload")
    elif args.cmd == "topics":
        topics = Topics(cfg)
        if args.action == "list":
            for row in topics.all():
                print(f"{row[0]:>4}  {row[2]:<12} {row[1]}" + (f"  -> {row[3]}" if row[3] else ""))
        elif args.action == "add":
            print(f"added {topics.add([' '.join(args.topic)])}")
        elif args.action == "next":
            from fyt import catalog

            picked = []
            for _ in range(args.n):
                idea = catalog.pick(cfg, set(topics.titles()), category=args.category)
                if idea is None:
                    break
                topics.add([idea.topic])
                picked.append(idea)
            print(f"added {len(picked)}:")
            for idea in picked:
                print(f"  - {idea.topic}  [{idea.category}] {idea.title}")
        elif args.action == "wiki":
            from fyt import wiki

            titles = args.title or wiki.pick_articles(cfg, args.n, set(topics.titles()))
            print(f"added {topics.add([wiki.topic_for(t) for t in titles])}:")
            for t in titles:
                print(f"  - {t}")
        else:
            from fyt import llm

            ideas = llm.ideate_topics(cfg, args.n, topics.titles(), pipeline.performance_summary(cfg))
            print(f"added {topics.add(ideas)}:")
            for idea in ideas:
                print(f"  - {idea}")
    elif args.cmd == "fill":
        from fyt import schedule

        print(f"filled {schedule.fill(cfg)} slots")
    elif args.cmd == "buffer":
        from fyt import schedule

        if args.needed:
            print("yes" if schedule.needed(cfg) else "no")
            return
        table, soon = schedule.report(cfg)
        print(table)
        if args.check and soon:
            print(f"\n{len(soon)} slot(s) in the next 24 hours have no video yet.")
            raise SystemExit(1)
    elif args.cmd == "run":
        if args.no_upload:
            cfg.require_review = True
        done = pipeline.run_queue(cfg, args.count)
        if not done:
            raise SystemExit(f"no videos were made (asked for {args.count})")
        if len(done) < args.count:
            # Some videos are ready to download, so the run still counts as a success.
            print(f"::warning::only {len(done)} of {args.count} videos were made; see the log for why")
        for job in done:
            if job.meta.get("youtube_id"):
                print(f"{job.id}: https://youtu.be/{job.meta['youtube_id']}")
        if any(job.meta.get("status") == "upload_failed" for job in done):
            raise SystemExit("the video was made but the YouTube upload failed; see the error above")
    elif args.cmd == "ideas":
        from fyt import catalog

        print(catalog.summary(cfg))
    elif args.cmd == "jobs":
        for j in list_jobs(cfg):
            m = j.meta
            extra = f" https://youtu.be/{m['youtube_id']}" if m.get("youtube_id") else ""
            print(f"{j.id:<60} {m.get('status', '?'):<10} {m.get('title', m.get('topic', ''))}{extra}")
    elif args.cmd == "approve":
        job = find_job(cfg, args.job)
        if job.meta.get("status") not in {"ready", "qa_failed"}:
            raise SystemExit(f"{job.id} is '{job.meta.get('status')}', nothing to approve")
        job.update(status="approved")
        print(f"approved {job.id}")
        if args.upload:
            pipeline.upload_job(cfg, job)
    elif args.cmd == "upload":
        pipeline.upload_job(cfg, find_job(cfg, args.job), force=args.force)
    elif args.cmd == "auth":
        from fyt import youtube

        youtube.auth()
    elif args.cmd == "stats":
        print(pipeline.performance_summary(cfg, limit=100) or "no uploaded videos yet")


if __name__ == "__main__":
    main()
