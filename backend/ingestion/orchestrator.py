"""
LAKO V2 — Ingestion Orchestrator

Entry point for all V2 document ingestion.
Chains three passes sequentially:
  Pass 1 — Structure extraction (PyMuPDF / python-pptx) → SQLite pages
  Pass 2 — LLM page summarisation                       → SQLite page_summaries
  Pass 3 — Embedding                                     → Qdrant

Document lifecycle:
  processing → extracting → summarizing → embedding → ready
                                                    ↘ failed (any phase)

Progress callback signature: fn(doc_id, phase, current, total)
"""

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Callable, Optional

import structlog

from db.document_store import (
    create_document,
    get_document_by_hash,
    get_pages,
    init_db,
    update_document_status,
)
from ingestion.docx_extractor import extract_docx
from ingestion.embedder_v2 import _embed_all_summaries_for_doc, ensure_collection
from ingestion.pdf_extractor import extract_pdf
from ingestion.pptx_extractor import extract_pptx
from ingestion.summarizer import summarize_batch

logger = structlog.get_logger(__name__)

_EXT_TO_SOURCE_TYPE: dict[str, str] = {
    ".pdf":  "pdf",
    ".pptx": "pptx",
    ".docx": "docx",
}


def _sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as fh:
        for block in iter(lambda: fh.read(65_536), b""):
            h.update(block)
    return h.hexdigest()


ProgressCallback = Optional[Callable[[str, str, int, int], None]]
# fn(doc_id, phase, current, total)


async def ingest_document(
    file_path: str,
    source_type: str,
    progress_callback: ProgressCallback = None,
    original_filename: Optional[str] = None,
) -> str:
    """
    Run the full V2 ingestion pipeline for a single document.

    Deduplication: if a SHA-256-identical document is already *ready*,
    return its existing doc_id immediately.

    Args:
        original_filename: The user-facing filename (e.g. "ACROI.pdf").
                           Falls back to the staged file's basename if omitted.

    Returns:
        doc_id — UUID string of the (new or existing) document.
    """
    await init_db()

    path     = Path(file_path)
    filename = original_filename or path.name

    # ── Deduplication ─────────────────────────────────────────────────────────
    file_hash = _sha256(file_path)
    existing  = await get_document_by_hash(file_hash)
    if existing and existing["status"] == "ready":
        logger.info("duplicate_skipped", filename=filename, doc_id=existing["doc_id"])
        return existing["doc_id"]

    # ── Create document record ────────────────────────────────────────────────
    doc_id = str(uuid.uuid4())
    await create_document(
        doc_id=doc_id,
        filename=filename,
        source_type=source_type,
        file_hash=file_hash,
    )
    log = logger.bind(doc_id=doc_id, filename=filename, source_type=source_type)
    log.info("ingestion_started")

    try:
        # ── Pass 1: Structure extraction ──────────────────────────────────────
        await update_document_status(doc_id, "extracting")

        def _extract_cb(current: int, total: int) -> None:
            if progress_callback:
                progress_callback(doc_id, "extracting", current, total)

        if source_type == "pdf":
            total_pages = await extract_pdf(file_path, doc_id, _extract_cb)
        elif source_type == "pptx":
            total_pages = await extract_pptx(file_path, doc_id, _extract_cb)
        elif source_type == "docx":
            total_pages = await extract_docx(file_path, doc_id, _extract_cb)
        else:
            raise ValueError(f"Unsupported source_type: {source_type!r}")

        # total_pages now known — write it to the documents row
        await update_document_status(doc_id, "summarizing", total_pages=total_pages)
        log.info("extraction_complete", total_pages=total_pages)

        # ── Pass 2: Per-page LLM summarisation (batch=1 for reliability with small models)
        pages      = await get_pages(doc_id)   # sorted by page_num
        BATCH_SIZE = 1
        for batch_start in range(0, len(pages), BATCH_SIZE):
            batch_pages = pages[batch_start : batch_start + BATCH_SIZE]
            batch_input = [
                {
                    "doc_id":      doc_id,
                    "page_num":    p["page_num"],
                    "raw_text":    p["raw_text"],
                    "headers":     json.loads(p.get("headers", "[]")),
                    "doc_name":    filename,
                    "total_pages": total_pages,
                }
                for p in batch_pages
            ]
            await summarize_batch(batch_input)
            last_page = batch_pages[-1]["page_num"]
            if progress_callback:
                progress_callback(doc_id, "summarizing", last_page, total_pages)

        await update_document_status(doc_id, "embedding")
        log.info("summarization_complete", total_pages=total_pages)

        # ── Pass 3: Embedding into Qdrant ─────────────────────────────────────
        await ensure_collection()

        def _embed_cb(d: str, phase: str, current: int, total: int) -> None:
            if progress_callback:
                progress_callback(d, phase, current, total)

        await _embed_all_summaries_for_doc(
            doc_id       = doc_id,
            filename     = filename,
            source_type  = source_type,
            progress_callback=_embed_cb,
        )

        await update_document_status(doc_id, "ready")
        log.info("ingestion_complete", total_pages=total_pages)

    except Exception as exc:
        await update_document_status(doc_id, "failed")
        log.error("ingestion_failed", error=str(exc))
        raise

    return doc_id


def source_type_from_path(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    if ext not in _EXT_TO_SOURCE_TYPE:
        raise ValueError(
            f"Unsupported file extension {ext!r}. "
            f"Supported: {list(_EXT_TO_SOURCE_TYPE.keys())}"
        )
    return _EXT_TO_SOURCE_TYPE[ext]
