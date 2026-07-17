"""A bounded SQLite work queue with leases, attempts, and idempotency keys."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Job:
    job_id: str
    kind: str
    payload: dict[str, Any]
    priority: int
    attempts: int
    max_attempts: int
    lease_token: str | None


class WorkQueue:
    def __init__(self, path: str | Path, *, max_jobs: int = 100, max_payload_bytes: int = 65536):
        if max_jobs <= 0 or max_payload_bytes <= 0:
            raise ValueError("queue limits must be positive")
        self.path = str(path)
        self.max_jobs = max_jobs
        self.max_payload_bytes = max_payload_bytes
        self._connect().close()
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
                kind TEXT NOT NULL, payload TEXT NOT NULL, priority INTEGER NOT NULL,
                status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL, lease_token TEXT, lease_until REAL,
                created REAL NOT NULL, result TEXT)"""
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def enqueue(
        self,
        job_id: str,
        kind: str,
        payload: dict[str, Any],
        *,
        priority: int = 0,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
    ) -> bool:
        encoded = json.dumps(payload, sort_keys=True, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode()) > self.max_payload_bytes:
            raise ValueError("payload exceeds queue byte limit")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        key = idempotency_key or job_id
        now = time.time()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT 1 FROM jobs WHERE idempotency_key=?", (key,)).fetchone()
            if existing is not None:
                return False
            count = db.execute(
                "SELECT count(*) FROM jobs WHERE status IN ('queued','leased')"
            ).fetchone()[0]
            if count >= self.max_jobs:
                raise OverflowError("queue capacity reached")
            try:
                db.execute(
                    "INSERT INTO jobs VALUES (?,?,?,?,?,'queued',0,?,NULL,NULL,?,NULL)",
                    (job_id, key, kind, encoded, priority, max_attempts, now),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def lease(self, worker: str, *, seconds: float = 30.0) -> Job | None:
        if seconds <= 0 or not worker:
            raise ValueError("invalid lease")
        now = time.time()
        token = f"{worker}:{time.monotonic_ns()}"
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE jobs SET status='queued', lease_token=NULL, lease_until=NULL
                WHERE status='leased' AND lease_until < ? AND attempts < max_attempts""",
                (now,),
            )
            db.execute(
                "UPDATE jobs SET status='dead' WHERE status='leased' "
                "AND lease_until < ? AND attempts >= max_attempts",
                (now,),
            )
            row = db.execute(
                """SELECT job_id,kind,payload,priority,attempts,max_attempts FROM jobs
                WHERE status='queued' ORDER BY priority DESC, created ASC LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            updated = db.execute(
                """UPDATE jobs SET status='leased', attempts=attempts+1,
                lease_token=?, lease_until=? WHERE job_id=? AND status='queued'""",
                (token, now + seconds, row[0]),
            ).rowcount
            if updated != 1:
                return None
            return Job(row[0], row[1], json.loads(row[2]), row[3], row[4] + 1, row[5], token)

    def finish(self, job: Job, result: dict[str, Any]) -> None:
        encoded = json.dumps(result, sort_keys=True, allow_nan=False, separators=(",", ":"))
        with self._connect() as db:
            updated = db.execute(
                """UPDATE jobs SET status='succeeded', result=?, lease_token=NULL, lease_until=NULL
                WHERE job_id=? AND status='leased' AND lease_token=?""",
                (encoded, job.job_id, job.lease_token),
            ).rowcount
            if updated != 1:
                raise RuntimeError("stale or invalid lease cannot commit")

    def release(self, job: Job, *, preempted: bool = False) -> None:
        status = "preempted" if preempted else "queued"
        with self._connect() as db:
            updated = db.execute(
                "UPDATE jobs SET status=?, lease_token=NULL, lease_until=NULL "
                "WHERE job_id=? AND status='leased' AND lease_token=?",
                (status, job.job_id, job.lease_token),
            ).rowcount
            if updated != 1:
                raise RuntimeError("stale or invalid lease")

    def status(self, job_id: str) -> str:
        with self._connect() as db:
            row = db.execute("SELECT status FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return str(row[0])
