import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import config

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init() -> None:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              id         INTEGER PRIMARY KEY AUTOINCREMENT,
              url        TEXT NOT NULL UNIQUE,
              status     TEXT NOT NULL,
              result     TEXT,
              error      TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")


def find_by_url(url: str) -> Optional[sqlite3.Row]:
    with _lock, _connect() as conn:
        return conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()


def find(job_id: int) -> Optional[sqlite3.Row]:
    with _lock, _connect() as conn:
        return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def upsert_for_post(url: str) -> tuple[sqlite3.Row, bool]:
    """Upsert semantics for POST /jobs.

    Returns (row, enqueued). `enqueued=True` if caller should push job onto
    worker queue (new row, or previously failed and reset to queued).
    """
    with _lock, _connect() as conn:
        now = _now()
        row = conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
        if row is None:
            cur = conn.execute(
                "INSERT INTO jobs (url, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (url, STATUS_QUEUED, now, now),
            )
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (cur.lastrowid,)).fetchone()
            return row, True
        if row["status"] == STATUS_FAILED:
            conn.execute(
                "UPDATE jobs SET status=?, error=NULL, updated_at=? WHERE id=?",
                (STATUS_QUEUED, now, row["id"]),
            )
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
            return row, True
        return row, False


def mark_running(job_id: int) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status=?, updated_at=? WHERE id=?",
            (STATUS_RUNNING, _now(), job_id),
        )


def mark_done(job_id: int, result: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status=?, result=?, error=NULL, updated_at=? WHERE id=?",
            (STATUS_DONE, result, _now(), job_id),
        )


def mark_failed(job_id: int, error: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?",
            (STATUS_FAILED, error, _now(), job_id),
        )


def requeue_running() -> list[int]:
    """On startup: any row left in 'running' from a crash → put back to 'queued'."""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT id FROM jobs WHERE status = ?", (STATUS_RUNNING,)
        ).fetchall()
        if rows:
            conn.execute(
                "UPDATE jobs SET status=?, updated_at=? WHERE status=?",
                (STATUS_QUEUED, _now(), STATUS_RUNNING),
            )
        return [r["id"] for r in rows]


def queued_ids() -> list[int]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT id FROM jobs WHERE status = ? ORDER BY created_at", (STATUS_QUEUED,)
        ).fetchall()
        return [r["id"] for r in rows]
