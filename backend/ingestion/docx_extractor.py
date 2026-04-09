"""
LAKO V2 — DOCX Structure Extractor (Pass 1)

Extracts Word document content into virtual "pages" for the V2 smart-index
pipeline, matching the interface and quality of pdf_extractor.py.

Since DOCX files have no physical pages, content is split into virtual pages
using heading boundaries (H1–H4). Sections longer than _MAX_PAGE_CHARS are
further split at paragraph boundaries so the summariser never receives a
block larger than its input limit.

Feature parity with pdf_extractor:
  • Tables flattened inline  (Header: value | Header: value format)
  • Embedded images described via vision model (same as scanned-page OCR)
  • Headers stored per virtual page (heading text of that section)
  • has_tables flag set per virtual page
  • Short sections (<50 chars after strip) left as-is — summariser marks
    them [Empty page] just like a blank PDF page

Each virtual page is written to SQLite via insert_page() and returns the
total virtual page count so the orchestrator can write total_pages.
"""

import base64
import logging
from pathlib import Path
from typing import Callable, Optional

import structlog
from docx import Document
from docx.oxml.ns import qn

from db.document_store import insert_page, update_document_status

logger = structlog.get_logger(__name__)

# Soft cap — sections larger than this are split at paragraph boundaries
# Matches summarizer._MAX_CHARS so no page needs to be truncated downstream
_MAX_PAGE_CHARS = 5_000

_VISION_PROMPT = (
    "Transcribe all text visible in this image exactly as written. "
    "If it is a diagram or chart, describe all labels, values, flows and "
    "relationships. Include every number. Output only the content — no commentary."
)

# Heading style names that trigger a new virtual page
_HEADING_PREFIXES = ("heading 1", "heading 2", "heading 3", "heading 4")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_heading(para) -> bool:
    """Return True if *para* uses any of the standard Heading styles."""
    style_name = (para.style.name or "").lower()
    return any(style_name.startswith(h) for h in _HEADING_PREFIXES)


def _flatten_table(table) -> str:
    """
    Flatten a python-docx Table into key: value pipe-separated rows.
    The first row is treated as column headers.
    """
    rows = []
    cells_by_row = [
        [cell.text.strip() for cell in row.cells]
        for row in table.rows
    ]
    if not cells_by_row:
        return ""

    header_row = cells_by_row[0]
    for row in cells_by_row[1:]:
        pairs = [
            f"{h}: {v}" if h else v
            for h, v in zip(header_row, row)
            if v
        ]
        if pairs:
            rows.append(" | ".join(pairs))

    # If the table has no data rows (header only), return the header row as text
    if not rows:
        return " | ".join(c for c in header_row if c)

    return "\n".join(rows)


async def _vision_describe(img_bytes: bytes) -> Optional[str]:
    """Describe an embedded image using the vision model. Returns None on failure."""
    if len(img_bytes) < 500:   # ignore tiny decorative images
        return None
    from services.ollama_client import ollama_client
    try:
        img_b64 = base64.b64encode(img_bytes).decode()
        result  = await ollama_client.describe_image(img_b64, _VISION_PROMPT)
        return result.strip() if result and result.strip() else None
    except Exception as exc:
        logger.warning("docx_vision_failed", error=str(exc))
        return None


def _split_lines_to_pages(
    lines: list[str],
    headers: list[str],
    has_tables: bool,
    max_chars: int,
) -> list[tuple[str, list[str], bool]]:
    """
    If the accumulated lines exceed max_chars, split them into multiple
    virtual pages at line boundaries. All resulting pages share the same
    headers and has_tables flag (they are part of the same heading section).

    Returns list of (raw_text, headers, has_tables) tuples.
    """
    pages: list[tuple[str, list[str], bool]] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > max_chars and current:
            pages.append(("\n".join(current).strip(), headers, has_tables))
            current = []
            current_len = 0
        current.append(line)
        current_len += line_len

    if current:
        pages.append(("\n".join(current).strip(), headers, has_tables))

    return pages


# ── Main extractor ─────────────────────────────────────────────────────────────

