"""
LAKO V2 — Ingestion Router

POST /api/v2/ingest               — Upload a PDF or PPTX, trigger background extraction.
GET  /api/v2/ingest/{job_id}/status — Poll ingestion progress by job_id.

The *job_id* returned by POST is a stable handle for polling.
Once ingestion completes, the response also includes the permanent *doc_id*
(which may differ from job_id if the file was a duplicate).
"""

import os
import uuid
import logging
from pathlib import Path
from typing import Optional

import aiofiles
import structlog
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from pydantic import BaseModel

from db.document_store import get_document, get_all_ready_documents, init_db
from ingestion.orchestrator import ingest_document, source_type_from_path
from services.activity_log import activity_log

logger = structlog.get_logger(__name__)

router = APIRouter()

# ── In-memory job tracker ─────────────────────────────────────────────────────
# Keyed by job_id (UUID returned at POST time).
# Entries are never deleted so historical polls always return something.
_jobs: dict[str, dict] = {}

# Upload staging directory
_UPLOAD_DIR = Path(__file__).parent.parent.parent / "storage" / "uploads"

# Accepted file extensions → source_type
_SUPPORTED_EXT = {".pdf", ".pptx", ".docx"}


# ── Pydantic models ────────────────────────────────────────────────────────────

class DocumentSummary(BaseModel):
    doc_id:      str
    filename:    str
    source_type: str
    total_pages: Optional[int]
    ingested_at: Optional[str]


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]


class IngestResponse(BaseModel):
    job_id:   str
    doc_id:   Optional[str] = None
    filename: str
    status:   str
    message:  str


class StatusResponse(BaseModel):
    job_id:          str
    doc_id:          Optional[str]
    filename:        str
    status:          str
    phase:           str
    pages_processed: int
    total_pages:     Optional[int]
    error:           Optional[str]


# ── Background task ───────────────────────────────────────────────────────────

async def _run_ingestion(job_id: str, file_path: str, source_type: str, filename: str) -> None:
    """
    Background task that drives the orchestrator and keeps _jobs up-to-date.
    Cleans up the staging file when done (success or failure).
    """
    import time
    _start = time.time()

    _jobs[job_id] = {
        "filename":        filename,
        "status":          "processing",
        "phase":           "extracting",
        "pages_processed": 0,
        "total_pages":     None,
        "doc_id":          None,
        "error":           None,
    }

    def _on_progress(doc_id: str, phase: str, current: int, total: int) -> None:
        entry = _jobs.get(job_id)
        if entry:
            entry["doc_id"]          = doc_id
            entry["phase"]           = phase
            entry["pages_processed"] = current
            entry["total_pages"]     = total

    try:
        real_doc_id = await ingest_document(file_path, source_type, _on_progress, original_filename=filename)
        duration = time.time() - _start
        total_pages = _jobs[job_id].get("total_pages") or 0
        _jobs[job_id].update(
            doc_id          = real_doc_id,
            status          = "ready",
            phase           = "complete",
        )
        activity_log.append(
            event_type       = source_type,
            title            = filename,
            chunks_indexed   = total_pages,
            status           = "success",
            duration_seconds = duration,
            source           = "v2",
        )
        # Invalidate query cache — new document may make previous answers stale
        from cache import query_cache
        await query_cache.clear()
        logger.info("job_complete", job_id=job_id, doc_id=real_doc_id)
    except Exception as exc:
        duration = time.time() - _start
        _jobs[job_id].update(
            status = "failed",
            phase  = "failed",
            error  = str(exc),
        )
        activity_log.append(
            event_type       = source_type,
            title            = filename,
            chunks_indexed   = 0,
            status           = "failed",
            error            = str(exc),
            duration_seconds = duration,
            source           = "v2",
        )
        logger.error("job_failed", job_id=job_id, error=str(exc))
    finally:
        try:
            os.unlink(file_path)
        except Exception:
            pass


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/v2/ingest",
    response_model=IngestResponse,
    summary="Upload and ingest a document (V2)",
    tags=["V2 Ingestion"],
)
async def ingest_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> IngestResponse:
    """
    Accept a PDF, PPTX, or DOCX upload and start the V2 structure-extraction pipeline.

    Returns a **job_id** that can be polled at
    `GET /api/v2/ingest/{job_id}/status`.
    """
    await init_db()

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _SUPPORTED_EXT:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type {suffix!r}. "
                f"Accepted: {sorted(_SUPPORTED_EXT)}"
            ),
        )

    source_type = source_type_from_path(file.filename)
    job_id      = str(uuid.uuid4())

    # Save upload to staging directory
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    staged_path = _UPLOAD_DIR / f"v2_{job_id}{suffix}"

    content = await file.read()
    async with aiofiles.open(staged_path, "wb") as fh:
        await fh.write(content)

    logger.info(
        "ingest_job_queued",
        job_id=job_id,
        filename=file.filename,
        bytes=len(content),
    )

    background_tasks.add_task(
        _run_ingestion, job_id, str(staged_path), source_type, file.filename
    )

    return IngestResponse(
        job_id   = job_id,
        filename = file.filename,
        status   = "processing",
        message  = (
            f"Ingestion started. "
            f"Poll /api/v2/ingest/{job_id}/status for progress."
        ),
    )


@router.get(
    "/v2/ingest/{job_id}/status",
    response_model=StatusResponse,
    summary="Poll ingestion status (V2)",
    tags=["V2 Ingestion"],
)
async def get_status(job_id: str) -> StatusResponse:
    """
    Return live or historical ingestion status for a *job_id*.

    - While the job is running: served from in-memory tracker (real-time page count).
    - After completion: in-memory entry remains and is returned directly.
    - If the job_id is unknown to memory (e.g. after server restart):
      falls back to a SQLite lookup treating job_id as a doc_id.
    """
    # ── In-memory hit (active or recently completed) ──────────────────────────
    if job_id in _jobs:
        e = _jobs[job_id]
        return StatusResponse(
            job_id          = job_id,
            doc_id          = e.get("doc_id"),
            filename        = e.get("filename", ""),
            status          = e.get("status", "unknown"),
            phase           = e.get("phase", "unknown"),
            pages_processed = e.get("pages_processed", 0),
            total_pages     = e.get("total_pages"),
            error           = e.get("error"),
        )

    # ── SQLite fallback (post-restart or doc_id used directly) ────────────────
    doc = await get_document(job_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"No ingestion job or document found for id={job_id!r}",
        )

    total = doc.get("total_pages")
    return StatusResponse(
        job_id          = job_id,
        doc_id          = doc["doc_id"],
        filename        = doc["filename"],
        status          = doc["status"],
        phase           = "complete" if doc["status"] == "ready" else doc["status"],
        pages_processed = total or 0,
        total_pages     = total,
        error           = None,
    )


@router.get(
    "/v2/documents",
    response_model=DocumentListResponse,
    summary="List all ready V2 documents",
    tags=["V2 Ingestion"],
)
async def list_documents() -> DocumentListResponse:
    """Return all documents with status='ready' from the SQLite Document Store."""
    docs = await get_all_ready_documents()
    return DocumentListResponse(
        documents=[
            DocumentSummary(
                doc_id      = d["doc_id"],
                filename    = d["filename"],
                source_type = d["source_type"],
                total_pages = d.get("total_pages"),
                ingested_at = d.get("ingested_at"),
            )
            for d in docs
        ]
    )
