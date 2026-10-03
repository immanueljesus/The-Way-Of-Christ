"""Keep the channel's publish slots filled ahead of time.

`fyt fill` looks at the next few days of publish slots (config `schedule`), makes a
video for each empty one and uploads it with YouTube's scheduled publishing
(`publishAt`). Videos sit on YouTube as "scheduled" until their slot, so a run that
fails, or a scheduled run GitHub skips, only shrinks the buffer; the next run refills
it and no publish is missed. A video whose upload fails is kept in jobs/pending/ and
uploaded by a later run.
"""

from __future__ import annotations

import random
import re
import shutil
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as dtime
from zoneinfo import ZoneInfo

from fyt import pipeline, youtube
from fyt.config import Config
from fyt.store import Job, Topics, Uploads

# The YouTube Data API quota resets at midnight Pacific time.
PACIFIC = ZoneInfo("America/Los_Angeles")
LEAD_MINUTES = 30  # a slot this close is left alone: the upload might not finish in time
# Rough time to make one video on the free 2-core runner, to avoid starting one the job can't finish.
MAKE_MINUTES = {"short": 10, "long": 80}
KEEP = ("video.mp4", "thumbnail.png", "captions.srt", "script.json", "job.json")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Slot:
    at: datetime
    kind: str  # short | long
    category: str | None = None  # from the weekly plan: the catalog category to draw from
    minutes: float | None = None  # from the weekly plan: the long video's length
    label: str = ""
    topic: str | None = None  # a specific video for this slot (a Christian-calendar campaign video)

    @property
    def key(self) -> str:
        return self.at.isoformat()


def _at(day: date, hhmm: str, tz: str = "UTC") -> datetime:
    """A publish time on a day, in the schedule's time zone (so daylight saving is followed), as UTC."""
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, dtime(h, m), tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)


def upcoming_slots(cfg: Config, now: datetime) -> list[Slot]:
    """Publish slots from now (plus a lead time) to the end of the buffer, earliest first."""
    sc = cfg.schedule
    start = now + timedelta(minutes=LEAD_MINUTES)
    short_end = now + timedelta(days=sc.buffer_days)
    long_end = now + timedelta(days=sc.long_lead_days)
    slots = []
    tz = sc.timezone
    day = now.astimezone(ZoneInfo(tz)).date() - timedelta(days=1)  # days in the schedule's own time zone
    while day <= max(short_end, long_end).date() + timedelta(days=1):
        for hhmm in sc.short_slots:
            at = _at(day, hhmm, tz)
            if start <= at <= short_end:
                slots.append(Slot(at, "short"))
        if sc.long_weekday is not None and day.weekday() == sc.long_weekday:
            at = _at(day, sc.long_slot, tz)
            if start <= at <= long_end:
                slots.append(Slot(at, "long"))
        for p in sc.plan:
            at = _at(day, p.time, tz)
            end = short_end if p.kind == "short" else long_end
            if p.weekday == day.weekday() and start <= at <= end:
                slots.append(Slot(at, p.kind, p.category, p.minutes, p.label))
        day += timedelta(days=1)
    unique = {s.key: s for s in slots}  # plan entries come later, so one wins a clash with a daily slot
    for s in calendar_slots(cfg, now, unique):
        unique[s.key] = s
    return sorted(unique.values(), key=lambda s: s.at)


def calendar_slots(cfg: Config, now: datetime, regular: dict[str, Slot]) -> list[Slot]:
    """Christian-calendar campaign videos (fyt/liturgy.py) in the coming `liturgy.lead_days`.

    A campaign long video takes that day's long slot from the weekly plan (keeping its time) or gets
    its own at liturgy.long_time; campaign Shorts get their own slots at liturgy.short_times, on top
    of the day's regular Shorts. So the evergreen engine keeps running while a campaign is on."""
    from fyt import liturgy

    lt = cfg.liturgy
    if not lt.enabled:
        return []
    start = now + timedelta(minutes=LEAD_MINUTES)
    end = now + timedelta(days=lt.lead_days)
    out: list[Slot] = []
    used_times: dict[tuple, int] = {}
    for e in liturgy.entries(cfg, start.date(), end.date()):
        if e.kind == "long":
            same_day = [s for s in regular.values() if s.kind == "long" and s.at.date() == e.on and not s.topic]
            at = same_day[0].at if same_day else _at(e.on, lt.long_time, cfg.schedule.timezone)
        else:
            k = used_times.get((e.on, "short"), 0)
            used_times[(e.on, "short")] = k + 1
            if k >= len(lt.short_times):
                continue  # more campaign Shorts on one day than slots for them
            at = _at(e.on, lt.short_times[k], cfg.schedule.timezone)
        if start <= at <= end:
            out.append(Slot(at, e.kind, None, e.minutes or (cfg.target_minutes if e.kind == "long" else None),
                            f"{e.event}: {e.title}", e.topic))
    return out


