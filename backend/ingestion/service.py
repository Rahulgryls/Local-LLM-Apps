"""
LAKO — Ingestion Service (V3 Direct-RAG Pipeline)

No LLM summarisation. Raw text is preserved exactly.
Vision model is called only for IMAGE_ONLY pages and image regions on MIXED pages.

Pipeline per document:
  Stage 1 — SHA-256 hash check (dedup)
  Stage 2 — File-type router
  Stage 3 — PDF pipeline with per-page classifier
              TEXT_RICH  → sentence-boundary chunking (no LLM)
              TABLE      → pdfplumber flatten (no LLM)
              IMAGE_ONLY → render PNG → vision model
              MIXED      → text spans direct + vision per image region
  Stage 4 — smart_chunk() — sentence boundaries, 400-token max, 50-token overlap
  Stage 5 — embed (nomic-embed-text) → Qdrant lako_documents + SQLite document_chunks
  Stage 6 — designed to be wrapped in FastAPI BackgroundTasks (see routers/)

Public API:
  ingest_file(file_path, filename, source_type, progress_callback) → doc_id
  smart_chunk(text, page, metadata, max_tokens, overlap)            → [(text, meta)]
"""

import base64
import hashlib
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import fitz  # PyMuPDF
import pdfplumber
import structlog

from config import get_config
from db.chunk_store import (
    create_doc,
    delete_doc_and_chunks,
    find_by_filename,
    find_by_hash,
    get_chunk_qdrant_ids,
    get_doc,
    init_chunk_db,
    insert_chunk,
    update_doc_status,
)
from services.ollama_client import ollama_client

logger = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

STORAGE_DOCS_DIR  = Path(__file__).parent.parent.parent / "storage" / "documents"
COLLECTION_NAME   = "lako_documents"
VECTOR_SIZE       = 768          # nomic-embed-text
TEXT_RICH_TOKENS  = 50           # >= 50 tokens → TEXT_RICH
MIXED_MIN_TOKENS  = 20           # >= 20 tokens + images → MIXED

VISION_PROMPT = (
    "Describe all text, data, labels, values, flows and relationships visible "
    "in this diagram or image. Be precise and complete. Include all numbers."
)

ROTATED_TABLE_PROMPT = (
    "This page contains rotated content (likely a wide table "
    "rotated 90 degrees). Read it in its natural orientation. "
    "Extract ALL text, preserving the table structure as a markdown "
    "table. Include every row, every column header, and every data "
    "cell exactly as printed. Do not summarise. Do not skip rows."
)

ProgressCallback = Optional[Callable[[str, str, int, int], None]]
# fn(doc_id, phase, current, total)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as fh:
        for block in iter(lambda: fh.read(65_536), b""):
            h.update(block)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _token_count(text: str) -> int:
    return len(text.split())


# ── Stage 4: Smart Chunking ────────────────────────────────────────────────────

def smart_chunk(
    text: str,
    page: int,
    metadata: dict,
    max_tokens: int = 400,
    overlap: int = 50,
) -> list[tuple[str, dict]]:
    """
    Split *text* on sentence boundaries with *overlap* token carry-over.

    Rules:
    - If block_type == "table": return text as a single chunk (never split tables).
    - Split on sentence boundaries: ". ", "? ", "! ", "\\n\\n"
    - Each chunk ≤ max_tokens (measured in whitespace-split words).
    - The last *overlap* tokens of each chunk prepend the next one.

    Returns a list of (chunk_text, metadata_copy) tuples.
    The metadata dict is shallow-copied per chunk; do not mutate the originals.
    """
    if not text or not text.strip():
        return []

    # Tables are always kept whole
    if metadata.get("block_type") == "table":
        return [(text.strip(), dict(metadata))]

    # Split on sentence-ending punctuation followed by whitespace, or blank line
    sentences = re.split(r"(?<=[.?!])\s+|\n\n+", text)
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks: list[tuple[str, dict]] = []
    current_tokens: list[str] = []

    for sentence in sentences:
        sent_tokens = sentence.split()

        # Would adding this sentence exceed max_tokens?
        if current_tokens and len(current_tokens) + len(sent_tokens) > max_tokens:
            # Flush current chunk
            chunks.append((" ".join(current_tokens), dict(metadata)))
            # Carry overlap from the end of the flushed chunk
            current_tokens = current_tokens[-overlap:] if overlap else []

        current_tokens.extend(sent_tokens)

    # Flush remainder
    if current_tokens:
        chunks.append((" ".join(current_tokens), dict(metadata)))

    return chunks


