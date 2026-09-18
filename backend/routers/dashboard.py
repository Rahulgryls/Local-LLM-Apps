"""
LAKO — Dashboard Router
GET /api/dashboard/stats          — Real-time system stats
GET /api/dashboard/recent-activity — Last 10 ingestion events
Session 11: Created.
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter

from config import get_config
from services.chroma_client import chroma_client
from services.ollama_client import ollama_client
from services.api_key_manager import api_key_manager
from services.activity_log import activity_log

router = APIRouter()

# Track server start time so we can report uptime
_START_TIME = time.time()


@router.get("/dashboard/stats")
async def get_stats():
    """
    Returns real-time system stats by querying ChromaDB, Ollama, and API key store.
    """
    config = get_config()

    # ── Vector DB — ChromaDB V1 (legacy) ─────────────────────────────────────
    chroma_stats = chroma_client.get_stats()
    total_chunks = chroma_stats.get("total_chunks", 0)

    pdf_chunks        = 0
    confluence_chunks = 0
    total_documents   = 0
    last_updated      = None

    if total_chunks > 0:
        try:
            all_docs = chroma_client.get_all_documents()
            seen_filenames: set = set()
            for doc in all_docs:
                meta   = doc.get("metadata", {})
                source = meta.get("source", "pdf")
                if source == "confluence":
                    confluence_chunks += 1
                else:
                    pdf_chunks += 1
                fname = meta.get("filename", "")
                if fname:
                    seen_filenames.add(fname)
                ts = meta.get("timestamp")
                if ts:
                    if last_updated is None or ts > last_updated:
                        last_updated = ts
            total_documents = len(seen_filenames)
        except Exception:
            pdf_chunks = total_chunks
            confluence_chunks = 0

    # ── Vector DB — Qdrant V3 (lako_documents: PDFs, DOCX, Confluence V3) ────
    v3_total_chunks      = 0
    v3_confluence_chunks = 0
    v3_doc_chunks        = 0
    v3_documents         = 0
    try:
        from ingestion.embedder_v2 import _get_qdrant
        qdrant = await _get_qdrant()
        collections = {c.name for c in (await qdrant.get_collections()).collections}
        if "lako_documents" in collections:
            info = await qdrant.get_collection("lako_documents")
            v3_total_chunks = info.points_count or 0

            # Count confluence vs document chunks by scrolling payload
            # Use count API with filter for efficiency
            from qdrant_client.http.models import Filter, FieldCondition, MatchValue
            conf_result = await qdrant.count(
                collection_name="lako_documents",
                count_filter=Filter(
                    must=[FieldCondition(
                        key="source_type", match=MatchValue(value="confluence")
                    )]
                ),
                exact=True,
            )
            v3_confluence_chunks = conf_result.count
            v3_doc_chunks        = v3_total_chunks - v3_confluence_chunks

            # Count unique doc_ids via SQLite (fast, no scroll needed)
            from db.chunk_store import init_chunk_db
            import aiosqlite
            from pathlib import Path as _Path
            _db = _Path(__file__).parent.parent.parent / "storage" / "lako.db"
            if _db.exists():
                async with aiosqlite.connect(_db) as db:
                    async with db.execute(
                        "SELECT COUNT(*) FROM documents WHERE status='indexed'"
                    ) as cur:
                        row = await cur.fetchone()
                        v3_documents = row[0] if row else 0
    except Exception:
        pass

    # Merge V1 + V3 totals for top-level cards
    total_chunks    += v3_total_chunks
    confluence_chunks += v3_confluence_chunks
    pdf_chunks        += v3_doc_chunks
    total_documents   += v3_documents

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_reachable = await ollama_client.health_check()
    ollama_status = "healthy" if ollama_reachable else "unreachable"

    # ── API Keys ──────────────────────────────────────────────────────────────
    all_keys = api_key_manager.list_keys()
    active_keys = sum(1 for k in all_keys if k.get("is_active", False))

    # ── Ingestion activity summary ────────────────────────────────────────────
    all_activity = activity_log.recent(limit=50)
    total_jobs = len(all_activity)
    successful_jobs = sum(1 for e in all_activity if e.get("status") == "success")
    skipped_jobs    = sum(1 for e in all_activity if e.get("status") == "skipped")
    failed_jobs     = total_jobs - successful_jobs - skipped_jobs
    last_job_at = all_activity[0].get("timestamp") if all_activity else None

    return {
        "vector_db": {
            "total_chunks": total_chunks,
            "total_documents": total_documents,
            "sources": {
                "pdf": pdf_chunks,
                "confluence": confluence_chunks,
            },
            "last_updated": last_updated,
        },
        "models": {
            "primary": config["primary_model"],
            "vision": config["vision_model"],
            "embeddings": config["embedding_model"],
            "ollama_status": ollama_status,
        },
        "ingestion": {
            "total_jobs": total_jobs,
            "successful": successful_jobs,
            "skipped": skipped_jobs,
            "failed": failed_jobs,
            "last_job_at": last_job_at,
        },
        "api_keys": {
            "total": len(all_keys),
            "active": active_keys,
        },
        "system": {
            "uptime_seconds": int(time.time() - _START_TIME),
            "backend_version": "1.0.0",
        },
    }


@router.get("/dashboard/recent-activity")
async def get_recent_activity():
    """Returns last 10 ingestion events from the activity log."""
    return activity_log.recent(limit=10)
