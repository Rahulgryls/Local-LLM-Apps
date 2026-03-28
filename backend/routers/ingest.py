"""
LAKO — Ingestion Router
POST /api/ingest/docs   — Upload files, run full ingestion pipeline in background
GET  /api/ingest/status — Poll ingestion progress % by job_id
Session 5: PDF + TXT pipeline implemented.
Session 6: Excel, Word, PowerPoint parsers added.
"""

import asyncio
import io
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import aiofiles
from fastapi import APIRouter, BackgroundTasks, UploadFile, File
from fastapi.responses import JSONResponse
from PIL import Image as PILImage
from pydantic import BaseModel

from services.parsers.pdf_parser import pdf_parser
from services.parsers.txt_parser import txt_parser
from services.parsers.excel_parser import excel_parser
from services.parsers.word_parser import word_parser
from services.parsers.ppt_parser import ppt_parser
from services.chunker import chunker
from services.embedder import embedder
from services.chroma_client import chroma_client
from services.vision_service import vision_service

router = APIRouter()

# Uploads directory — files are saved here before parsing
UPLOADS_DIR = Path("/Users/rahul/lako/storage/uploads")
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

# In-memory job tracker — keyed by job_id
# Each entry: { status, progress, files, message, chunk_count, error }
_jobs: dict = {}

# All supported file types (Session 5: pdf, txt — Session 6: xlsx, docx, pptx)
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".xlsx", ".docx", ".pptx"}


class IngestStatusResponse(BaseModel):
    job_id: str
    status: str       # pending / processing / complete / error
    progress: int     # 0–100
    message: str
    chunk_count: int = 0


@router.post("/ingest/docs")
async def ingest_docs(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
):
    """
    Accept one or more files for ingestion (PDF and TXT in Session 5).
    Saves files to /storage/uploads/, runs pipeline in background.
    Returns job_id to poll /api/ingest/status.
    """
    accepted_files = []
    rejected_files = []

    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext in ALLOWED_EXTENSIONS:
            accepted_files.append(f)
        else:
            rejected_files.append(f.filename)

    if not accepted_files:
        return JSONResponse(
            status_code=400,
            content={
                "error": "No supported files. Accepted: PDF, TXT, XLSX, DOCX, PPTX.",
                "rejected": rejected_files,
            },
        )

    # Read file contents now — UploadFile stream is only readable once,
    # before the response is returned, so we buffer in memory here.
    file_data = []
    for f in accepted_files:
        content = await f.read()
        file_data.append({"filename": f.filename, "content": content})

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "pending",
        "progress": 0,
        "files": [fd["filename"] for fd in file_data],
        "message": "Queued — starting shortly...",
        "chunk_count": 0,
    }

    background_tasks.add_task(_run_ingestion_pipeline, job_id, file_data)

    return JSONResponse({
        "job_id": job_id,
        "accepted_files": [fd["filename"] for fd in file_data],
        "rejected_files": rejected_files,
        "message": f"Ingestion started for {len(file_data)} file(s).",
    })


@router.get("/ingest/status")
async def ingest_status(job_id: str):
    """
    Poll ingestion progress by job_id.
    Returns progress 0–100, status string, and chunk count when complete.
    """
    if job_id not in _jobs:
        return JSONResponse(status_code=404, content={"error": "Job not found."})

    job = _jobs[job_id]
    return IngestStatusResponse(
        job_id=job_id,
        status=job["status"],
        progress=job["progress"],
        message=job["message"],
        chunk_count=job.get("chunk_count", 0),
    )