# ── Stage 3: PDF pipeline internals ────────────────────────────────────────────

def _detect_page_rotation(page: fitz.Page) -> str | None:
    """
    Returns 'rotated' if a meaningful share of text on this page is not
    horizontal, based on PyMuPDF span direction metadata. Returns None
    for normal pages or pages with too little text to judge.

    This is deterministic — no heuristics, no language assumptions.

    Args:
        page: A fitz.Page object to inspect.

    Returns:
        'rotated' if >30% of text characters have non-horizontal direction,
        None otherwise (including when total text is too sparse to judge).
    """
    try:
        blocks = page.get_text("dict").get("blocks", [])
    except Exception:
        return None

    horizontal_chars = 0
    rotated_chars = 0
    for block in blocks:
        if block.get("type") != 0:  # 0 = text block, 1 = image
            continue
        for line in block.get("lines", []):
            d = tuple(line.get("dir", (1.0, 0.0)))
            line_text_len = sum(
                len(span.get("text", "")) for span in line.get("spans", [])
            )
            if line_text_len < 3:
                continue
            if d == (1.0, 0.0):
                horizontal_chars += line_text_len
            else:
                rotated_chars += line_text_len

    total = horizontal_chars + rotated_chars
    if total < 50:
        return None
    if rotated_chars / total > 0.30:
        return "rotated"
    return None


def _classify_page(token_count: int, has_images: bool, raw_text: str) -> str:
    """
    Return one of: TEXT_RICH | TABLE | IMAGE_ONLY | MIXED

    TABLE is checked first — a page with table-like structure is always TABLE
    regardless of token count or image presence.
    Remaining classes are decided by token count and image presence.
    """
    # Table check first — applies at any token count
    if _looks_like_table(raw_text):
        return "TABLE"
    if token_count >= TEXT_RICH_TOKENS:
        return "TEXT_RICH"
    if token_count < MIXED_MIN_TOKENS:
        return "IMAGE_ONLY" if has_images else "TEXT_RICH"
    return "MIXED" if has_images else "TEXT_RICH"


_RE_PIPE = re.compile(r".*\|.*\|")
_RE_TABS = re.compile(r"\t.*\t")
_RE_COLS = re.compile(r"(?:[ ]{2,}\S{1,40}){2,}")


def _looks_like_table(text: str) -> bool:
    for line in text.splitlines():
        if _RE_PIPE.match(line):
            return True
        if _RE_TABS.search(line):
            return True
        if _RE_COLS.search(line):
            return True
    return False


def _extract_span_info(fitz_page: fitz.Page) -> dict:
    """Return first_bbox, avg_font_size, is_bold from span data."""
    try:
        raw = fitz_page.get_text("dict")
    except Exception:
        return {"first_bbox": [0, 0, 0, 0], "avg_font_size": 0.0, "is_bold": False}

    sizes: list[float] = []
    bold = False
    first_bbox: list[float] = [0, 0, 0, 0]
    found_first = False

    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                size = float(span.get("size", 0))
                if size:
                    sizes.append(size)
                flags = span.get("flags", 0)
                if flags & 2**4:   # bold flag in PyMuPDF
                    bold = True
                if not found_first and span.get("bbox"):
                    first_bbox = list(span["bbox"])
                    found_first = True

    avg_size = sum(sizes) / len(sizes) if sizes else 0.0
    return {"first_bbox": first_bbox, "avg_font_size": avg_size, "is_bold": bold}


