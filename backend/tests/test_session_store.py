"""
LAKO — Session Store Unit Tests

Tests db/session_store.py against a real (temporary) SQLite file — no mocking,
since aiosqlite against a throwaway file is fast and exercises the actual
schema/queries.

Run from backend/:
    python -m pytest tests/test_session_store.py -v

Coverage:
  - init_session_db() — idempotent table creation
  - touch_session() — insert then update (upsert) semantics
  - append_message() / get_recent_messages() — round trip, oldest-first order
  - get_recent_messages() — respects `limit`, still oldest-first after trimming
  - prune_stale_sessions() — removes sessions + their messages past the cutoff
"""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import aiosqlite

# ── Make sure the backend src dir is on the path ──────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

import db.session_store as session_store


def async_test(coro):
    """Decorator to run async test methods."""
    def wrapper(*args, **kwargs):
        return asyncio.get_event_loop().run_until_complete(coro(*args, **kwargs))
    return wrapper


class TestSessionStore(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_db_path = Path(self._tmpdir.name) / "test_sessions.db"
        self._patcher = patch.object(session_store, "_DB_PATH", tmp_db_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    @async_test
    async def test_init_is_idempotent(self):
        await session_store.init_session_db()
        await session_store.init_session_db()  # must not raise on re-run

    @async_test
    async def test_touch_session_upserts(self):
        await session_store.init_session_db()
        await session_store.touch_session("case-1")
        await session_store.touch_session("case-1")  # second call updates, not duplicates

        async with aiosqlite.connect(session_store._db_path()) as db:
            async with db.execute("SELECT COUNT(*) FROM sessions WHERE session_id = ?", ("case-1",)) as cur:
                row = await cur.fetchone()
                self.assertEqual(row[0], 1)

    @async_test
    async def test_append_and_get_recent_messages_oldest_first(self):
        await session_store.init_session_db()
        await session_store.touch_session("case-2")

        await session_store.append_message("case-2", "user", "What is this document about?")
        await session_store.append_message("case-2", "assistant", "It's a UX case study.")
        await session_store.append_message("case-2", "user", "Which awards did it win?")

        history = await session_store.get_recent_messages("case-2", limit=6)

        self.assertEqual(len(history), 3)
        # Oldest-first: the first user question must come before the follow-up,
        # not the reverse — this is the ordering bug the store is explicitly
        # designed to avoid (SQL naturally returns newest-first without the
        # reverse() in get_recent_messages()).
        self.assertEqual(history[0]["content"], "What is this document about?")
        self.assertEqual(history[1]["content"], "It's a UX case study.")
        self.assertEqual(history[2]["content"], "Which awards did it win?")

    @async_test
    async def test_get_recent_messages_respects_limit(self):
        await session_store.init_session_db()
        await session_store.touch_session("case-3")

        for i in range(10):
            await session_store.append_message("case-3", "user", f"message {i}")

        history = await session_store.get_recent_messages("case-3", limit=4)

        self.assertEqual(len(history), 4)
        # Still oldest-first among the trimmed window: the last 4 of 10 messages,
        # i.e. "message 6".."message 9", in that order.
        self.assertEqual([m["content"] for m in history],
                         ["message 6", "message 7", "message 8", "message 9"])

    @async_test
    async def test_prune_stale_sessions(self):
        await session_store.init_session_db()
        await session_store.touch_session("stale-case")
        await session_store.append_message("stale-case", "user", "old question")

        # Backdate last_active_at well past the cutoff
        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        async with aiosqlite.connect(session_store._db_path()) as db:
            await db.execute(
                "UPDATE sessions SET last_active_at = ? WHERE session_id = ?",
                (old_ts, "stale-case"),
            )
            await db.commit()

        await session_store.touch_session("fresh-case")

        deleted = await session_store.prune_stale_sessions(older_than_days=30)

        self.assertEqual(deleted, 1)
        history = await session_store.get_recent_messages("stale-case", limit=10)
        self.assertEqual(history, [])


if __name__ == "__main__":
    unittest.main()
