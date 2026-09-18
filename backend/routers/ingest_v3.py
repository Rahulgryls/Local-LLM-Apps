"""
LAKO V3 — Ingestion Router (Direct-RAG pipeline)

POST /api/v3/ingest               — Upload any supported file; returns immediately.
GET  /api/v3/ingest/{job_id}/status — Poll background job progress.
GET  /api/v3/ingest/{doc_id}/file    — Download the stored original file.
GET  /api/v3/documents               — List all indexed V3 documents.

Supported file types: PDF, DOCX, PPTX, XLSX, HTML

V3 differs from V2:
  - Raw text preserved (no LLM summarisation pass)
  - All file types supported (V2: PDF + PPTX only)
  - Chunks go into lako_documents Qdrant collection
  - Metadata in storage/lako.db (not lako_v2.db)
  - Original file saved to storage/documents/{doc_id}/original.{ext}
"""

import os
import uuid
import logging
from pathlib import Path
from typing import Optional

import aiofiles
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from db.chunk_store import get_doc, init_chunk_db, find_by_hash
from ingestion.service import ingest_file, source_type_from_filename
from services.auth_deps import require_permission

logger = structlog.get_logger(__name__)

router = APIRouter()

# ── Config ─────────────────────────────────────────────────────────────────────

_UPLOAD_DIR = Path(__file__).parent.parent.parent / "storage" / "uploads_v3"
_DOCS_DIR   = Path(__file__).parent.parent.parent / "storage" / "documents"

_SUPPORTED_EXT = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"}


# ── In-memory job tracker ─────────────────────────────────────────────────────
# Keyed by job_id (UUID returned at POST time).
# Entries never deleted — historical polls always return something.

_jobs: dict[str, dict] = {}


# ── Pydantic models ────────────────────────────────────────────────────────────

class IngestResponse(BaseModel):
    job_id:   str
    filename: str
    status:   str
    message:  str


class StatusResponse(BaseModel):
    job_id:          str
    doc_id:          Optional[str]
    filename:        str
    status:          str          # processing | parsing | embedding | indexed | replaced | failed | duplicate
    phase:           str
    chunks_indexed:  int
    pages_processed: int
    error:           Optional[str]


class DocumentSummary(BaseModel):
    doc_id:      str
    filename:    str
    source_type: str
    chunk_count: int
    page_count:  int
    ingested_at: Optional[str]
    indexed_at:  Optional[str]


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]


# ── Background task ───────────────────────────────────────────────────────────