def _pdfplumber_table_text(file_path: str, page_idx: int) -> Optional[str]:
    """
    Extract table(s) from a page with pdfplumber and flatten to:
      "Col1: Val | Col2: Val | Col3: Val\\n"
    Returns None if no table found or on error.
    """
    try:
        with pdfplumber.open(file_path) as pdf:
            if page_idx >= len(pdf.pages):
                return None
            tables = pdf.pages[page_idx].extract_tables()
            if not tables:
                return None

            rows: list[str] = []
            for table in tables:
                if not table:
                    continue
                headers = [str(c or "").strip() for c in table[0]]
                for row in table[1:]:
                    cells = [str(c or "").strip() for c in row]
                    pairs = [
                        f"{h}: {v}" if h else v
                        for h, v in zip(headers, cells)
                        if v
                    ]
                    if pairs:
                        rows.append(" | ".join(pairs))

            return "\n".join(rows) if rows else None
    except Exception as exc:
        logger.warning("pdfplumber_failed", page_idx=page_idx, error=str(exc))
        return None


async def _render_page_png(fitz_page: fitz.Page, dpi: int = 150) -> bytes:
    """Render a fitz page to PNG bytes at *dpi* resolution."""
    scale = dpi / 72
    mat = fitz.Matrix(scale, scale)
    pix = fitz_page.get_pixmap(matrix=mat, alpha=False)
    return pix.tobytes("png")


async def _vision_call(
    img_bytes: bytes,
    doc_id: str,
    page_num: int,
    prompt: str = VISION_PROMPT,
) -> Optional[str]:
    """Base64-encode *img_bytes* and call vision model. Returns description or None.

    Args:
        img_bytes: Raw PNG or JPEG image bytes.
        doc_id:    Document ID for logging.
        page_num:  Page number for logging.
        prompt:    Vision prompt to send alongside the image. Defaults to VISION_PROMPT.
    """
    if len(img_bytes) < 500:
        return None
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    logger.info("vision_llm_called", page=page_num, doc_id=doc_id)
    try:
        return await ollama_client.describe_image(img_b64, prompt)
    except Exception as exc:
        logger.warning("vision_llm_error", page=page_num, doc_id=doc_id, error=str(exc))
        return None