def make_minutes(slot: Slot, cfg: Config) -> float:
    """Rough time to make this slot's video on the free runner (long videos scale with length)."""
    if slot.kind == "short" or not slot.minutes:
        return MAKE_MINUTES[slot.kind]
    return max(MAKE_MINUTES["long"] * slot.minutes / 8, 30)  # ~80 minutes for 8 minutes of video


def slot_config(cfg: Config, slot: Slot) -> Config:
    """The channel config for making this slot's video."""
    update: dict = {"format": slot.kind}
    if slot.minutes:
        update["target_minutes"] = slot.minutes
    return cfg.model_copy(update=update)


def empty_slots(cfg: Config, now: datetime) -> list[Slot]:
    filled = Uploads(cfg).filled()
    return [s for s in upcoming_slots(cfg, now) if s.key not in filled]


def uploads_left_today(cfg: Config, now: datetime) -> int:
    day_start = now.astimezone(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0)
    used = Uploads(cfg).count_since(day_start.astimezone(timezone.utc).isoformat(timespec="seconds"))
    return max(0, cfg.schedule.max_uploads_per_day - used)


def pending_jobs(cfg: Config) -> list[Job]:
    folder = cfg.jobs_path / "pending"
    if not folder.exists():
        return []
    return [Job(p) for p in sorted(folder.iterdir()) if (p / "job.json").exists()]


def _keep_pending(cfg: Config, job: Job) -> None:
    """Save a made-but-not-uploaded video so a later run can upload it (jobs/pending is cached)."""
    dst = cfg.jobs_path / "pending" / job.id
    if dst == job.path:
        return
    dst.mkdir(parents=True, exist_ok=True)
    for name in KEEP:
        if job.file(name).exists():
            shutil.copy(job.file(name), dst / name)
    print(f"kept {job.id} to upload in a later run")


def _is_quota_error(e: Exception) -> bool:
    return "quota" in str(e).lower()


def publish_time(cfg: Config, slot: Slot, rng: random.Random | None = None) -> datetime:
    jitter = cfg.youtube.publish_jitter_minutes
    return slot.at + timedelta(minutes=(rng or random).uniform(0, jitter) if jitter else 0)


def _upload(
    cfg: Config, job: Job, slot: Slot, rng: random.Random | None, now: datetime, kind: str | None = None
) -> bool | None:
    """Upload a job into a slot. True on success, None when the daily quota ran out, False otherwise."""
    # A long render can outlast a near slot; YouTube needs publishAt in the future.
    earliest = utcnow() + timedelta(minutes=youtube.MIN_PUBLISH_LEAD_MINUTES)
    publish_at = max(publish_time(cfg, slot, rng), earliest)
    try:
        video_id = pipeline.upload_job(cfg, job, publish_at=publish_at)
    except Exception as e:
        print(f"::warning::upload of {job.id} failed: {e}")
        job.update(status="upload_failed", upload_error=str(e)[:500])
        return None if _is_quota_error(e) else False
    key = None if kind else slot.key  # bonus videos fill no slot
    Uploads(cfg).record(kind or slot.kind, job.id, video_id, publish_at.isoformat(), key, at=now.isoformat(timespec="seconds"))
    print(f"scheduled https://youtu.be/{video_id} ({kind or slot.kind}) for {publish_at:%a %d %b %H:%M} UTC")
    return True


