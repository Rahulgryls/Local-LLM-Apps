"""
LAKO — Conversation Session Store (MCP)
Tables: sessions, session_messages

Persists conversation turns server-side for callers that can't hold their own
in-memory chat state (e.g. an external MCP client like Pega, which is a separate
remote process — unlike the browser Chat UI, which keeps its own thread in
Zustand and sends it inline with every request).

Deliberately its own DB file, separate from lako_v2.db / lako.db: a session's
history is pipeline-agnostic (search_pages() already merges both the V2 and V3
Qdrant collections), so it doesn't belong to either pipeline's store.

All I/O is async via aiosqlite.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

# Resolves to <project_root>/storage/lako_sessions.db
_DB_PATH = Path(__file__).parent.parent.parent / "storage" / "lako_sessions.db"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id     TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    last_active_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_messages_session_id ON session_messages(session_id);
"""


def _db_path() -> Path:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_session_db() -> None:
    """Create all tables and indexes if they do not exist."""
    async with aiosqlite.connect(_db_path()) as db:
        await db.executescript(_CREATE_SQL)
        await db.commit()
    logger.info("SQLite session store ready at %s", _DB_PATH)


# ── Session CRUD ─────────────────────────────────────────────────────────────

async def touch_session(session_id: str) -> None:
    """Create the session if new, otherwise bump last_active_at."""
    now = _now()
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            INSERT INTO sessions (session_id, created_at, last_active_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET last_active_at = excluded.last_active_at
            """,
            (session_id, now, now),
        )
        await db.commit()


async def append_message(session_id: str, role: str, content: str) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            INSERT INTO session_messages (session_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, role, content, _now()),
        )
        await db.commit()


async def get_recent_messages(session_id: str, limit: int = 6) -> list[dict]:
    """
    Return the last `limit` messages for a session, oldest first.

    Queries newest-first (to LIMIT correctly off the tail of a long
    conversation) then reverses before returning, so callers always get
    chronological order — the order build_query_prompt()/Message expect.
    """
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT role, content, created_at FROM session_messages
            WHERE session_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (session_id, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in reversed(rows)]


async def prune_stale_sessions(older_than_days: int) -> int:
    """
    Delete sessions (and their messages) whose last_active_at is older than
    `older_than_days`. Not called anywhere yet — a future cleanup job can call
    this directly rather than needing a schema migration. Returns count deleted.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - older_than_days * 86400
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()

    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT session_id FROM sessions WHERE last_active_at < ?", (cutoff_iso,)
        ) as cur:
            rows = await cur.fetchall()
        stale_ids = [r["session_id"] for r in rows]

        for session_id in stale_ids:
            await db.execute(
                "DELETE FROM session_messages WHERE session_id = ?", (session_id,)
            )
            await db.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
        await db.commit()

    return len(stale_ids)