async def _process_pdf_page(
    fitz_doc: fitz.Document,
    fitz_page: fitz.Page,
    page_num: int,
    doc_id: str,
    filename: str,
    file_path: str,
) -> list[tuple[str, dict]]:
    """
    Classify and process one PDF page.
    Returns list of (chunk_text, metadata) tuples.
    Errors on a single page are logged and return [].
    """
    try:
        raw_text    = fitz_page.get_text("text").strip()
        token_count = _token_count(raw_text)
        images      = fitz_page.get_images(full=True)
        has_images  = len(images) > 0
        span_info   = _extract_span_info(fitz_page)

        # Rotation check runs FIRST — a rotated page with table-like layout
        # must be routed to vision regardless of other classifier signals.
        if _detect_page_rotation(fitz_page) == "rotated":
            page_class = "ROTATED"
        else:
            page_class = _classify_page(token_count, has_images, raw_text)

        base_meta = {
            "doc_id":      doc_id,
            "filename":    filename,
            "page":        page_num,
            "bbox":        span_info["first_bbox"],
            "font_size":   span_info["avg_font_size"],
            "is_bold":     span_info["is_bold"],
            "ingested_at": _now(),
            "source_type": "pdf",
        }

        # ── ROTATED ──────────────────────────────────────────────────────────
        if page_class == "ROTATED":
            logger.info(
                "rotation_detected",
                page=page_num, doc_id=doc_id, filename=filename,
            )
            img_bytes = await _render_page_png(fitz_page, dpi=200)
            description = await _vision_call(
                img_bytes, doc_id, page_num, prompt=ROTATED_TABLE_PROMPT
            )
            if description and description.strip():
                meta = {
                    **base_meta,
                    "block_type": "table",
                    "extraction_quality": "vision_extracted",
                    "rotation_detected": True,
                }
                return smart_chunk(description.strip(), page_num, meta)
            return []

        # ── TEXT_RICH ────────────────────────────────────────────────────────
        if page_class == "TEXT_RICH":
            # Re-extract with sort=True for reading-order correctness on
            # multi-column layouts.  Falls back to the already-extracted
            # raw_text only if sort= is not supported (e.g. test mocks).
            try:
                sorted_text = fitz_page.get_text("text", sort=True).strip()
            except TypeError:
                sorted_text = raw_text
            meta = {**base_meta, "block_type": "text", "extraction_quality": "clean"}
            return smart_chunk(sorted_text, page_num, meta)

        # ── TABLE ────────────────────────────────────────────────────────────
        if page_class == "TABLE":
            table_text = _pdfplumber_table_text(file_path, page_num - 1)
            if table_text:
                meta = {**base_meta, "block_type": "table"}
                return smart_chunk(table_text, page_num, meta)
            # Fallback: treat as text
            meta = {**base_meta, "block_type": "text"}
            return smart_chunk(raw_text, page_num, meta)

        # ── IMAGE_ONLY ───────────────────────────────────────────────────────
        if page_class == "IMAGE_ONLY":
            img_bytes   = await _render_page_png(fitz_page)
            description = await _vision_call(img_bytes, doc_id, page_num)
            if description and description.strip():
                meta = {**base_meta, "block_type": "image_description"}
                return [(description.strip(), meta)]
            return []

        # ── MIXED ────────────────────────────────────────────────────────────
        if page_class == "MIXED":
            chunks: list[tuple[str, dict]] = []

            # Text spans extracted directly (no LLM)
            if token_count >= MIXED_MIN_TOKENS:
                meta = {**base_meta, "block_type": "text"}
                chunks.extend(smart_chunk(raw_text, page_num, meta))

            # Vision call per image region
            for img_info in images:
                xref = img_info[0]
                try:
                    # Find image placement rect on this page
                    img_rects = [
                        r.rect for r in fitz_page.get_image_rects(xref)
                    ]
                    for img_rect in img_rects:
                        if img_rect.width < 50 or img_rect.height < 50:
                            continue   # skip tiny decorative images
                        scale = 150 / 72
                        mat = fitz.Matrix(scale, scale)
                        clip_pix = fitz_page.get_pixmap(
                            matrix=mat, clip=img_rect, alpha=False
                        )
                        clip_bytes = clip_pix.tobytes("png")
                        desc = await _vision_call(clip_bytes, doc_id, page_num)
                        if desc and desc.strip():
                            img_meta = {
                                **base_meta,
                                "block_type": "image_description",
                                "bbox": list(img_rect),
                            }
                            chunks.append((desc.strip(), img_meta))
                except Exception as exc:
                    logger.warning(
                        "mixed_image_region_failed",
                        page=page_num, doc_id=doc_id, error=str(exc),
                    )

            return chunks

    except Exception as exc:
        logger.error(
            "page_processing_failed",
            page=page_num, doc_id=doc_id, error=str(exc),
        )
        return []

    return []


async def _pdf_pipeline(
    file_path: str,
    doc_id: str,
    filename: str,
    progress_callback: ProgressCallback = None,
) -> list[tuple[str, dict]]:
    """
    Full PDF pipeline: open → classify each page → chunk.
    Returns all (text, metadata) tuples across all pages.
    """
    try:
        fitz_doc = fitz.open(file_path)
    except Exception as exc:
        logger.error("pdf_open_failed", filename=filename, error=str(exc))
        raise

    if fitz_doc.is_encrypted:
        fitz_doc.close()
        raise ValueError(f"PDF is encrypted: {filename}")

    total_pages = len(fitz_doc)
    all_chunks: list[tuple[str, dict]] = []

    logger.info("pdf_pipeline_start", filename=filename, pages=total_pages, doc_id=doc_id)

    for idx in range(total_pages):
        fitz_page = fitz_doc[idx]
        page_num  = idx + 1

        page_chunks = await _process_pdf_page(
            fitz_doc, fitz_page, page_num, doc_id, filename, file_path
        )
        all_chunks.extend(page_chunks)

        if progress_callback:
            progress_callback(doc_id, "parsing", page_num, total_pages)

    fitz_doc.close()
    logger.info(
        "pdf_pipeline_complete",
        filename=filename,
        doc_id=doc_id,
        pages=total_pages,
        chunks=len(all_chunks),
    )
    return all_chunks


# ── Stage 5: Embed and Store ───────────────────────────────────────────────────

async def _ensure_collection() -> None:
    """Create lako_documents Qdrant collection if it doesn't exist."""
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


