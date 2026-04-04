"""
LAKO V2 — PDF Structure Extractor (Pass 1)

Uses PyMuPDF (fitz) for text + header detection.
Uses pdfplumber as a targeted secondary pass — only on pages where a
lightweight heuristic (applied to the PyMuPDF text) signals a likely table.

Heuristic triggers pdfplumber when ANY of these are true:
  • 2+ pipe characters  (|)  on a single line
  • 2+ consecutive tab  characters on a line
  • 3+ short tokens separated by 2+ spaces on the same line
    (column-like layout with no tabs or pipes)

For a typical 200-page bank document most pages are plain prose and
pdfplumber is never called.  Only pages with table-like patterns pay
the ~1-3 s pdfplumber cost.
"""

import logging
import re
from pathlib import Path
from typing import Callable, Optional

import fitz  # PyMuPDF
import pdfplumber

from db.document_store import insert_page, update_document_status

_OCR_PROMPT = (
    "Transcribe all text visible on this document page exactly as written. "
    "Preserve headings, bullet points, tables, and numbers. "
    "Output only the transcribed text — no commentary."
)

logger = logging.getLogger(__name__)

# ── Table-signal heuristic ─────────────────────────────────────────────────────

# Matches a line with 2+ pipe chars
_RE_PIPE = re.compile(r".*\|.*\|")

# Matches a line with 2+ consecutive tab chars
_RE_TABS = re.compile(r"\t.*\t")

# Matches a line that has 3+ whitespace-separated short tokens (≤40 chars each)
# separated by 2+ spaces — typical of space-aligned table columns
_RE_COLS = re.compile(r"(?:[ ]{2,}\S{1,40}){2,}")


def _looks_like_table_page(text: str) -> bool:
    """
    Return True if *text* (raw PyMuPDF page text) contains table-like patterns.
    Runs in microseconds — pure Python regex over the page string.
    """
    for line in text.splitlines():
        if _RE_PIPE.match(line):
            return True
        if _RE_TABS.search(line):
            return True
        if _RE_COLS.search(line):
            return True
    return False


# ── Header detection ───────────────────────────────────────────────────────────

def _extract_headers(fitz_page: fitz.Page) -> list[str]:
    """
    Detect header text on a page by comparing each span's font size
    against the page-average font size.  Spans more than 1.5 pt above
    average are considered headers (capped at 10 per page).
    """
    try:
        raw = fitz_page.get_text("dict")
    except Exception as exc:
        logger.warning("get_text('dict') failed: %s", exc)
        return []

    spans_data: list[tuple[str, float]] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:          # skip image blocks
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                size = float(span.get("size", 0))
                if text and len(text) > 2:
                    spans_data.append((text, size))

    if not spans_data:
        return []

    avg_size = sum(s for _, s in spans_data) / len(spans_data)

    headers: list[str] = []
    seen: set[str] = set()
    for text, size in spans_data:
        if size > avg_size + 1.5 and text not in seen:
            headers.append(text)
            seen.add(text)
            if len(headers) >= 10:
                break

    return headers


# ── pdfplumber targeted table extraction ───────────────────────────────────────

def _extract_tables_pdfplumber(file_path: str, page_idx: int) -> bool:
    """
    Open only *page_idx* (0-based) with pdfplumber and return True if it
    contains at least one table.  Called only when the heuristic fires.
    """
    try:
        with pdfplumber.open(file_path) as pdf:
            if page_idx >= len(pdf.pages):
                return False
            tables = pdf.pages[page_idx].extract_tables()
            return bool(tables)
    except Exception as exc:
        logger.warning("pdfplumber failed on page %d: %s", page_idx + 1, exc)
        return False


# ── Main extractor ─────────────────────────────────────────────────────────────

async def extract_pdf(
    file_path: str,
    doc_id: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> int:
    """
    Extract all pages from *file_path* into the SQLite document store.

    Args:
        file_path: Absolute path to the PDF file.
        doc_id:    UUID assigned to this document in the documents table.
        progress_callback: Optional fn(pages_done, total_pages).

    Returns:
        Total number of pages extracted.

    Raises:
        ValueError: If the PDF is encrypted.
        Exception:  Propagates any fitz open / read error.
    """
    path = Path(file_path)

    try:
        fitz_doc = fitz.open(str(path))
    except Exception as exc:
        logger.error("Cannot open PDF %s: %s", path.name, exc)
        raise

    if fitz_doc.is_encrypted:
        fitz_doc.close()
        await update_document_status(doc_id, "failed")
        raise ValueError(f"PDF is encrypted and cannot be read: {path.name}")

    total_pages  = len(fitz_doc)
    plumber_hits = 0

    logger.info("Extracting PDF %s — %d pages", path.name, total_pages)

    pages_done = 0
    for idx in range(total_pages):
        fitz_page = fitz_doc[idx]
        page_num  = idx + 1          # store 1-indexed

        raw_text   = fitz_page.get_text("text").strip()
        char_count = len(raw_text)

        # Scanned page — render to PNG and OCR via vision model
        if char_count < 50:
            logger.debug("Page %d of %s is scanned — running OCR", page_num, path.name)
            try:
                from services.vision_service import vision_service
                mat      = fitz.Matrix(2.0, 2.0)   # 2× zoom → ~144 dpi
                pix      = fitz_page.get_pixmap(matrix=mat, alpha=False)
                img_bytes = pix.tobytes("png")
                ocr_text  = await vision_service.describe_image_bytes(img_bytes, _OCR_PROMPT)
                if ocr_text and len(ocr_text.strip()) > 20:
                    raw_text   = ocr_text
                    char_count = len(raw_text)
            except Exception as exc:
                logger.warning("OCR failed for page %d: %s", page_num, exc)

        headers = _extract_headers(fitz_page)

        # Only call pdfplumber when the cheap heuristic fires
        if _looks_like_table_page(raw_text):
            has_tables = _extract_tables_pdfplumber(str(path), idx)
            if has_tables:
                plumber_hits += 1
        else:
            has_tables = False

        await insert_page(
            doc_id=doc_id,
            page_num=page_num,
            raw_text=raw_text,
            headers=headers,
            has_tables=has_tables,
            char_count=char_count,
        )

        pages_done += 1
        if progress_callback:
            progress_callback(pages_done, total_pages)

    fitz_doc.close()
    logger.info(
        "PDF extraction complete: %s — %d pages, %d table pages (pdfplumber called on heuristic matches)",
        path.name, pages_done, plumber_hits,
    )
    return pages_done
