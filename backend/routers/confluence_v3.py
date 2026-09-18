"""
LAKO — Confluence V3 Ingestion Router

Ingests Confluence pages (root + optional recursive sub-pages) into the
V3 Qdrant collection (lako_documents) — the same store used by uploaded
documents, so all content is queried together.

Endpoints:
  POST /api/v3/ingest/confluence          — Queue ingestion job, return job_id
  GET  /api/v3/ingest/confluence/{job_id}/status — Poll job progress

Auth:
  Atlassian Cloud: provide both email + api_token → Basic auth
  Server / DC:     provide api_token only          → Bearer token

Pipeline per page:
  1. Fetch page HTML via Confluence REST API
  2. Parse HTML → text chunks (reuse confluence_client.parse_page_content)
  3. Hash content → dedup check (skip if unchanged, replace if updated)
  4. Embed via nomic-embed-text → upsert to lako_documents Qdrant collection
  5. Record in SQLite with source_id = "confluence:{page_id}"
  6. Evict old vectors AFTER new doc is fully indexed (ingest-first, swap-after)
"""

import hashlib
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db.chunk_store import (
    create_doc,
    delete_doc_and_chunks,
    find_by_hash,
    find_by_source_id,
    get_chunk_qdrant_ids,
    init_chunk_db,
    insert_chunk,
    update_doc_status,
)
from services.confluence_client import confluence_client
from services.ollama_client import ollama_client

logger = structlog.get_logger(__name__)

router = APIRouter()

COLLECTION_NAME = "lako_documents"
VECTOR_SIZE     = 768   # nomic-embed-text

# In-memory job tracker
_jobs: dict[str, dict] = {}


# ── Pydantic models ────────────────────────────────────────────────────────────

class ConfluenceV3IngestRequest(BaseModel):
    url:            str
    email:          Optional[str] = None   # only needed for Basic (Classic token) auth
    api_token:      Optional[str] = None
    auth_type:      str = "bearer"         # "bearer" (OAuth) or "basic" (Classic API token)
    crawl_subpages: bool = True


class ConfluenceV3StatusResponse(BaseModel):
    job_id:         str
    status:         str            # queued | crawling | processing | complete | failed
    pages_found:    int
    pages_done:     int
    chunks_total:   int
    current_page:   str
    errors:         list[str]
    error:          Optional[str]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/v3/ingest/confluence",
    summary="Ingest Confluence page(s) into V3 Qdrant index",
    tags=["V3 Confluence"],
)
async def ingest_confluence_v3(
    request: ConfluenceV3IngestRequest,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """
    Queue a Confluence ingestion job.

    - Set crawl_subpages=true  to ingest the root page + all descendants.
    - Set crawl_subpages=false to ingest the root page only.

    For Atlassian Cloud provide **both** email and api_token.
    For Server/DC provide api_token only.

    Returns job_id — poll GET /api/v3/ingest/confluence/{job_id}/status.
    """
    url = request.url.strip()
    if not url.startswith(("http://", "https://")):
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid URL. Must start with http:// or https://"},
        )

    try:
        confluence_client.extract_page_id(url)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    await init_chunk_db()

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status":       "queued",
        "pages_found":  0,
        "pages_done":   0,
        "chunks_total": 0,
        "current_page": "",
        "errors":       [],
        "error":        None,
    }

    background_tasks.add_task(
        _run_pipeline,
        job_id,
        request.url.strip(),
        request.email,
        request.api_token,
        request.auth_type,
        request.crawl_subpages,
    )

    return JSONResponse({
        "job_id":  job_id,
        "status":  "queued",
        "message": f"Poll GET /api/v3/ingest/confluence/{job_id}/status for progress.",
    })


@router.get(
    "/v3/ingest/confluence/{job_id}/status",
    response_model=ConfluenceV3StatusResponse,
    summary="Poll Confluence V3 ingestion job status",
    tags=["V3 Confluence"],
)
async def confluence_v3_status(job_id: str) -> ConfluenceV3StatusResponse:
    if job_id not in _jobs:
        return JSONResponse(status_code=404, content={"error": "Job not found."})
    j = _jobs[job_id]
    return ConfluenceV3StatusResponse(
        job_id       = job_id,
        status       = j["status"],
        pages_found  = j["pages_found"],
        pages_done   = j["pages_done"],
        chunks_total = j["chunks_total"],
        current_page = j["current_page"],
        errors       = j["errors"],
        error        = j["error"],
    )


# ── Background pipeline ────────────────────────────────────────────────────────

async def _run_pipeline(
    job_id:         str,
    root_url:       str,
    email:          Optional[str],
    api_token:      Optional[str],
    auth_type:      str,
    crawl_subpages: bool,
) -> None:
    job = _jobs[job_id]
    base_url = confluence_client._base_url(root_url)

    try:
        # ── Step 1: Collect page IDs ──────────────────────────────────────────
        job["status"] = "crawling"
        job["current_page"] = "Discovering pages..."

        if crawl_subpages:
            page_ids = await confluence_client.collect_all_page_ids(
                root_url, api_token, email, auth_type
            )
        else:
            page_ids = [confluence_client.extract_page_id(root_url)]

        job["pages_found"] = len(page_ids)
        logger.info("confluence_v3_pages_found", job_id=job_id, count=len(page_ids))

        # ── Step 2: Ingest each page ──────────────────────────────────────────
        job["status"] = "processing"

        await _ensure_qdrant_collection()

        for page_id in page_ids:
            try:
                await _ingest_single_page(job_id, job, base_url, page_id, email, api_token, auth_type)
            except Exception as exc:
                msg = f"Page {page_id}: {exc}"
                job["errors"].append(msg)
                logger.warning("confluence_v3_page_failed", page_id=page_id, error=str(exc))
            job["pages_done"] += 1

        job["status"]       = "complete"
        job["current_page"] = ""
        logger.info(
            "confluence_v3_complete",
            job_id=job_id,
            pages=job["pages_done"],
            chunks=job["chunks_total"],
        )
        # Rebuild BM25 index so ingested Confluence pages are searchable by keyword
        try:
            from config import get_config as _get_cfg
            if _get_cfg().get("hybrid_search_enabled", True):
                from retrieval.bm25_index import rebuild_bm25_index
                await rebuild_bm25_index()
        except Exception as _bm25_exc:
            logger.warning("bm25_rebuild_failed", error=str(_bm25_exc))

    except Exception as exc:
        job["status"] = "failed"
        job["error"]  = str(exc)
        logger.error("confluence_v3_pipeline_failed", job_id=job_id, error=str(exc))