async def _run_ingestion(
    job_id:      str,
    file_path:   str,
    filename:    str,
    source_type: str,
) -> None:
    """
    Drives ingest_file() in the background and keeps _jobs up-to-date.
    Cleans up the staging file when done (success or failure).
    """
    import time
    _start = time.time()

    _jobs[job_id] = {
        "filename":        filename,
        "status":          "processing",
        "phase":           "parsing",
        "doc_id":          None,
        "chunks_indexed":  0,
        "pages_processed": 0,
        "total_pages":     None,
        "error":           None,
    }

    def _on_progress(doc_id: str, phase: str, current: int, total: int) -> None:
        entry = _jobs.get(job_id)
        if entry:
            entry["doc_id"] = doc_id
            entry["phase"]  = phase
            if phase == "parsing":
                entry["pages_processed"] = current
                entry["total_pages"]     = total
            elif phase == "embedding":
                entry["chunks_indexed"]  = current

    try:
        result = await ingest_file(
            file_path         = file_path,
            filename          = filename,
            source_type       = source_type,
            progress_callback = _on_progress,
        )
        duration = time.time() - _start

        _jobs[job_id].update(
            doc_id         = result["doc_id"],
            status         = result["status"],   # "indexed" or "duplicate"
            phase          = "complete",
            chunks_indexed = result["chunks"],
            pages_processed= result["pages"],
        )
        logger.info(
            "v3_job_complete",
            job_id=job_id,
            doc_id=result["doc_id"],
            status=result["status"],
            duration_s=round(duration, 1),
        )
        # Rebuild BM25 index so the new document is searchable by keyword
        try:
            from config import get_config as _get_cfg
            if _get_cfg().get("hybrid_search_enabled", True):
                from retrieval.bm25_index import rebuild_bm25_index
                await rebuild_bm25_index()
        except Exception as _bm25_exc:
            logger.warning("bm25_rebuild_failed", error=str(_bm25_exc))

    except Exception as exc:
        _jobs[job_id].update(
            status = "failed",
            phase  = "failed",
            error  = str(exc),
        )
        logger.error("v3_job_failed", job_id=job_id, error=str(exc))

    finally:
        try:
            os.unlink(file_path)
        except Exception:
            pass


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/v3/ingest",
    response_model=IngestResponse,
    summary="Upload and ingest a document (V3 direct-RAG)",
    tags=["V3 Ingestion"],
)
async def ingest_file_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> IngestResponse:
    """
    Accept a document upload and start the V3 direct-RAG ingestion pipeline.

    Supported: PDF, DOCX, PPTX, XLSX, HTML

    Returns a **job_id** to poll at `GET /api/v3/ingest/{job_id}/status`.
    The pipeline runs in the background — this endpoint returns immediately.
    """
    await init_chunk_db()

    suffix = Path(file.filename).suffix.lower()
    if suffix not in _SUPPORTED_EXT:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type {suffix!r}. "
                f"Accepted: {sorted(_SUPPORTED_EXT)}"
            ),
        )

    try:
        source_type = source_type_from_filename(file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc))

    job_id = str(uuid.uuid4())
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    staged_path = _UPLOAD_DIR / f"v3_{job_id}{suffix}"

    content = await file.read()
    async with aiofiles.open(staged_path, "wb") as fh:
        await fh.write(content)

    logger.info(
        "v3_ingest_queued",
        job_id=job_id,
        filename=file.filename,
        bytes=len(content),
        source_type=source_type,
    )

    background_tasks.add_task(
        _run_ingestion, job_id, str(staged_path), file.filename, source_type
    )

    return IngestResponse(
        job_id   = job_id,
        filename = file.filename,
        status   = "processing",
        message  = (
            f"V3 ingestion started. "
            f"Poll GET /api/v3/ingest/{job_id}/status for progress."
        ),
    )


@router.get(
    "/v3/ingest/{job_id}/status",
    response_model=StatusResponse,
    summary="Poll V3 ingestion job status",
    tags=["V3 Ingestion"],
)
async def get_ingest_status(job_id: str) -> StatusResponse:
    """
    Return live or historical ingestion status for a *job_id*.

    - While running: served from in-memory tracker (real-time chunk count).
    - After completion: in-memory entry is returned.
    - Post-restart fallback: SQLite lookup using job_id as doc_id.
    """
    # ── In-memory hit ────────────────────────────────────────────────────────
    if job_id in _jobs:
        e = _jobs[job_id]
        return StatusResponse(
            job_id          = job_id,
            doc_id          = e.get("doc_id"),
            filename        = e.get("filename", ""),
            status          = e.get("status", "unknown"),
            phase           = e.get("phase", "unknown"),
            chunks_indexed  = e.get("chunks_indexed", 0),
            pages_processed = e.get("pages_processed", 0),
            error           = e.get("error"),
        )

    # ── SQLite fallback (treat job_id as doc_id after server restart) ────────
    doc = await get_doc(job_id)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail=f"No V3 job or document found for id={job_id!r}",
        )

    return StatusResponse(
        job_id          = job_id,
        doc_id          = doc["id"],
        filename        = doc["filename"],
        status          = doc["status"],
        phase           = "complete" if doc["status"] == "indexed" else doc["status"],
        chunks_indexed  = doc.get("chunk_count", 0),
        pages_processed = doc.get("page_count", 0),
        error           = doc.get("error_message"),
    )


