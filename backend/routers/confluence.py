"""
LAKO — Confluence Ingestion Router
POST /api/ingest/confluence          — Start async ingestion job, returns job_id
GET  /api/ingest/confluence/status   — Poll job progress by job_id
Session 9: Full implementation.
Session 11: Converted to async job pattern with progress polling.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.confluence_client import confluence_client
from services.embedder import embedder
from services.chroma_client import chroma_client
from services.bm25_index import bm25_index
from services.activity_log import activity_log
from services.rag_engine import invalidate_query_cache

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory job tracker for Confluence ingestion
_confluence_jobs: dict = {}


class ConfluenceIngestRequest(BaseModel):
    url: str
    api_token: Optional[str] = None
    mock: bool = False


class ConfluenceJobStatus(BaseModel):
    job_id: str
    status: str          # queued | processing | complete | failed
    progress: int        # 0–100
    message: str
    chunks_indexed: int = 0
    page_title: str = ""
    page_id: str = ""
    error: Optional[str] = None


def _set_job(job_id: str, **kwargs):
    _confluence_jobs[job_id].update(kwargs)


@router.post("/ingest/confluence")
async def ingest_confluence(
    request: ConfluenceIngestRequest,
    background_tasks: BackgroundTasks,
):
    """
    Queue a Confluence page for async ingestion.
    Returns job_id immediately — poll /api/ingest/confluence/status?job_id=...
    """
    url = request.url.strip()

    if not url.startswith(("http://", "https://")):
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid URL. Must start with http:// or https://"},
        )

    try:
        page_id = confluence_client.extract_page_id(url)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    job_id = str(uuid.uuid4())
    _confluence_jobs[job_id] = {
        "status": "queued",
        "progress": 0,
        "message": "Queued — starting shortly...",
        "chunks_indexed": 0,
        "page_title": "",
        "page_id": page_id,
        "error": None,
    }

    background_tasks.add_task(_run_confluence_pipeline, job_id, url, page_id, request)

    return JSONResponse({
        "job_id": job_id,
        "status": "queued",
        "page_id": page_id,
        "message": "Confluence ingestion queued.",
    })


@router.get("/ingest/confluence/status", response_model=ConfluenceJobStatus)
async def confluence_status(job_id: str):
    """Poll Confluence ingestion job status."""
    if job_id not in _confluence_jobs:
        return JSONResponse(status_code=404, content={"error": "Job not found."})

    job = _confluence_jobs[job_id]
    return ConfluenceJobStatus(
        job_id=job_id,
        status=job["status"],
        progress=job["progress"],
        message=job["message"],
        chunks_indexed=job.get("chunks_indexed", 0),
        page_title=job.get("page_title", ""),
        page_id=job.get("page_id", ""),
        error=job.get("error"),
    )


async def _run_confluence_pipeline(
    job_id: str,
    url: str,
    page_id: str,
    request: ConfluenceIngestRequest,
):
    """
    Background task: fetch, parse, embed, and store a Confluence page.
    Progress steps:
      5%  — job started
      20% — page fetched
      40% — chunks parsed
      80% — embeddings generated
      95% — stored in ChromaDB
      100% — done
    """
    _set_job(job_id, status="processing", progress=5, message="Starting Confluence ingestion...")

    try:
        # ── Step 1: Fetch page ───────────────────────────────────────────────
        _set_job(job_id, progress=10, message="Fetching Confluence page...")
        try:
            if request.mock:
                page_info, raw_chunks = confluence_client.generate_mock_data(url, page_id)
            else:
                page_info = await confluence_client.fetch_page(url, request.api_token)
                raw_chunks = confluence_client.parse_page_content(page_info["content"])
        except PermissionError as e:
            _set_job(job_id, status="failed", message=str(e), error=str(e))
            activity_log.append(event_type="confluence", title=url, chunks_indexed=0,
                                 status="failed", error=str(e))
            return
        except FileNotFoundError as e:
            _set_job(job_id, status="failed", message=str(e), error=str(e))
            activity_log.append(event_type="confluence", title=url, chunks_indexed=0,
                                 status="failed", error=str(e))
            return
        except ConnectionError as e:
            _set_job(job_id, status="failed", message=str(e), error=str(e))
            activity_log.append(event_type="confluence", title=url, chunks_indexed=0,
                                 status="failed", error=str(e))
            return
        except Exception as e:
            logger.exception("Unexpected error fetching Confluence page")
            _set_job(job_id, status="failed", message=f"Unexpected error: {e}", error=str(e))
            activity_log.append(event_type="confluence", title=url, chunks_indexed=0,
                                 status="failed", error=str(e))
            return

        page_title = page_info["title"]
        _set_job(job_id, progress=20, message=f"Fetched: '{page_title}'", page_title=page_title)

        if not raw_chunks:
            msg = "No content chunks found. The page may be empty."
            _set_job(job_id, status="failed", message=msg, error=msg)
            activity_log.append(event_type="confluence", title=page_title, chunks_indexed=0,
                                 status="failed", error=msg)
            return

        _set_job(job_id, progress=40, message=f"Parsed {len(raw_chunks)} chunk(s) from '{page_title}'")

        # ── Step 2: Embed ────────────────────────────────────────────────────
        _set_job(job_id, progress=50, message=f"Embedding {len(raw_chunks)} chunk(s)...")
        embed_texts = [
            f"[Confluence: {page_title} | Section: {c['metadata']['type']}]\n{c['text']}"
            for c in raw_chunks
        ]
        try:
            embeddings = await embedder.embed_chunks(embed_texts)
        except Exception as e:
            logger.exception("Embedding failed for Confluence page")
            _set_job(job_id, status="failed", message=f"Embedding failed: {e}", error=str(e))
            activity_log.append(event_type="confluence", title=page_title, chunks_indexed=0,
                                 status="failed", error=str(e))
            return

        _set_job(job_id, progress=80, message=f"Embeddings ready for '{page_title}'")

        # ── Step 3: Store in ChromaDB ────────────────────────────────────────
        _set_job(job_id, progress=85, message="Storing in vector database...")
        now = datetime.now(timezone.utc).isoformat()
        chroma_chunks = [
            {
                "embedding": emb,
                "document":  chunk["text"],
                "metadata": {
                    "filename":   page_title,
                    "page":       0,
                    "chunk_type": chunk["metadata"]["type"],
                    "timestamp":  now,
                    "source":     "confluence",
                    "url":        url,
                    "title":      page_title,
                    "updated":    page_info.get("updated", ""),
                    "author":     page_info.get("author", ""),
                },
            }
            for chunk, emb in zip(raw_chunks, embeddings)
        ]

        try:
            chroma_client.add_chunks(chroma_chunks)
        except Exception as e:
            logger.exception("ChromaDB storage failed for Confluence page")
            _set_job(job_id, status="failed", message=f"Storage failed: {e}", error=str(e))
            activity_log.append(event_type="confluence", title=page_title, chunks_indexed=0,
                                 status="failed", error=str(e))
            return

        bm25_index.mark_dirty()
        invalidate_query_cache()   # new docs may change answers

        # ── Done ─────────────────────────────────────────────────────────────
        chunks_count = len(chroma_chunks)
        _confluence_jobs[job_id].update({
            "status": "complete",
            "progress": 100,
            "chunks_indexed": chunks_count,
            "message": f"Done. {chunks_count} chunk(s) indexed from '{page_title}'.",
            "error": None,
        })

        activity_log.append(
            event_type="confluence",
            title=page_title,
            chunks_indexed=chunks_count,
            status="success",
        )
        logger.info(f"Confluence ingested async: '{page_title}' — {chunks_count} chunks")

    except Exception as e:
        logger.exception("Unexpected error in Confluence background pipeline")
        _set_job(job_id, status="failed", message=str(e), error=str(e))
        activity_log.append(
            event_type="confluence",
            title=_confluence_jobs[job_id].get("page_title") or url,
            chunks_indexed=0,
            status="failed",
            error=str(e),
        )