async def _embed_and_store(
    chunks: list[tuple[str, dict]],
    doc_id: str,
    progress_callback: ProgressCallback = None,
) -> int:
    """
    Embed each chunk with nomic-embed-text, upsert to Qdrant, record in SQLite.
    Returns total chunks stored.
    """
    from ingestion.embedder_v2 import _get_qdrant
    from qdrant_client.http.models import PointStruct

    client = await _get_qdrant()
    total  = len(chunks)
    stored = 0

    for i, (text, meta) in enumerate(chunks):
        if not text or not text.strip():
            continue
        try:
            vector    = await ollama_client.embed(text)
            qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_id}:{i}:{text[:80]}"))

            point = PointStruct(
                id      = qdrant_id,
                vector  = vector,
                payload = {
                    **meta,
                    "text": text,
                    "extraction_quality": meta.get("extraction_quality", "clean"),
                    "rotation_detected":  meta.get("rotation_detected", False),
                },
            )
            await client.upsert(collection_name=COLLECTION_NAME, points=[point])

            chunk_id = str(uuid.uuid4())
            await insert_chunk(
                chunk_id    = chunk_id,
                doc_id      = doc_id,
                page        = meta.get("page", 0),
                block_type  = meta.get("block_type", "text"),
                chunk_index = i,
                qdrant_id   = qdrant_id,
            )
            stored += 1

            if progress_callback:
                progress_callback(doc_id, "embedding", i + 1, total)

        except Exception as exc:
            logger.error(
                "embed_chunk_failed",
                doc_id=doc_id,
                chunk_index=i,
                error=str(exc),
            )
            # Continue — one bad chunk should not abort the document

    return stored


# ── Stage 1-2: Hash check + file router ───────────────────────────────────────

async def ingest_file(
    file_path: str,
    filename: str,
    source_type: str,
    progress_callback: ProgressCallback = None,
) -> dict:
    """
    Run the full V3 ingestion pipeline for a single file.

    Args:
        file_path:    Absolute path to the file on disk.
        filename:     Original user-facing filename (e.g. "report.pdf").
        source_type:  One of: pdf | docx | pptx | xlsx | html
        progress_callback: fn(doc_id, phase, current, total) — optional.

    Returns:
        {
          "doc_id":  str,
          "status":  "duplicate" | "indexed" | "failed",
          "chunks":  int   (0 for duplicate/failed),
          "pages":   int
        }
    """
    await init_chunk_db()

    # ── Stage 1: Hash dedup ───────────────────────────────────────────────────
    file_hash = _sha256(file_path)
    existing  = await find_by_hash(file_hash)
    if existing and existing["status"] in ("indexed", "processing"):
        logger.info("duplicate_skipped", filename=filename, doc_id=existing["id"])
        return {
            "doc_id": existing["id"],
            "status": "duplicate",
            "chunks": existing.get("chunk_count", 0),
            "pages":  existing.get("page_count", 0),
        }

    # ── Stage 1b: Detect same filename, different content ────────────────────
    # Store reference now but DO NOT delete yet — old doc stays live until
    # the new one is fully indexed (ingest-first, swap-after).
    prev = await find_by_filename(filename)

    # ── Create document row ───────────────────────────────────────────────────
    doc_id = str(uuid.uuid4())
    await create_doc(doc_id, filename, file_hash, source_type)
    log = logger.bind(doc_id=doc_id, filename=filename, source_type=source_type)
    log.info("ingestion_started", replacing=prev["id"] if prev else None)

    try:
        await update_doc_status(doc_id, "parsing")

        # ── Stage 2+3: Route to correct pipeline ─────────────────────────────
        chunks = await _route(file_path, filename, source_type, doc_id, progress_callback)

        page_count = _count_pages(chunks)
        await update_doc_status(doc_id, "embedding", page_count=page_count)

        # ── Stage 5c: Persist original file to storage/documents/{doc_id}/ ──
        ext       = Path(filename).suffix.lower()
        dest_dir  = STORAGE_DOCS_DIR / doc_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"original{ext}"
        shutil.copy2(file_path, dest_path)
        log.info("file_stored", path=str(dest_path))

        # ── Stage 5a/b: Embed chunks → Qdrant, record → SQLite ───────────────
        await _ensure_collection()
        chunk_count = await _embed_and_store(chunks, doc_id, progress_callback)

        # Verify new doc is healthy before touching the old one
        if chunk_count == 0:
            raise RuntimeError(
                f"New ingestion produced 0 chunks for {filename!r} — aborting replace."
            )

        # ── Stage 5d: Post-ingest quality probe ──────────────────────────────
        from services.quality_probe import probe_ingest_quality
        try:
            quality = await probe_ingest_quality(doc_id, filename)
        except Exception as exc:
            log.warning("quality_probe_failed", error=str(exc))
            quality = "unknown"

        if quality == "suspect":
            log.warning(
                "ingest_quality_suspect",
                doc_id=doc_id,
                filename=filename,
            )

        await update_doc_status(
            doc_id, "indexed",
            chunk_count=chunk_count,
            page_count=page_count,
            ingest_quality=quality,
        )

        # ── Stage 6: Now safe to evict the old doc ────────────────────────────
        # New doc is fully indexed and verified — remove old version atomically.
        if prev:
            old_id = prev["id"]
            log.info("evicting_old_doc", old_doc_id=old_id, filename=filename)
            try:
                from ingestion.embedder_v2 import _get_qdrant
                from qdrant_client.http.models import Filter, FieldCondition, MatchValue

                qdrant_client_inst = await _get_qdrant()
                await qdrant_client_inst.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=Filter(
                        must=[FieldCondition(key="doc_id", match=MatchValue(value=old_id))]
                    ),
                )
                log.info("old_qdrant_vectors_deleted", old_doc_id=old_id)
            except Exception as exc:
                log.warning("old_qdrant_delete_failed", old_doc_id=old_id, error=str(exc))

            await delete_doc_and_chunks(old_id)

            old_dir = STORAGE_DOCS_DIR / old_id
            if old_dir.exists():
                shutil.rmtree(old_dir, ignore_errors=True)
                log.info("old_doc_dir_removed", old_doc_id=old_id)

        final_status = "replaced" if prev else "indexed"
        log.info("ingestion_complete", chunks=chunk_count, pages=page_count, status=final_status)

        return {"doc_id": doc_id, "status": final_status, "chunks": chunk_count, "pages": page_count}

    except Exception as exc:
        await update_doc_status(doc_id, "failed", error_message=str(exc))
        log.error("ingestion_failed", error=str(exc))
        raise


