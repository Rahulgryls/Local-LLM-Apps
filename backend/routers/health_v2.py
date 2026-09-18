"""
LAKO V2 — Health & Reindex Router

GET    /api/v2/health            — Qdrant collection stats + cache stats
GET    /api/v2/ready             — Model readiness check (true after warm-up)
POST   /api/v2/reindex/{doc_id}  — Re-summarise + re-embed a single document
POST   /api/v2/reindex           — Rebuild entire Qdrant collection from SQLite
DELETE /api/v2/clear             — Wipe all V2 data (Qdrant + SQLite + cache)

Session 4: added /api/v2/ready and cache_stats field on /api/v2/health.
"""

from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from cache import query_cache
from db.document_store import get_document, clear_all_documents
from ingestion.embedder_v2 import collection_stats, reindex_all, reindex_document, COLLECTION_NAME, _get_qdrant
from services.auth_deps import require_permission

logger = structlog.get_logger(__name__)
router = APIRouter()


# ── Pydantic models ────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    qdrant_status:  str
    points_count:   int = 0
    vectors_count:  int = 0
    collection:     str
    error:          str = ""
    cache_stats:    dict = {}


class ReadyResponse(BaseModel):
    ready:           bool
    llm:             bool
    embedder:        bool
    model_name:      str
    embedding_model: str


class ReindexResponse(BaseModel):
    status:  str
    message: str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get(
    "/v2/health",
    response_model=HealthResponse,
    summary="Qdrant collection health + cache stats (V2)",
    tags=["V2 Health"],
)
async def v2_health() -> HealthResponse:
    """Return Qdrant collection stats and query-cache occupancy."""
    stats = await collection_stats()
    # Use points_count — vectors_count only reflects the HNSW index
    # which Qdrant only builds above the indexing_threshold (default 10k).
    # points_count is always accurate regardless of index state.
    points = stats.get("points_count") or 0
    return HealthResponse(
        qdrant_status = stats.get("status", "unknown"),
        points_count  = points,
        vectors_count = points,
        collection    = stats.get("collection", ""),
        error         = stats.get("error", ""),
        cache_stats   = query_cache.stats(),
    )


@router.get(
    "/v2/ready",
    response_model=ReadyResponse,
    summary="Model readiness check (V2)",
    tags=["V2 Health"],
)
async def v2_ready() -> ReadyResponse:
    """
    Returns true only after both the LLM and the embedding model have
    responded to their startup warm-up requests.

    Poll this endpoint after server start to know when queries will be fast.
    """
    from services.model_warmer import get_status
    s = get_status()
    return ReadyResponse(
        ready           = bool(s["llm"] and s["embedder"]),
        llm             = bool(s["llm"]),
        embedder        = bool(s["embedder"]),
        model_name      = s["model_name"] or "",
        embedding_model = s["embedding_model"] or "",
    )


@router.post(
    "/v2/reindex/{doc_id}",
    response_model=ReindexResponse,
    summary="Re-summarise and re-embed a single document (V2)",
    tags=["V2 Health"],
    dependencies=[Depends(require_permission("admin"))],
)
async def reindex_document_endpoint(
    doc_id: str,
    background_tasks: BackgroundTasks,
) -> ReindexResponse:
    """Trigger a background re-index for *doc_id* (re-runs LLM summariser)."""
    doc = await get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id!r} not found")

    background_tasks.add_task(_run_reindex_document, doc_id)
    return ReindexResponse(
        status  = "accepted",
        message = f"Reindex started for {doc['filename']} ({doc_id})",
    )


@router.post(
    "/v2/reindex",
    response_model=ReindexResponse,
    summary="Rebuild entire Qdrant collection from SQLite (V2)",
    tags=["V2 Health"],
    dependencies=[Depends(require_permission("admin"))],
)
async def reindex_all_endpoint(
    background_tasks: BackgroundTasks,
) -> ReindexResponse:
    """Drop + recreate the Qdrant collection and re-embed all existing summaries."""
    background_tasks.add_task(_run_reindex_all)
    return ReindexResponse(
        status  = "accepted",
        message = "Full reindex started. Poll GET /api/v2/health for point count.",
    )


class ClearResponse(BaseModel):
    status:         str
    deleted_docs:   int
    deleted_points: int


@router.delete(
    "/v2/clear",
    response_model=ClearResponse,
    summary="Wipe all V2 data (Qdrant + SQLite + cache)",
    tags=["V2 Health"],
    dependencies=[Depends(require_permission("admin"))],
)
async def clear_v2() -> ClearResponse:
    """
    Permanently delete all V2 data:
      • Drops and recreates the Qdrant collection (all vectors gone)
      • Deletes all rows in documents, pages, page_summaries (SQLite)
      • Clears the query cache

    This cannot be undone. Documents must be re-ingested.
    """
    # ── Qdrant: count then drop+recreate ──────────────────────────────────────
    stats  = await collection_stats()
    points = stats.get("points_count") or 0

    client = await _get_qdrant()
    try:
        await client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    from ingestion.embedder_v2 import ensure_collection
    await ensure_collection()

    # ── SQLite: wipe all tables ───────────────────────────────────────────────
    deleted_docs = await clear_all_documents()

    # ── Cache ─────────────────────────────────────────────────────────────────
    await query_cache.clear()

    # BM25 index is now empty — rebuild immediately (will return 0 docs, cheap)
    try:
        from config import get_config as _get_cfg
        if _get_cfg().get("hybrid_search_enabled", True):
            from retrieval.bm25_index import rebuild_bm25_index
            await rebuild_bm25_index()
    except Exception as _bm25_exc:
        logger.warning("bm25_rebuild_failed", error=str(_bm25_exc))

    logger.info("v2_clear_complete", deleted_docs=deleted_docs, deleted_points=points)
    return ClearResponse(
        status         = "cleared",
        deleted_docs   = deleted_docs,
        deleted_points = points,
    )


# ── Background helpers ─────────────────────────────────────────────────────────

async def _run_reindex_document(doc_id: str) -> None:
    try:
        await reindex_document(doc_id)
        await query_cache.clear()   # stale answers may reference old summaries
        try:
            from config import get_config as _get_cfg
            if _get_cfg().get("hybrid_search_enabled", True):
                from retrieval.bm25_index import rebuild_bm25_index
                await rebuild_bm25_index()
        except Exception as _bm25_exc:
            logger.warning("bm25_rebuild_failed", error=str(_bm25_exc))
        logger.info("reindex_document_done_cache_cleared", doc_id=doc_id)
    except Exception as exc:
        logger.error("reindex_document_failed", doc_id=doc_id, error=str(exc))


async def _run_reindex_all() -> None:
    try:
        total = await reindex_all()
        await query_cache.clear()
        try:
            from config import get_config as _get_cfg
            if _get_cfg().get("hybrid_search_enabled", True):
                from retrieval.bm25_index import rebuild_bm25_index
                await rebuild_bm25_index()
        except Exception as _bm25_exc:
            logger.warning("bm25_rebuild_failed", error=str(_bm25_exc))
        logger.info("reindex_all_done", total_points=total)
    except Exception as exc:
        logger.error("reindex_all_failed", error=str(exc))
