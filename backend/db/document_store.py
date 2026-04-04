"""
LAKO V2 — SQLite Document Store
Tables: documents, pages, page_summaries

All I/O is async via aiosqlite.
"""

import json
import logging
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)

# Resolves to <project_root>/storage/lako_v2.db
_DB_PATH = Path(__file__).parent.parent.parent / "storage" / "lako_v2.db"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    source_type TEXT NOT NULL,
    total_pages INTEGER,
    file_hash   TEXT,
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status      TEXT DEFAULT 'processing'
);

CREATE TABLE IF NOT EXISTS pages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id     TEXT NOT NULL REFERENCES documents(doc_id),
    page_num   INTEGER NOT NULL,
    raw_text   TEXT NOT NULL,
    headers    TEXT DEFAULT '[]',
    has_tables BOOLEAN DEFAULT FALSE,
    char_count INTEGER,
    UNIQUE(doc_id, page_num)
);

CREATE TABLE IF NOT EXISTS page_summaries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id       TEXT NOT NULL REFERENCES documents(doc_id),
    page_num     INTEGER NOT NULL,
    summary_text TEXT NOT NULL,
    embedded     BOOLEAN DEFAULT FALSE,
    UNIQUE(doc_id, page_num)
);

CREATE INDEX IF NOT EXISTS idx_pages_doc_id     ON pages(doc_id);
CREATE INDEX IF NOT EXISTS idx_summaries_doc_id ON page_summaries(doc_id);
CREATE INDEX IF NOT EXISTS idx_documents_hash   ON documents(file_hash);
"""


def _db_path() -> Path:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


async def init_db() -> None:
    """Create all tables and indexes if they do not exist."""
    async with aiosqlite.connect(_db_path()) as db:
        await db.executescript(_CREATE_SQL)
        await db.commit()
    logger.info("SQLite document store ready at %s", _DB_PATH)


# ── Document CRUD ──────────────────────────────────────────────────────────────

async def create_document(
    doc_id: str,
    filename: str,
    source_type: str,
    file_hash: str,
) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            INSERT INTO documents (doc_id, filename, source_type, file_hash, status)
            VALUES (?, ?, ?, ?, 'processing')
            """,
            (doc_id, filename, source_type, file_hash),
        )
        await db.commit()


async def update_document_status(
    doc_id: str,
    status: str,
    total_pages: Optional[int] = None,
) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        if total_pages is not None:
            await db.execute(
                "UPDATE documents SET status = ?, total_pages = ? WHERE doc_id = ?",
                (status, total_pages, doc_id),
            )
        else:
            await db.execute(
                "UPDATE documents SET status = ? WHERE doc_id = ?",
                (status, doc_id),
            )
        await db.commit()


async def get_document(doc_id: str) -> Optional[dict]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_document_by_hash(file_hash: str) -> Optional[dict]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM documents WHERE file_hash = ? ORDER BY ingested_at DESC LIMIT 1",
            (file_hash,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


# ── Page CRUD ──────────────────────────────────────────────────────────────────

async def insert_page(
    doc_id: str,
    page_num: int,
    raw_text: str,
    headers: list[str],
    has_tables: bool,
    char_count: int,
) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO pages
                (doc_id, page_num, raw_text, headers, has_tables, char_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (doc_id, page_num, raw_text, json.dumps(headers), has_tables, char_count),
        )
        await db.commit()


async def get_page_count(doc_id: str) -> int:
    async with aiosqlite.connect(_db_path()) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM pages WHERE doc_id = ?", (doc_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def get_page_by_num(doc_id: str, page_num: int) -> Optional[dict]:
    """Fetch a single page row by doc_id + page_num."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM pages WHERE doc_id = ? AND page_num = ?", (doc_id, page_num)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_pages(doc_id: str) -> list[dict]:
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM pages WHERE doc_id = ? ORDER BY page_num", (doc_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ── Page-summary CRUD ──────────────────────────────────────────────────────────

async def insert_page_summary(doc_id: str, page_num: int, summary_text: str) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO page_summaries (doc_id, page_num, summary_text, embedded)
            VALUES (?, ?, ?, FALSE)
            """,
            (doc_id, page_num, summary_text),
        )
        await db.commit()


async def mark_page_embedded(doc_id: str, page_num: int) -> None:
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            "UPDATE page_summaries SET embedded = TRUE WHERE doc_id = ? AND page_num = ?",
            (doc_id, page_num),
        )
        await db.commit()


async def get_page_summaries(doc_id: str) -> list[dict]:
    """Return all page_summaries rows for a document, ordered by page_num."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM page_summaries WHERE doc_id = ? ORDER BY page_num", (doc_id,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def get_unembedded_summaries(doc_id: str) -> list[dict]:
    """Return page_summaries rows where embedded=FALSE, ordered by page_num."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM page_summaries
            WHERE doc_id = ? AND embedded = FALSE
            ORDER BY page_num
            """,
            (doc_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def reset_embedded_flag(doc_id: str) -> None:
    """Mark all summaries for a document as not embedded (used before re-indexing)."""
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            "UPDATE page_summaries SET embedded = FALSE WHERE doc_id = ?", (doc_id,)
        )
        await db.commit()


async def reset_all_embedded_flags() -> None:
    """Mark every summary in the table as not embedded (used before full reindex)."""
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute("UPDATE page_summaries SET embedded = FALSE")
        await db.commit()


async def get_all_ready_documents() -> list[dict]:
    """Return all documents with status='ready'."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM documents WHERE status = 'ready' ORDER BY ingested_at"
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


async def clear_all_documents() -> int:
    """Delete all rows from documents, pages, and page_summaries. Returns doc count deleted."""
    async with aiosqlite.connect(_db_path()) as db:
        async with db.execute("SELECT COUNT(*) FROM documents") as cur:
            row = await cur.fetchone()
            count = row[0] if row else 0
        await db.execute("DELETE FROM page_summaries")
        await db.execute("DELETE FROM pages")
        await db.execute("DELETE FROM documents")
        await db.commit()
    return count