def _count_pages(chunks: list[tuple[str, dict]]) -> int:
    """Infer page count from max page number seen in chunk metadata."""
    pages = {meta.get("page", 0) for _, meta in chunks}
    return max(pages, default=0)


async def _route(
    file_path: str,
    filename: str,
    source_type: str,
    doc_id: str,
    progress_callback: ProgressCallback,
) -> list[tuple[str, dict]]:
    """Dispatch to the correct file-type pipeline."""
    if source_type == "pdf":
        return await _pdf_pipeline(file_path, doc_id, filename, progress_callback)

    if source_type == "docx":
        from ingestion.docx_pipeline import docx_pipeline
        return await docx_pipeline(file_path, doc_id, filename, progress_callback)

    if source_type == "pptx":
        from ingestion.pptx_pipeline import pptx_pipeline
        return await pptx_pipeline(file_path, doc_id, filename, progress_callback)

    if source_type == "xlsx":
        from ingestion.xlsx_pipeline import xlsx_pipeline
        return await xlsx_pipeline(file_path, doc_id, filename, progress_callback)

    if source_type == "html":
        from ingestion.docx_pipeline import html_pipeline
        return await html_pipeline(file_path, doc_id, filename, progress_callback)

    raise ValueError(f"Unsupported source_type: {source_type!r}")


def source_type_from_filename(filename: str) -> str:
    """Map file extension to source_type string."""
    ext = Path(filename).suffix.lower()
    mapping = {
        ".pdf":  "pdf",
        ".docx": "docx",
        ".pptx": "pptx",
        ".xlsx": "xlsx",
        ".html": "html",
        ".htm":  "html",
    }
    if ext not in mapping:
        raise ValueError(f"Unsupported extension {ext!r}. Supported: {sorted(mapping)}")
    return mapping[ext]
