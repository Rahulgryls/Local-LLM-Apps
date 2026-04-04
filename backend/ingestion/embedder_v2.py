"""
LAKO V2 — Qdrant Embedding Manager (Pass 3)

Embeds page summaries via nomic-embed-text and upserts to Qdrant.
Point IDs are deterministic (uuid5 of doc_id:page_num) so re-runs
are safe upserts, not duplicates.

Public API:
  ensure_collection()          — create collection if missing
  embed_and_upsert(...)        — embed one summary, upsert, mark embedded
  reindex_document(doc_id)     — re-summarise + re-embed a single document
  reindex_all()                — rebuild entire collection from SQLite
  collection_stats()           — Qdrant collection info dict
"""

import json
import logging
import uuid
from typing import Optional

import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from config import get_config
from db.document_store import (
    get_all_ready_documents,
    get_document,
    get_page_summaries,
    get_pages,
    get_unembedded_summaries,
    reset_all_embedded_flags,
    reset_embedded_flag,
    update_document_status,
)
from ingestion.summarizer import summarize_page

logger = structlog.get_logger(__name__)

COLLECTION_NAME = "lako_page_summaries"
VECTOR_SIZE     = 768           # nomic-embed-text output dimension

_qdrant: Optional[AsyncQdrantClient] = None


# ── Qdrant client singleton ────────────────────────────────────────────────────

async def _get_qdrant() -> AsyncQdrantClient:
    global _qdrant
    if _qdrant is None:
        url = get_config().get("qdrant_url", "http://localhost:6333")
        _qdrant = AsyncQdrantClient(url=url)
    return _qdrant


# ── Collection bootstrap ───────────────────────────────────────────────────────

async def ensure_collection() -> None:
    """Create the lako_page_summaries collection if it does not exist."""
    client      = await _get_qdrant()
    collections = await client.get_collections()
    names       = {c.name for c in collections.collections}

    if COLLECTION_NAME not in names:
        await client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        logger.info("qdrant_collection_created", name=COLLECTION_NAME)
    else:
        logger.debug("qdrant_collection_exists", name=COLLECTION_NAME)


# ── Single-point upsert ────────────────────────────────────────────────────────

