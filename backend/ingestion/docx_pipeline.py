"""
LAKO — DOCX Pipeline (V3 Direct-RAG)

Extracts text from Word documents using python-docx.
Applies the same TEXT_RICH / TABLE / IMAGE classifier logic as the PDF pipeline.
Images embedded in DOCX are extracted and passed through the vision model.

Also exports html_pipeline() for Confluence HTML exports.
"""

import base64
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import structlog
from docx import Document
from docx.oxml.ns import qn

from services.ollama_client import ollama_client

logger = structlog.get_logger(__name__)

VISION_PROMPT = (
    "Describe all text, data, labels, values, flows and relationships visible "
    "in this diagram or image. Be precise and complete. Include all numbers."
)

ProgressCallback = Optional[Callable[[str, str, int, int], None]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _token_count(text: str) -> int:
    return len(text.split())


# ── Table extraction ───────────────────────────────────────────────────────────

def _flatten_docx_table(table) -> str:
    """
    Convert a python-docx Table object into:
      "Col1: Val | Col2: Val | Col3: Val\\n"
    """
    rows = []
    cells_by_row = [
        [cell.text.strip() for cell in row.cells]
        for row in table.rows
    ]
    if not cells_by_row:
        return ""

    headers = cells_by_row[0]
    for row in cells_by_row[1:]:
        pairs = [
            f"{h}: {v}" if h else v
            for h, v in zip(headers, row)
            if v
        ]
        if pairs:
            rows.append(" | ".join(pairs))

    return "\n".join(rows)


# ── Image extraction ───────────────────────────────────────────────────────────

def _extract_docx_images(doc: Document) -> list[bytes]:
    """Return raw bytes for every embedded image in the DOCX (inline + drawing)."""
    images: list[bytes] = []
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            try:
                images.append(rel.target_part.blob)
            except Exception:
                pass
    return images


async def _describe_image(img_bytes: bytes, doc_id: str, slide_or_section: int) -> Optional[str]:
    if len(img_bytes) < 500:
        return None
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    logger.info("vision_llm_called", section=slide_or_section, doc_id=doc_id)
    try:
        return await ollama_client.describe_image(img_b64, VISION_PROMPT)
    except Exception as exc:
        logger.warning("vision_llm_error", section=slide_or_section, doc_id=doc_id, error=str(exc))
        return None


# ── Main pipeline ──────────────────────────────────────────────────────────────

async def docx_pipeline(
    file_path: str,
    doc_id: str,
    filename: str,
    progress_callback: ProgressCallback = None,
) -> list[tuple[str, dict]]:
    """
    Process a DOCX file into (text, metadata) chunks.

    Strategy:
    - Paragraphs are collected into "sections" (split on heading styles).
    - Each section is chunked using smart_chunk().
    - Tables are flattened and stored as single table chunks.
    - Embedded images are vision-described if they are image-only regions.
    """
    from ingestion.service import smart_chunk

    try:
        doc = Document(file_path)
    except Exception as exc:
        logger.error("docx_open_failed", filename=filename, error=str(exc))
        raise

    chunks: list[tuple[str, dict]] = []
    current_section_lines: list[str] = []
    section_num = 0

    def _flush_section(lines: list[str], sec_num: int) -> None:
        text = "\n".join(lines).strip()
        if not text:
            return
        meta = {
            "doc_id":      doc_id,
            "filename":    filename,
            "page":        sec_num,
            "bbox":        [0, 0, 0, 0],
            "font_size":   0.0,
            "is_bold":     False,
            "block_type":  "text",
            "ingested_at": _now(),
            "source_type": "docx",
        }
        chunks.extend(smart_chunk(text, sec_num, meta))

    total_elements = len(doc.element.body)
    processed = 0

    for child in doc.element.body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "p":
            # Paragraph
            from docx.oxml.ns import qn as _qn
            style_elem = child.find(f".//{_qn('w:pStyle')}")
            style_name = (style_elem.get(_qn("w:val")) or "") if style_elem is not None else ""
            is_heading  = "Heading" in style_name or "heading" in style_name

            para_text = "".join(
                r.text for r in child.findall(f".//{qn('w:t')}")
            ).strip()

            if is_heading and current_section_lines:
                section_num += 1
                _flush_section(current_section_lines, section_num)
                current_section_lines = []

            if para_text:
                current_section_lines.append(para_text)

        elif tag == "tbl":
            # Flush pending text before table
            if current_section_lines:
                section_num += 1
                _flush_section(current_section_lines, section_num)
                current_section_lines = []

            # Find the table object corresponding to this XML element
            for table in doc.tables:
                if table._tbl is child:
                    table_text = _flatten_docx_table(table)
                    if table_text:
                        section_num += 1
                        meta = {
                            "doc_id":      doc_id,
                            "filename":    filename,
                            "page":        section_num,
                            "bbox":        [0, 0, 0, 0],
                            "font_size":   0.0,
                            "is_bold":     False,
                            "block_type":  "table",
                            "ingested_at": _now(),
                            "source_type": "docx",
                        }
                        chunks.extend(smart_chunk(table_text, section_num, meta))
                    break

        processed += 1
        if progress_callback and total_elements:
            progress_callback(doc_id, "parsing", processed, total_elements)

    # Flush final section
    if current_section_lines:
        section_num += 1
        _flush_section(current_section_lines, section_num)

    # ── Embedded images ───────────────────────────────────────────────────────
    images = _extract_docx_images(doc)
    for i, img_bytes in enumerate(images):
        desc = await _describe_image(img_bytes, doc_id, i)
        if desc and desc.strip():
            section_num += 1
            meta = {
                "doc_id":      doc_id,
                "filename":    filename,
                "page":        section_num,
                "bbox":        [0, 0, 0, 0],
                "font_size":   0.0,
                "is_bold":     False,
                "block_type":  "image_description",
                "ingested_at": _now(),
                "source_type": "docx",
            }
            chunks.append((desc.strip(), meta))

    logger.info(
        "docx_pipeline_complete",
        filename=filename, doc_id=doc_id, chunks=len(chunks),
    )
    return chunks


# ── HTML pipeline (Confluence exports) ────────────────────────────────────────

async def html_pipeline(
    file_path: str,
    doc_id: str,
    filename: str,
    progress_callback: ProgressCallback = None,
) -> list[tuple[str, dict]]:
    """
    Parse a Confluence HTML export into chunks using BeautifulSoup.
    Tables are flattened; images are skipped (no binary available in HTML exports).
    """
    from ingestion.service import smart_chunk

    try:
        from bs4 import BeautifulSoup
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            soup = BeautifulSoup(fh.read(), "html.parser")
    except Exception as exc:
        logger.error("html_open_failed", filename=filename, error=str(exc))
        raise

    chunks: list[tuple[str, dict]] = []
    section_num = 0

    def _base_meta(block_type: str) -> dict:
        return {
            "doc_id":      doc_id,
            "filename":    filename,
            "page":        section_num,
            "bbox":        [0, 0, 0, 0],
            "font_size":   0.0,
            "is_bold":     False,
            "block_type":  block_type,
            "ingested_at": _now(),
            "source_type": "html",
        }

    # Walk top-level elements
    body = soup.find("body") or soup
    elements = list(body.children)
    total = len(elements)

    for i, elem in enumerate(elements):
        if not hasattr(elem, "name") or not elem.name:
            continue

        if elem.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            section_num += 1

        if elem.name == "table":
            # Flatten table rows
            rows = []
            header_cells = [th.get_text(strip=True) for th in (elem.find("tr") or {}).find_all(["th", "td"])]
            for tr in elem.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                pairs = [
                    f"{h}: {v}" if h else v
                    for h, v in zip(header_cells, cells) if v
                ]
                if pairs:
                    rows.append(" | ".join(pairs))
            if rows:
                section_num += 1
                meta = _base_meta("table")
                chunks.extend(smart_chunk("\n".join(rows), section_num, meta))
        else:
            text = elem.get_text(separator=" ", strip=True)
            if text and len(text.split()) >= 5:
                meta = _base_meta("text")
                chunks.extend(smart_chunk(text, section_num, meta))

        if progress_callback:
            progress_callback(doc_id, "parsing", i + 1, total)

    logger.info(
        "html_pipeline_complete",
        filename=filename, doc_id=doc_id, chunks=len(chunks),
    )
    return chunks