@router.get(
    "/v3/documents",
    response_model=DocumentListResponse,
    summary="List all V3 indexed documents",
    tags=["V3 Ingestion"],
)
async def list_v3_documents() -> DocumentListResponse:
    """
    Return all documents with status='indexed' from storage/lako.db.
    """
    import aiosqlite
    from pathlib import Path

    db_path = Path(__file__).parent.parent.parent / "storage" / "lako.db"
    if not db_path.exists():
        return DocumentListResponse(documents=[])

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM documents WHERE status = 'indexed' ORDER BY ingested_at DESC"
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]

    return DocumentListResponse(
        documents=[
            DocumentSummary(
                doc_id      = r["id"],
                filename    = r["filename"],
                source_type = r["source_type"],
                chunk_count = r.get("chunk_count", 0),
                page_count  = r.get("page_count", 0),
                ingested_at = r.get("ingested_at"),
                indexed_at  = r.get("indexed_at"),
            )
            for r in rows
        ]
    )


@router.get(
    "/v3/documents/{doc_id}/file",
    summary="Download the stored original file (V3)",
    tags=["V3 Ingestion"],
)
async def download_original_file(doc_id: str):
    """
    Stream the original uploaded file back to the caller.
    File lives at storage/documents/{doc_id}/original.{ext}
    """
    doc_dir = _DOCS_DIR / doc_id
    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"No stored file for doc_id={doc_id!r}")

    # Find the original.* file — there should be exactly one
    candidates = list(doc_dir.glob("original.*"))
    if not candidates:
        raise HTTPException(status_code=404, detail="Original file not found on disk")

    original = candidates[0]

    media_types = {
        ".pdf":  "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".html": "text/html",
        ".htm":  "text/html",
    }
    media_type = media_types.get(original.suffix.lower(), "application/octet-stream")

    doc = await get_doc(doc_id)
    download_name = doc["filename"] if doc else original.name

    return FileResponse(
        path         = str(original),
        media_type   = media_type,
        filename     = download_name,
        headers      = {"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


@router.delete(
    "/v3/documents/{doc_id}",
    summary="Delete a V3 document and all its vectors",
    tags=["V3 Ingestion"],
    dependencies=[Depends(require_permission("admin"))],
)
async def delete_v3_document(doc_id: str) -> dict:
    """
    Remove a document from:
      - Qdrant (all points where payload.doc_id == doc_id)
      - SQLite document_chunks and documents rows
      - Filesystem storage/documents/{doc_id}/
    """
    import shutil as _shutil
    import aiosqlite
    from pathlib import Path
    from ingestion.embedder_v2 import _get_qdrant
    from qdrant_client.http.models import Filter, FieldCondition, MatchValue

    doc = await get_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id!r} not found")

    # ── Qdrant delete ─────────────────────────────────────────────────────────
    try:
        client = await _get_qdrant()
        await client.delete(
            collection_name="lako_documents",
            points_selector=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
        )
    except Exception as exc:
        logger.warning("v3_qdrant_delete_failed", doc_id=doc_id, error=str(exc))

    # ── SQLite delete ─────────────────────────────────────────────────────────
    db_path = Path(__file__).parent.parent.parent / "storage" / "lako.db"
    async with aiosqlite.connect(db_path) as db:
        await db.execute("DELETE FROM document_chunks WHERE doc_id = ?", (doc_id,))
        await db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        await db.commit()

    # ── Filesystem delete ─────────────────────────────────────────────────────
    doc_dir = _DOCS_DIR / doc_id
    if doc_dir.exists():
        _shutil.rmtree(doc_dir, ignore_errors=True)

    logger.info("v3_document_deleted", doc_id=doc_id, filename=doc["filename"])
    return {"status": "deleted", "doc_id": doc_id, "filename": doc["filename"]}