ARTICLE = re.compile(r'Based on the Wikipedia article "(.+?)" \(')
SLOT_SLACK_MINUTES = 60  # a publish time can land past the jitter window when a render ran long


def sync(cfg: Config, now: datetime) -> int:
    """Recover the schedule from the channel itself, so a lost or reset state cache can't double-book
    slots or repeat topics. Returns how many uploads were new to the local state."""
    from fyt import wiki

    try:
        videos = youtube.recent_uploads()
    except (Exception, SystemExit) as e:  # e.g. an upload-only token; the local state is all we have then
        print(f"::warning::could not read the channel's uploads to check the schedule: {e}")
        return 0
    uploads, topics = Uploads(cfg), Topics(cfg)
    known = set(uploads.video_ids())
    filled = uploads.filled()
    slots = upcoming_slots(cfg, now)
    window = timedelta(minutes=cfg.youtube.publish_jitter_minutes + SLOT_SLACK_MINUTES)
    added = 0
    for v in videos:
        m = ARTICLE.search(v["description"])
        if m:
            topics.mark_done(wiki.topic_for(m.group(1)))
        if v["id"] in known:
            continue
        slot = None
        if v["publish_at"]:
            at = datetime.fromisoformat(v["publish_at"])
            slot = next((s for s in slots if s.key not in filled and s.at <= at <= s.at + window), None)
        uploaded = v["uploaded"] and datetime.fromisoformat(v["uploaded"]).isoformat(timespec="seconds")
        uploads.record(slot.kind if slot else "channel", None, v["id"], v["publish_at"], slot.key if slot else None, at=uploaded)
        if slot:
            filled[slot.key] = (v["id"], v["publish_at"])
            print(f"slot {slot.at:%a %d %b %H:%M} already has https://youtu.be/{v['id']}")
        added += 1
    return added


def fill(cfg: Config, now: datetime | None = None, rng: random.Random | None = None, clock=time.monotonic) -> int:
    """Make and upload videos for the empty slots. Returns how many slots were filled."""
    if cfg.require_review:
        raise SystemExit("fill uploads automatically: set require_review: false in channel.yaml")
    if not youtube.authorised():
        raise SystemExit("fill needs YouTube access: add the YOUTUBE_TOKEN_JSON secret")
    now = now or utcnow()
    started = clock()
    sync(cfg, now)
    budget = uploads_left_today(cfg, now)
    free = empty_slots(cfg, now)
    print(f"{len(free)} empty slots in the next {cfg.schedule.buffer_days:g} days; {budget} uploads left today")
    filled = 0

    # Videos made earlier whose upload failed go first: they cost no rendering.
    for job in pending_jobs(cfg):
        kind = job.meta.get("format", "short")
        slot = next((s for s in free if s.kind == kind), None)
        if slot is None or budget <= 0:
            continue
        result = _upload(cfg, job, slot, rng, now)
        if result:
            shutil.rmtree(job.path)
            free.remove(slot)
            budget -= 1
            filled += 1
        elif result is None:
            budget = 0

    topics = Topics(cfg)
    failures = 0
    for slot in list(free):
        if budget <= 0:
            print("daily upload quota used up; the next run continues")
            break
        elapsed = (clock() - started) / 60
        if elapsed + make_minutes(slot, cfg) > cfg.schedule.max_run_minutes:
            print(f"not enough time left in this run for a {slot.kind} video; the next run continues")
            continue  # a Short may still fit after a skipped long video
        if slot.topic:
            job = pipeline.make_planned(slot_config(cfg, slot), topics, slot.topic, category=slot.category)
        else:
            job = pipeline.make_next(slot_config(cfg, slot), topics, category=slot.category)
        if job is None or job.meta.get("status") != "approved":
            failures += 1
            if failures >= 3:
                print("::warning::3 videos in a row failed; stopping this run")
                break
            continue
        result = _upload(cfg, job, slot, rng, now)
        if result:
            budget -= 1
            filled += 1
        else:
            _keep_pending(cfg, job)
            if result is None:
                budget = 0

    # The schedule comes first; bonus videos only use what's left of the quota and the run.
    if budget > 0 and failures < 3:
        filled += bonus(cfg, now, rng, clock, started, budget, topics)
    return filled