def _point_id(doc_id: str, page_num: int) -> str:
    """Deterministic UUID from doc_id + page_num (safe for re-runs)."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}:{page_num}"))


async def embed_and_upsert(
    doc_id:       str,
    page_num:     int,
    filename:     str,
    source_type:  str,
    headers:      list[str],
    has_tables:   bool,
    summary_text: str,
) -> None:
    """
    Embed *summary_text* with nomic-embed-text, upsert to Qdrant,
    then mark embedded=TRUE in page_summaries.
    """
    from services.ollama_client import ollama_client   # local import — avoids circular

    vector = await ollama_client.embed(summary_text)

    point = PointStruct(
        id=_point_id(doc_id, page_num),
        vector=vector,
        payload={
            "doc_id":       doc_id,
            "page_num":     page_num,
            "filename":     filename,
            "source_type":  source_type,
            "headers":      " | ".join(headers) if headers else "",
            "has_tables":   has_tables,
            "summary_text": summary_text,
        },
    )

    client = await _get_qdrant()
    await client.upsert(collection_name=COLLECTION_NAME, points=[point])

    from db.document_store import mark_page_embedded
    await mark_page_embedded(doc_id, page_num)


# ── Batch helpers ──────────────────────────────────────────────────────────────

async def _embed_all_summaries_for_doc(
    doc_id:   str,
    filename: str,
    source_type: str,
    progress_callback=None,
) -> int:
    """
    Embed every unembedded summary for doc_id.
    Returns the number of points upserted.
    """
    await ensure_collection()

    summaries  = await get_unembedded_summaries(doc_id)
    pages_dict = {p["page_num"]: p for p in await get_pages(doc_id)}
    total      = len(summaries)

    for i, s in enumerate(summaries, start=1):
        summary_text = s["summary_text"]
        # Skip placeholder summaries — empty text causes Ollama 400
        if not summary_text or summary_text.strip() in ("[Empty page]", "[Summarization failed]"):
            if progress_callback:
                progress_callback(doc_id, "embedding", i, total)
            continue
        page     = pages_dict.get(s["page_num"], {})
        headers  = json.loads(page.get("headers", "[]"))
        await embed_and_upsert(
            doc_id       = doc_id,
            page_num     = s["page_num"],
            filename     = filename,
            source_type  = source_type,
            headers      = headers,
            has_tables   = bool(page.get("has_tables", False)),
            summary_text = summary_text,
        )
        if progress_callback:
            progress_callback(doc_id, "embedding", i, total)

    return total


# ── Re-index public API ────────────────────────────────────────────────────────

async def reindex_document(doc_id: str) -> None:
    """
    Re-summarise every page and re-embed for a single document.

    Steps:
      1. Delete all Qdrant points where payload.doc_id == doc_id
      2. Clear embedded flags in SQLite
      3. Re-summarise all pages (fresh LLM call per page)
      4. Embed all summaries → Qdrant
      5. Set document status back to 'ready'
    """
    doc = await get_document(doc_id)
    if not doc:
        raise ValueError(f"reindex_document: doc_id {doc_id!r} not found")

    log = logger.bind(doc_id=doc_id, filename=doc["filename"])
    log.info("reindex_document_start")

    await update_document_status(doc_id, "reindexing")

    # ── 1. Delete existing Qdrant points ──────────────────────────────────────
    client = await _get_qdrant()
    await ensure_collection()
    await client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
        ),
    )

    # ── 2. Reset embedded flags ───────────────────────────────────────────────
    await reset_embedded_flag(doc_id)

    # ── 3. Re-summarise ───────────────────────────────────────────────────────
    pages      = await get_pages(doc_id)
    total      = len(pages)
    for page in pages:
        headers = json.loads(page.get("headers", "[]"))
        await summarize_page(
            doc_id      = doc_id,
            page_num    = page["page_num"],
            raw_text    = page["raw_text"],
            headers     = headers,
            doc_name    = doc["filename"],
            total_pages = total,
        )

    # ── 4. Re-embed ───────────────────────────────────────────────────────────
    await _embed_all_summaries_for_doc(doc_id, doc["filename"], doc["source_type"])

    await update_document_status(doc_id, "ready")
    log.info("reindex_document_complete")


async def reindex_all() -> int:
    """
    Rebuild the entire Qdrant collection from existing SQLite summaries.

    Does NOT re-run the LLM summariser — uses whatever is in page_summaries.
    Drops and recreates the Qdrant collection, then re-embeds every summary.

    Returns total points upserted.
    """
    logger.info("reindex_all_start")

    # ── Drop + recreate collection ────────────────────────────────────────────
    client = await _get_qdrant()
    try:
        await client.delete_collection(COLLECTION_NAME)
        logger.info("qdrant_collection_deleted", name=COLLECTION_NAME)
    except Exception:
        pass
    await ensure_collection()

    # ── Reset all embedded flags ──────────────────────────────────────────────
    await reset_all_embedded_flags()

    # ── Re-embed per document ─────────────────────────────────────────────────
    docs       = await get_all_ready_documents()
    total_pts  = 0
    for doc in docs:
        n = await _embed_all_summaries_for_doc(
            doc["doc_id"], doc["filename"], doc["source_type"]
        )
        total_pts += n
        logger.info("reindex_all_doc_done", doc_id=doc["doc_id"], points=n)

    logger.info("reindex_all_complete", total_points=total_pts)
    return total_pts


# ── Stats ──────────────────────────────────────────────────────────────────────

async def collection_stats() -> dict:
    """Return basic stats about the Qdrant collection."""
    try:
        client = await _get_qdrant()
        info   = await client.get_collection(COLLECTION_NAME)
        return {
            "status":       str(info.status),
            "points_count": info.points_count,
            "vectors_count": info.vectors_count,
            "collection":   COLLECTION_NAME,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc), "collection": COLLECTION_NAME}
