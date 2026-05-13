"""Application-level pending-reviews index — separate from the LangGraph
checkpointer database (PRD §5.1).

The LangGraph checkpointer (``graph.sqlite``) holds per-thread state needed
for ``Command(resume=...)``; this module's ``reviews.sqlite`` holds the
HTTP-facing index of human-review tasks (extraction_id, status, payload).

Both files live in the same persisted Docker volume (``/app/data``) but are
intentionally separate so we can purge resolved reviews without touching
graph state.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import (
    Iterator,  # noqa: TC003 — runtime-required by @contextmanager return annotation
)
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.api.logging import get_logger

logger = get_logger(__name__)


def _default_db_path() -> Path:
    """Return the default reviews DB path.

    Production (Docker) writes to ``/app/data/reviews.sqlite`` (the persisted
    volume).  In dev/test the ``/app`` mount doesn't exist and creating it
    raises ``Read-only file system``.  Fall back to a cwd-relative path so
    tests never need to set ``REVIEWS_DB_PATH``.
    """
    docker_path = Path("/app/data/reviews.sqlite")
    if Path("/app").exists() and os.access("/app", os.W_OK):
        return docker_path
    return Path("./reviews.sqlite")


# All path resolution flows through ``_db_path()`` below so the env var is
# evaluated at call time (Docker volume mount happens after module import).

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_reviews (
    extraction_id     TEXT PRIMARY KEY,
    thread_id         TEXT NOT NULL,
    statement_sha256  TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    status            TEXT NOT NULL
        CHECK(status IN ('pending', 'in_review', 'resolved', 'aborted')),
    suspect_count     INTEGER NOT NULL DEFAULT 0,
    reason            TEXT,
    review_payload    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pending_reviews_status  ON pending_reviews(status);
CREATE INDEX IF NOT EXISTS idx_pending_reviews_created ON pending_reviews(created_at);
"""

_VALID_STATUSES = ("pending", "in_review", "resolved", "aborted")


def _db_path() -> Path:
    """Resolve the reviews DB path at call time so env / tests can override."""
    env = os.environ.get("REVIEWS_DB_PATH")
    if env:
        return Path(env)
    return _default_db_path()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_reviews_db() -> None:
    """Create the reviews schema if missing.  Idempotent."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
    logger.info("reviews: schema ready at %s", _db_path())


def insert_pending(
    *,
    extraction_id: str,
    thread_id: str,
    statement_sha256: str,
    suspect_count: int,
    reason: str | None,
    review_payload: dict[str, Any],
) -> None:
    """Insert a new ``pending`` review row."""
    now = datetime.now(UTC).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO pending_reviews "
            "(extraction_id, thread_id, statement_sha256, created_at, status, "
            " suspect_count, reason, review_payload) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
            (
                extraction_id,
                thread_id,
                statement_sha256,
                now,
                suspect_count,
                reason,
                json.dumps(review_payload, default=str),
            ),
        )


def list_pending(limit: int = 50) -> list[dict[str, Any]]:
    """Return up to ``limit`` rows ordered by created_at DESC."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT extraction_id, statement_sha256, created_at, suspect_count, "
            "       status, reason "
            "FROM pending_reviews ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_review(extraction_id: str) -> dict[str, Any] | None:
    """Fetch one review by id (full payload included).  Returns None if absent."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM pending_reviews WHERE extraction_id = ?",
            (extraction_id,),
        ).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["review_payload"] = json.loads(out["review_payload"])
    return out


def _set_status(extraction_id: str, status: str) -> None:
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}; expected one of {_VALID_STATUSES}")
    with _connect() as conn:
        conn.execute(
            "UPDATE pending_reviews SET status = ? WHERE extraction_id = ?",
            (status, extraction_id),
        )


def mark_in_review(extraction_id: str) -> None:
    _set_status(extraction_id, "in_review")


def mark_resolved(extraction_id: str) -> None:
    _set_status(extraction_id, "resolved")


def mark_aborted(extraction_id: str) -> None:
    _set_status(extraction_id, "aborted")