async def _ingest_single_page(
    job_id:    str,
    job:       dict,
    base_url:  str,
    page_id:   str,
    email:     Optional[str],
    api_token: Optional[str],
    auth_type: str = "bearer",
) -> None:
    """Full ingest pipeline for one Confluence page (ingest-first, swap-after)."""
    source_id = f"confluence:{page_id}"

    # Fetch page
    page_info = await confluence_client.fetch_page_by_id(
        base_url, page_id, api_token, email, auth_type
    )
    title = page_info["title"]
    job["current_page"] = title

    # Hash content for dedup
    content_hash = hashlib.sha256(page_info["content"].encode()).hexdigest()

    existing = await find_by_hash(content_hash)
    if existing and existing["status"] == "indexed":
        logger.info("confluence_page_unchanged", page_id=page_id, title=title)
        return  # content identical — skip

    # Detect previous version by source_id (may differ in hash = content changed)
    prev = await find_by_source_id(source_id)

    # Parse HTML → chunks
    raw_chunks = confluence_client.parse_page_content(page_info["content"])
    if not raw_chunks:
        logger.info("confluence_page_empty", page_id=page_id, title=title)
        return

    # Create SQLite doc record
    doc_id = str(uuid.uuid4())
    await create_doc(
        doc_id      = doc_id,
        filename    = title,
        file_hash   = content_hash,
        source_type = "confluence",
        source_id   = source_id,
    )
    await update_doc_status(doc_id, "embedding")

    # Embed and upsert to Qdrant
    from ingestion.embedder_v2 import _get_qdrant
    from qdrant_client.http.models import PointStruct

    client      = await _get_qdrant()
    chunk_count = 0

    for i, chunk in enumerate(raw_chunks):
        text = chunk["text"].strip()
        if not text:
            continue
        try:
            vector    = await ollama_client.embed(text)
            qdrant_id = str(uuid.uuid5(
                uuid.NAMESPACE_DNS, f"{doc_id}:{i}:{text[:80]}"
            ))
            point = PointStruct(
                id     = qdrant_id,
                vector = vector,
                payload = {
                    "doc_id":      doc_id,
                    "source_id":   source_id,
                    "page_id":     page_id,
                    "filename":    title,
                    "source_type": "confluence",
                    "block_type":  chunk["metadata"]["type"],
                    "page":        i,
                    "url":         page_info["url"],
                    "updated":     page_info.get("updated", ""),
                    "text":        text,
                },
            )
            await client.upsert(collection_name=COLLECTION_NAME, points=[point])
            await insert_chunk(
                chunk_id    = str(uuid.uuid4()),
                doc_id      = doc_id,
                page        = i,
                block_type  = chunk["metadata"]["type"],
                chunk_index = i,
                qdrant_id   = qdrant_id,
            )
            chunk_count += 1
        except Exception as exc:
            logger.warning(
                "confluence_chunk_embed_failed",
                page_id=page_id, chunk_index=i, error=str(exc),
            )

    if chunk_count == 0:
        await update_doc_status(doc_id, "failed", error_message="0 chunks embedded")
        raise RuntimeError(f"0 chunks embedded for page {page_id!r}")

    await update_doc_status(doc_id, "indexed", chunk_count=chunk_count, page_count=1)
    job["chunks_total"] += chunk_count

    # ── Evict old version AFTER new is fully indexed ──────────────────────────
    if prev:
        old_id = prev["id"]
        logger.info("confluence_evicting_old", old_doc_id=old_id, page_id=page_id)
        try:
            from qdrant_client.http.models import Filter, FieldCondition, MatchValue
            await client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=Filter(
                    must=[FieldCondition(key="doc_id", match=MatchValue(value=old_id))]
                ),
            )
        except Exception as exc:
            logger.warning("confluence_old_qdrant_delete_failed", old_doc_id=old_id, error=str(exc))
        await delete_doc_and_chunks(old_id)

    logger.info(
        "confluence_page_indexed",
        page_id=page_id, title=title, chunks=chunk_count,
        replaced=bool(prev),
    )


# ── Qdrant collection bootstrap ───────────────────────────────────────────────

async def _ensure_qdrant_collection() -> None:
    from ingestion.embedder_v2 import _get_qdrant
    from qdrant_client.http.models import Distance, VectorParams

    client      = await _get_qdrant()
    collections = await client.get_collections()
    names       = {c.name for c in collections.collections}

    if COLLECTION_NAME not in names:
        await client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        logger.info("qdrant_collection_created", name=COLLECTION_NAME)