BONUS_MIN_FIT = {"short": "bonus_min_fit", "long": "bonus_long_min_fit"}


def bonus_due(cfg: Config, fmt: str, now: datetime) -> bool:
    """Whether a trending bonus video of this format is allowed now."""
    g = cfg.growth
    per_day = g.bonus_shorts_per_day if fmt == "short" else g.bonus_longs_per_week / 7
    if per_day <= 0:
        return False
    uploads = Uploads(cfg)
    skip = uploads.note(f"bonus-{fmt}-skip-until")  # nothing fitting was trending when we last looked
    if skip and skip > now.isoformat():
        return False
    last = uploads.last(f"bonus-{fmt}")
    return last is None or last <= (now - timedelta(days=1 / per_day)).isoformat(timespec="seconds")


def bonus(cfg: Config, now: datetime, rng, clock, started: float, budget: int, topics: Topics) -> int:
    """Extra videos on topics trending on Wikipedia that fit the channel. Returns how many were uploaded."""
    from fyt import growth, wiki

    made = 0
    for fmt in ("short", "long"):
        if budget <= 0 or not bonus_due(cfg, fmt, now):
            continue
        if (clock() - started) / 60 + MAKE_MINUTES[fmt] > cfg.schedule.max_run_minutes:
            print(f"not enough time left for a bonus {fmt} video")
            continue
        min_chars = cfg.wikipedia.long_min_chars if fmt == "long" else cfg.wikipedia.min_chars
        try:
            title = growth.pick_trending(cfg, set(topics.titles()), getattr(cfg.growth, BONUS_MIN_FIT[fmt]), min_chars)
        except Exception as e:
            print(f"::warning::could not check trending topics: {e}")
            continue
        if title is None:
            print(f"nothing trending fits the channel for a bonus {fmt} right now")
            Uploads(cfg).set_note(f"bonus-{fmt}-skip-until", (now + timedelta(hours=6)).isoformat())
            continue
        topic = wiki.topic_for(title)
        topics.add([topic])
        topic_id, _ = topics.find(topic)
        topics.set(topic_id, "in_progress")
        vcfg = cfg.model_copy(update={"format": fmt})
        try:
            job = pipeline.make_video(vcfg, topic)
        except Exception as e:
            topics.set(topic_id, "failed")
            print(f"::warning::bonus {fmt} failed: {topic}: {e}")
            continue
        topics.set(topic_id, "done", job.id)
        if job.meta.get("status") != "approved":
            continue
        # Trending topics go out soon: at a random minute within the jitter window from now.
        result = _upload(cfg, job, Slot(utcnow(), fmt), rng, now, kind=f"bonus-{fmt}")
        if result:
            budget -= 1
            made += 1
        elif result is None:
            budget = 0
    return made


def report(cfg: Config, now: datetime | None = None) -> tuple[str, list[Slot]]:
    """A markdown table of the coming slots, and the ones in the next 24 hours that are still empty."""
    now = now or utcnow()
    filled = Uploads(cfg).filled()
    rows = ["| Goes live (UTC) | Kind | Plan | Video |", "|---|---|---|---|"]
    for s in upcoming_slots(cfg, now):
        video = f"https://youtu.be/{filled[s.key][0]}" if s.key in filled else "**empty**"
        rows.append(f"| {s.at:%a %d %b %H:%M} | {s.kind} | {s.label or s.category or ''} | {video} |")
    pending = pending_jobs(cfg)
    if pending:
        rows.append(f"\n{len(pending)} made video(s) waiting to be uploaded.")
    soon = [s for s in upcoming_slots(cfg, now) if s.key not in filled and s.at <= now + timedelta(days=1)]
    return "\n".join(rows), soon


def needed(cfg: Config, now: datetime | None = None) -> bool:
    """Whether a fill run has anything to do (so a run can skip installing the renderer)."""
    now = now or utcnow()
    work = bool(empty_slots(cfg, now)) or bonus_due(cfg, "short", now) or bonus_due(cfg, "long", now)
    return work and uploads_left_today(cfg, now) > 0
