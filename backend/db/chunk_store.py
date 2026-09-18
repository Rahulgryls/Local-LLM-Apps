"""
LAKO — Chunk Store (V3 Direct-RAG)

SQLite schema for the direct-chunking pipeline.
DB: storage/lako.db  (separate from V2's lako_v2.db)

Tables:
  documents       — one row per uploaded file, tracks status
  document_chunks — one row per Qdrant point, links chunk → doc
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

_DB_PATH = Path(__file__).parent.parent.parent / "storage" / "lako.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id             TEXT PRIMARY KEY,
  filename       TEXT,
  hash           TEXT UNIQUE,
  source_type    TEXT,
  source_id      TEXT,
  status         TEXT DEFAULT 'pending',
  chunk_count    INTEGER DEFAULT 0,
  page_count     INTEGER DEFAULT 0,
  ingested_at    TEXT,
  indexed_at     TEXT,
  error_message  TEXT,
  ingest_quality TEXT DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS document_chunks (
  id          TEXT PRIMARY KEY,
  doc_id      TEXT REFERENCES documents(id),
  page        INTEGER,
  block_type  TEXT,
  chunk_index INTEGER,
  qdrant_id   TEXT,
  created_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id  ON document_chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_docs_hash      ON documents(hash);
CREATE INDEX IF NOT EXISTS idx_docs_source_id ON documents(source_id);
"""


def _db_path() -> Path:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return _DB_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_chunk_db() -> None:
    """Create tables and indexes if they don't exist. Runs migrations for existing DBs."""
    async with aiosqlite.connect(_db_path()) as db:
        await db.executescript(_SCHEMA)
        await db.commit()

        # Migration: add source_id column to existing databases
        try:
            await db.execute("ALTER TABLE documents ADD COLUMN source_id TEXT")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_docs_source_id ON documents(source_id)"
            )
            await db.commit()
        except Exception:
            pass  # column already exists — safe to ignore

        # Migration: add ingest_quality column to existing databases
        async with db.execute("PRAGMA table_info(documents)") as cur:
            cols = {row[1] async for row in cur}
        if "ingest_quality" not in cols:
            try:
                await db.execute(
                    "ALTER TABLE documents ADD COLUMN ingest_quality TEXT DEFAULT 'unknown'"
                )
                await db.commit()
            except Exception:
                pass  # safe to ignore — column may have been added by another migration


async def find_by_hash(file_hash: str) -> Optional[dict]:
    """Return the most recent document with this SHA-256 hash, or None."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM documents WHERE hash = ? ORDER BY ingested_at DESC LIMIT 1",
            (file_hash,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def create_doc(
    doc_id: str,
    filename: str,
    file_hash: str,
    source_type: str,
    source_id: Optional[str] = None,
) -> None:
    """Insert a new document row with status='processing'."""
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            INSERT INTO documents (id, filename, hash, source_type, source_id, status, ingested_at)
            VALUES (?, ?, ?, ?, ?, 'processing', ?)
            """,
            (doc_id, filename, file_hash, source_type, source_id, _now()),
        )
        await db.commit()


async def find_by_source_id(source_id: str) -> Optional[dict]:
    """Return the most recent indexed document with this source_id, or None.
    source_id is a stable external identifier, e.g. 'confluence:5210370'.
    """
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM documents
            WHERE source_id = ? AND status = 'indexed'
            ORDER BY ingested_at DESC LIMIT 1
            """,
            (source_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_doc_status(
    doc_id: str,
    status: str,
    chunk_count: Optional[int] = None,
    page_count: Optional[int] = None,
    error_message: Optional[str] = None,
    ingest_quality: Optional[str] = None,
) -> None:
    """Update status and optional counters. Sets indexed_at when status='indexed'.

    Args:
        doc_id:         Document UUID.
        status:         New status string (e.g. 'parsing', 'embedding', 'indexed').
        chunk_count:    Total chunks stored; persisted when provided.
        page_count:     Total pages processed; persisted when provided.
        error_message:  Error description; persisted when provided.
        ingest_quality: Quality assessment from probe ('clean'|'mixed'|'suspect'|'unknown').
    """
    parts = ["status = ?"]
    args: list = [status]

    if chunk_count is not None:
        parts.append("chunk_count = ?")
        args.append(chunk_count)
    if page_count is not None:
        parts.append("page_count = ?")
        args.append(page_count)
    if error_message is not None:
        parts.append("error_message = ?")
        args.append(error_message)
    if ingest_quality is not None:
        parts.append("ingest_quality = ?")
        args.append(ingest_quality)
    if status == "indexed":
        parts.append("indexed_at = ?")
        args.append(_now())

    args.append(doc_id)

    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            f"UPDATE documents SET {', '.join(parts)} WHERE id = ?", args
        )
        await db.commit()


async def insert_chunk(
    chunk_id: str,
    doc_id: str,
    page: int,
    block_type: str,
    chunk_index: int,
    qdrant_id: str,
) -> None:
    """Record one chunk's metadata (the full text lives in Qdrant)."""
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO document_chunks
                (id, doc_id, page, block_type, chunk_index, qdrant_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (chunk_id, doc_id, page, block_type, chunk_index, qdrant_id, _now()),
        )
        await db.commit()


async def find_by_filename(filename: str) -> Optional[dict]:
    """Return the most recent indexed document with this filename, or None."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM documents
            WHERE filename = ? AND status = 'indexed'
            ORDER BY ingested_at DESC LIMIT 1
            """,
            (filename,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_chunk_qdrant_ids(doc_id: str) -> list[str]:
    """Return all Qdrant point IDs for a given doc_id."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT qdrant_id FROM document_chunks WHERE doc_id = ?",
            (doc_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [r["qdrant_id"] for r in rows]


async def delete_doc_and_chunks(doc_id: str) -> None:
    """Delete a document and all its chunk rows from SQLite."""
    async with aiosqlite.connect(_db_path()) as db:
        await db.execute("DELETE FROM document_chunks WHERE doc_id = ?", (doc_id,))
        await db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        await db.commit()


async def get_doc(doc_id: str) -> Optional[dict]:
    """Fetch a document row by id."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM documents WHERE id = ?", (doc_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_chunks_for_doc(doc_id: str) -> list[dict]:
    """Return all chunk rows for a document, ordered by page + chunk_index."""
    async with aiosqlite.connect(_db_path()) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM document_chunks
            WHERE doc_id = ?
            ORDER BY page, chunk_index
            """,
            (doc_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
