"""Topic queue (SQLite) and per-job state (job.json in each job folder)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fyt.config import Config


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Topics:
    def __init__(self, cfg: Config):
        cfg.jobs_path.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cfg.jobs_path / "state.db")
        self.db.execute(
            """create table if not exists topics (
                id integer primary key,
                topic text not null unique,
                status text not null default 'pending',  -- pending | in_progress | done | failed
                job text,
                created text not null
            )"""
        )
        self.db.commit()

    def add(self, topics: list[str]) -> int:
        cur = self.db.executemany(
            "insert or ignore into topics(topic, created) values (?, ?)", [(t.strip(), now()) for t in topics if t.strip()]
        )
        self.db.commit()
        return cur.rowcount

    def all(self) -> list[tuple]:
        return self.db.execute("select id, topic, status, job from topics order by id").fetchall()

    def titles(self) -> list[str]:
        return [r[0] for r in self.db.execute("select topic from topics")]

    def next_pending(self, prefix: str = "", exclude_prefix: str | None = None) -> tuple[int, str] | None:
        sql, args = "select id, topic from topics where status='pending' and topic like ?", [prefix + "%"]
        if exclude_prefix:
            sql += " and topic not like ?"
            args.append(exclude_prefix + "%")
        return self.db.execute(sql + " order by id limit 1", args).fetchone()

    def find(self, topic: str) -> tuple[int, str] | None:
        return self.db.execute("select id, topic from topics where topic=?", (topic.strip(),)).fetchone()

    def mark_done(self, topic: str) -> None:
        """Record a topic as already made (it stays done if it was)."""
        self.add([topic])
        self.db.execute("update topics set status='done' where topic=? and status='pending'", (topic.strip(),))
        self.db.commit()

    def set(self, topic_id: int, status: str, job: str | None = None) -> None:
        self.db.execute("update topics set status=?, job=coalesce(?, job) where id=?", (status, job, topic_id))
        self.db.commit()


class Uploads:
    """Every upload, and which publish slot it fills. Lives next to the topic queue in state.db."""

    def __init__(self, cfg: Config):
        cfg.jobs_path.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cfg.jobs_path / "state.db")
        self.db.execute(
            """create table if not exists uploads (
                id integer primary key,
                slot text unique,          -- publish slot (UTC ISO time) this video fills; null for one-off uploads
                kind text not null,        -- short | long
                job text,
                youtube_id text,
                publish_at text,
                uploaded text not null
            )"""
        )
        self.db.execute("create table if not exists notes (key text primary key, value text)")
        self.db.commit()

    def note(self, key: str) -> str | None:
        row = self.db.execute("select value from notes where key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_note(self, key: str, value: str) -> None:
        self.db.execute("insert or replace into notes(key, value) values (?, ?)", (key, value))
        self.db.commit()

    def record(
        self, kind: str, job: str, youtube_id: str, publish_at: str | None, slot: str | None = None, at: str | None = None
    ) -> None:
        self.db.execute(
            "insert into uploads(slot, kind, job, youtube_id, publish_at, uploaded) values (?, ?, ?, ?, ?, ?)",
            (slot, kind, job, youtube_id, publish_at, at or now()),
        )
        self.db.commit()

    def filled(self) -> dict[str, tuple[str, str]]:
        """slot -> (youtube_id, publish_at)"""
        rows = self.db.execute("select slot, youtube_id, publish_at from uploads where slot is not null")
        return {r[0]: (r[1], r[2]) for r in rows}

    def video_ids(self) -> list[str]:
        return [r[0] for r in self.db.execute("select youtube_id from uploads where youtube_id is not null")]

    def last(self, kind: str) -> str | None:
        """When the last upload of this kind happened (ISO time), or None."""
        return self.db.execute("select max(uploaded) from uploads where kind=?", (kind,)).fetchone()[0]

    def count_since(self, since: str) -> int:
        return self.db.execute("select count(*) from uploads where uploaded >= ?", (since,)).fetchone()[0]


class Job:
    """A folder under jobs/ holding every artifact for one video."""

    def __init__(self, path: Path):
        self.path = path
        self.public = path / "public"
        self.meta_path = path / "job.json"
        self.meta: dict = json.loads(self.meta_path.read_text()) if self.meta_path.exists() else {}

    @classmethod
    def create(cls, cfg: Config, topic: str) -> "Job":
        slug = "".join(c if c.isalnum() else "-" for c in topic.lower())[:40].strip("-")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        job = cls(cfg.jobs_path / f"{stamp}-{slug}")
        job.public.mkdir(parents=True)
        job.update(topic=topic, status="created", created=now(), format=cfg.format)
        return job

    @property
    def id(self) -> str:
        return self.path.name

    def update(self, **fields) -> None:
        self.meta.update(fields, updated=now())
        self.meta_path.write_text(json.dumps(self.meta, indent=2))

    def file(self, name: str) -> Path:
        return self.path / name


def list_jobs(cfg: Config) -> list[Job]:
    if not cfg.jobs_path.exists():
        return []
    return [Job(p) for p in sorted(cfg.jobs_path.iterdir()) if (p / "job.json").exists()]


def find_job(cfg: Config, ref: str) -> Job:
    p = Path(ref)
    if (p / "job.json").exists():
        return Job(p)
    matches = [j for j in list_jobs(cfg) if j.id.startswith(ref) or ref in j.id]
    if len(matches) != 1:
        raise SystemExit(f"job '{ref}' matched {len(matches)} jobs")
    return matches[0]