async def extract_docx(
    file_path: str,
    doc_id: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> int:
    """
    Extract all content from a DOCX file into virtual pages in the SQLite
    document store.

    Args:
        file_path:         Absolute path to the .docx file.
        doc_id:            UUID assigned to this document.
        progress_callback: Optional fn(pages_done, total_pages).
                           Called with a placeholder total_pages=0 until
                           extraction completes; final call uses real count.

    Returns:
        Total number of virtual pages written.
    """
    path = Path(file_path)
    logger.info("docx_extraction_start", filename=path.name, doc_id=doc_id)

    try:
        doc = Document(str(path))
    except Exception as exc:
        logger.error("docx_open_failed", filename=path.name, error=str(exc))
        await update_document_status(doc_id, "failed")
        raise

    # ── Walk body elements ─────────────────────────────────────────────────────
    # We iterate doc.element.body children to see paragraphs AND tables in
    # document order (python-docx's doc.paragraphs skips inline tables).

    # Accumulator for the current virtual page
    current_lines:  list[str]  = []
    current_headers: list[str] = []
    current_has_tables = False

    # Collect completed (raw_text, headers, has_tables) sections
    sections: list[tuple[str, list[str], bool]] = []

    def _flush() -> None:
        """Flush current accumulator to sections, splitting if over limit."""
        if not current_lines:
            return
        split = _split_lines_to_pages(
            current_lines, list(current_headers), current_has_tables, _MAX_PAGE_CHARS
        )
        sections.extend(split)

    body_children = list(doc.element.body)
    total_elements = len(body_children)

    for i, child in enumerate(body_children):
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "p":
            # Map element back to a python-docx Paragraph for style access
            # (We can build a Paragraph wrapper directly from the XML element)
            from docx.text.paragraph import Paragraph as _Para
            para = _Para(child, doc)

            para_text = para.text.strip()
            is_h      = _is_heading(para)

            if is_h:
                # Heading → flush current section, start a new one
                _flush()
                current_lines       = [para_text] if para_text else []
                current_headers     = [para_text] if para_text else []
                current_has_tables  = False
            else:
                if para_text:
                    current_lines.append(para_text)

        elif tag == "tbl":
            # Find the matching python-docx Table object by XML element identity
            table_text = ""
            for tbl in doc.tables:
                if tbl._tbl is child:
                    table_text = _flatten_table(tbl)
                    break

            if table_text:
                # Flush any pending prose before the table so each table gets
                # its own context block (better for summarisation)
                _flush()
                current_lines      = [table_text]
                current_headers    = list(current_headers)  # inherit section header
                current_has_tables = True
                _flush()
                current_lines      = []
                current_has_tables = False

        # Progress tick — we don't know total_pages yet, use 0 as sentinel
        if progress_callback and total_elements:
            progress_callback(i + 1, 0)

    # Flush the last accumulated section
    _flush()

    # ── Embedded images (vision OCR) ───────────────────────────────────────────
    # Extract all image relationships from the document part and describe them
    image_sections: list[tuple[str, list[str], bool]] = []
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            try:
                img_bytes = rel.target_part.blob
                desc      = await _vision_describe(img_bytes)
                if desc:
                    image_sections.append((f"[Image]\n{desc}", [], False))
            except Exception as exc:
                logger.warning("docx_image_extraction_failed", error=str(exc))

    all_sections = sections + image_sections

    # ── Write to SQLite ────────────────────────────────────────────────────────
    total_pages = len(all_sections)
    for page_num, (raw_text, headers, has_tables) in enumerate(all_sections, start=1):
        char_count = len(raw_text)
        await insert_page(
            doc_id     = doc_id,
            page_num   = page_num,
            raw_text   = raw_text,
            headers    = headers,
            has_tables = has_tables,
            char_count = char_count,
        )
        if progress_callback:
            progress_callback(page_num, total_pages)

    logger.info(
        "docx_extraction_complete",
        filename=path.name,
        doc_id=doc_id,
        virtual_pages=total_pages,
        image_pages=len(image_sections),
    )
    return total_pages