async def _run_ingestion_pipeline(job_id: str, file_data: List[dict]):
    """
    Background task: runs the full ingestion pipeline for each file.
    Progress steps per file:
      5%  — file saved to disk
      30% — parsing complete
      50% — chunking complete
      85% — embedding complete
      95% — stored in ChromaDB
      100% — done
    For N files, each file contributes an equal share of the 0–100 range.
    """
    _set_job(job_id, status="processing", progress=2, message="Starting ingestion...")

    total_files = len(file_data)
    total_chunks = 0

    try:
        for file_index, fd in enumerate(file_data):
            filename = fd["filename"]
            content = fd["content"]
            file_base = file_index / total_files        # 0.0 → 1.0
            file_top = (file_index + 1) / total_files   # 0.0 → 1.0

            def pct(step_frac: float) -> int:
                """Map a per-file fraction (0.0–1.0) to overall progress %."""
                return int((file_base + step_frac / total_files) * 95)

            # ── Step 1: Save file ────────────────────────────────────────
            upload_path = UPLOADS_DIR / filename
            async with aiofiles.open(upload_path, "wb") as f:
                await f.write(content)
            _set_job(job_id, progress=pct(0.05), message=f"Saved {filename}")

            # ── Step 2: Parse ────────────────────────────────────────────
            ext = Path(filename).suffix.lower()
            _set_job(job_id, progress=pct(0.10), message=f"Parsing {filename}...")

            if ext == ".pdf":
                parsed_doc = pdf_parser.parse(upload_path)
            elif ext == ".txt":
                parsed_doc = txt_parser.parse(upload_path)
            elif ext == ".xlsx":
                parsed_doc = excel_parser.parse(upload_path)
            elif ext == ".docx":
                parsed_doc = word_parser.parse(upload_path)
            elif ext == ".pptx":
                parsed_doc = ppt_parser.parse(upload_path)
            else:
                # Should not reach here — filtered at the endpoint
                continue

            _set_job(job_id, progress=pct(0.30), message=f"Parsed {filename} ({parsed_doc.total_pages} page(s))")

            # ── Step 3: Build extracted dict for chunker ──────────────────
            text_blocks = []
            tables = []
            for pg in parsed_doc.pages:
                if pg.text.strip():
                    text_blocks.append({"text": pg.text, "page": pg.page_number})
                for table_text in pg.tables:
                    if table_text.strip():
                        tables.append({"text": table_text, "page": pg.page_number})

            # ── Step 3b: Vision pipeline — describe PDF images (Session 7) ──
            image_captions = []
            if ext == ".pdf":
                all_page_images = [
                    (pg.page_number, img_bytes)
                    for pg in parsed_doc.pages
                    for img_bytes in pg.images
                ]
                if all_page_images:
                    _set_job(
                        job_id,
                        progress=pct(0.35),
                        message=f"[vision] Found {len(all_page_images)} image(s) in {filename} — analysing...",
                    )
                    for img_idx, (page_num, img_bytes) in enumerate(all_page_images):
                        try:
                            img = PILImage.open(io.BytesIO(img_bytes))
                            w, h = img.size
                            if w < 100 or h < 100:
                                continue
                            _set_job(
                                job_id,
                                message=f"[vision] Describing image {img_idx + 1}/{len(all_page_images)} (page {page_num})...",
                            )
                            caption = await asyncio.wait_for(
                                vision_service.describe_image_bytes(img_bytes),
                                timeout=60.0,
                            )
                            if caption.strip():
                                image_captions.append({"caption": caption, "page": page_num})
                        except asyncio.TimeoutError:
                            logging.warning(
                                f"Vision timeout — {filename} image {img_idx + 1} page {page_num}"
                            )
                        except Exception as exc:
                            logging.warning(
                                f"Vision error — {filename} image {img_idx + 1} page {page_num}: {exc}"
                            )

            if not text_blocks and not tables and not image_captions:
                _set_job(job_id, progress=pct(1.0), message=f"No content found in {filename} — skipped")
                continue

            extracted = {
                "filename": filename,
                "text_blocks": text_blocks,
                "tables": tables,
                "images": image_captions,  # vision captions from Session 7
            }

            # ── Step 4: Chunk ─────────────────────────────────────────────
            _set_job(job_id, progress=pct(0.40), message=f"Chunking {filename}...")
            chunks = chunker.chunk_document(extracted)

            if not chunks:
                _set_job(job_id, progress=pct(1.0), message=f"No chunks produced for {filename} — skipped")
                continue

            _set_job(job_id, progress=pct(0.50), message=f"Chunked into {len(chunks)} chunk(s)")

            # ── Step 5: Embed ─────────────────────────────────────────────
            _set_job(job_id, progress=pct(0.55), message=f"Embedding {len(chunks)} chunks...")
            chunk_texts = [c.content for c in chunks]
            embeddings = await embedder.embed_chunks(chunk_texts)
            _set_job(job_id, progress=pct(0.85), message=f"Embeddings generated for {filename}")

            # ── Step 6: Store in ChromaDB ─────────────────────────────────
            _set_job(job_id, progress=pct(0.90), message=f"Storing {filename} in vector database...")
            now = datetime.now(timezone.utc).isoformat()
            chroma_chunks = [
                {
                    "embedding": emb,
                    "document": chunk.content,
                    "metadata": {
                        "filename": chunk.filename,
                        "page": chunk.page,
                        "chunk_type": chunk.chunk_type,
                        "timestamp": now,
                    },
                }
                for chunk, emb in zip(chunks, embeddings)
            ]
            chroma_client.add_chunks(chroma_chunks)
            total_chunks += len(chroma_chunks)
            _set_job(job_id, progress=pct(1.0), message=f"Stored {len(chroma_chunks)} chunks from {filename}")

        # ── All files done ────────────────────────────────────────────────
        _jobs[job_id].update({
            "status": "complete",
            "progress": 100,
            "chunk_count": total_chunks,
            "message": f"Done. {total_chunks} chunk(s) indexed across {total_files} file(s).",
        })

    except Exception as e:
        _jobs[job_id].update({
            "status": "error",
            "progress": _jobs[job_id].get("progress", 0),
            "message": str(e),
        })


def _set_job(job_id: str, **kwargs):
    """Helper to update job fields without overwriting unrelated keys."""
    _jobs[job_id].update(kwargs)
