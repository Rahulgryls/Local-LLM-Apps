"""
LAKO — PPTX Pipeline (V3 Direct-RAG)

Processes PowerPoint files using python-pptx.
Each slide is classified and handled like a PDF page:

  TEXT_RICH  → direct chunking from text shapes
  TABLE      → flatten table shapes to prose rows
  IMAGE_ONLY → render slide to PNG via LibreOffice → vision model
  MIXED      → text direct + vision per picture shape

Slide-to-PNG rendering requires LibreOffice (free, brew-installable):
  brew install libreoffice

If LibreOffice is not found, IMAGE_ONLY slides are stored as empty
with a warning; text slides always work without LibreOffice.
"""

import base64
import logging
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import structlog
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Emu

from services.ollama_client import ollama_client

logger = structlog.get_logger(__name__)

VISION_PROMPT = (
    "Describe all text, data, labels, values, flows and relationships visible "
    "in this diagram or image. Be precise and complete. Include all numbers."
)

ProgressCallback = Optional[Callable[[str, str, int, int], None]]

# Detect LibreOffice at import time
_LIBREOFFICE = shutil.which("libreoffice") or shutil.which("soffice")

# Shape types that indicate a visual element (picture, chart, OLE)
_VISUAL_TYPES = {
    MSO_SHAPE_TYPE.PICTURE,
    MSO_SHAPE_TYPE.CHART,
    MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT,
    MSO_SHAPE_TYPE.LINKED_OLE_OBJECT,
    MSO_SHAPE_TYPE.GROUP,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _token_count(text: str) -> int:
    return len(text.split())


# ── Slide content extraction ───────────────────────────────────────────────────

def _extract_slide_text(slide) -> tuple[str, bool, bool]:
    """
    Return (raw_text, has_table_shape, has_visual_shape) for a slide.
    """
    text_parts: list[str] = []
    has_table  = False
    has_visual = False

    for shape in slide.shapes:
        try:
            if shape.shape_type in _VISUAL_TYPES:
                has_visual = True
        except Exception:
            pass

        if shape.has_text_frame:
            t = shape.text_frame.text.strip()
            if t:
                text_parts.append(t)

        if shape.has_table:
            has_table = True

    # Speaker notes
    try:
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                text_parts.append(f"[Notes: {notes}]")
    except Exception:
        pass

    return "\n".join(text_parts), has_table, has_visual


def _flatten_pptx_table(shape) -> str:
    """Flatten a table shape to 'Col: Val | Col: Val' rows."""
    table = shape.table
    rows: list[str] = []
    headers = [cell.text.strip() for cell in table.rows[0].cells]
    for row in table.rows[1:]:
        cells = [cell.text.strip() for cell in row.cells]
        pairs = [
            f"{h}: {v}" if h else v
            for h, v in zip(headers, cells) if v
        ]
        if pairs:
            rows.append(" | ".join(pairs))
    return "\n".join(rows)


# ── LibreOffice-based slide rendering ─────────────────────────────────────────

def _render_slide_png(pptx_path: str, slide_index: int) -> Optional[bytes]:
    """
    Render slide *slide_index* (0-based) to PNG bytes via LibreOffice.

    Exports the whole PPTX to images in a temp dir, then picks the right file.
    Returns None if LibreOffice is not installed or rendering fails.
    """
    if not _LIBREOFFICE:
        logger.warning(
            "libreoffice_not_found",
            hint="brew install libreoffice — needed to render image-only PPTX slides",
        )
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            result = subprocess.run(
                [
                    _LIBREOFFICE,
                    "--headless",
                    "--convert-to", "png",
                    "--outdir", tmpdir,
                    pptx_path,
                ],
                capture_output=True,
                timeout=120,
            )
            if result.returncode != 0:
                logger.warning(
                    "libreoffice_render_failed",
                    stderr=result.stderr.decode("utf-8", errors="replace")[:500],
                )
                return None

            # LibreOffice names output files like: filename-<N>.png (1-based)
            stem    = Path(pptx_path).stem
            img_num = slide_index + 1
            # Try zero-padded variant then plain
            for pattern in (f"{stem}-{img_num:04d}.png", f"{stem}-{img_num}.png"):
                candidate = Path(tmpdir) / pattern
                if candidate.exists():
                    return candidate.read_bytes()

            # Fall back: pick sorted list by index
            pngs = sorted(Path(tmpdir).glob("*.png"))
            if slide_index < len(pngs):
                return pngs[slide_index].read_bytes()

            return None

        except subprocess.TimeoutExpired:
            logger.warning("libreoffice_timeout", slide_index=slide_index)
            return None
        except Exception as exc:
            logger.warning("libreoffice_error", error=str(exc))
            return None


async def _describe_bytes(img_bytes: bytes, doc_id: str, slide_num: int) -> Optional[str]:
    if not img_bytes or len(img_bytes) < 500:
        return None
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    logger.info("vision_llm_called", slide=slide_num, doc_id=doc_id)
    try:
        return await ollama_client.describe_image(img_b64, VISION_PROMPT)
    except Exception as exc:
        logger.warning("vision_llm_error", slide=slide_num, doc_id=doc_id, error=str(exc))
        return None


# ── Main pipeline ──────────────────────────────────────────────────────────────

async def pptx_pipeline(
    file_path: str,
    doc_id: str,
    filename: str,
    progress_callback: ProgressCallback = None,
) -> list[tuple[str, dict]]:
    """
    Process a PPTX file into (text, metadata) chunks.

    Each slide is classified as TEXT_RICH / TABLE / IMAGE_ONLY / MIXED.
    """
    from ingestion.service import smart_chunk

    try:
        prs = Presentation(file_path)
    except Exception as exc:
        logger.error("pptx_open_failed", filename=filename, error=str(exc))
        raise

    total_slides = len(prs.slides)
    chunks: list[tuple[str, dict]] = []

    logger.info("pptx_pipeline_start", filename=filename, slides=total_slides, doc_id=doc_id)

    for idx, slide in enumerate(prs.slides):
        slide_num = idx + 1

        def _base_meta(block_type: str) -> dict:
            return {
                "doc_id":      doc_id,
                "filename":    filename,
                "page":        slide_num,
                "bbox":        [0, 0, 0, 0],
                "font_size":   0.0,
                "is_bold":     False,
                "block_type":  block_type,
                "ingested_at": _now(),
                "source_type": "pptx",
            }

        try:
            raw_text, has_table, has_visual = _extract_slide_text(slide)
            token_count = _token_count(raw_text)

            # ── TABLE slide ──────────────────────────────────────────────────
            if has_table:
                for shape in slide.shapes:
                    if shape.has_table:
                        table_text = _flatten_pptx_table(shape)
                        if table_text:
                            chunks.extend(smart_chunk(table_text, slide_num, _base_meta("table")))
                # Also keep any non-table text on the same slide
                if token_count >= 20:
                    chunks.extend(smart_chunk(raw_text, slide_num, _base_meta("text")))

            # ── IMAGE_ONLY ───────────────────────────────────────────────────
            elif has_visual and token_count < 20:
                img_bytes = _render_slide_png(file_path, idx)
                desc      = await _describe_bytes(img_bytes, doc_id, slide_num)
                if desc and desc.strip():
                    chunks.append((desc.strip(), _base_meta("image_description")))
                elif token_count > 0:
                    # Fallback: store what little text exists
                    chunks.extend(smart_chunk(raw_text, slide_num, _base_meta("text")))

            # ── MIXED ────────────────────────────────────────────────────────
            elif has_visual and token_count >= 20:
                # Text spans directly
                chunks.extend(smart_chunk(raw_text, slide_num, _base_meta("text")))
                # Vision for picture shapes
                for shape in slide.shapes:
                    try:
                        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                            img_bytes = shape.image.blob
                            desc = await _describe_bytes(img_bytes, doc_id, slide_num)
                            if desc and desc.strip():
                                chunks.append((desc.strip(), _base_meta("image_description")))
                    except Exception as exc:
                        logger.warning(
                            "pptx_shape_vision_failed",
                            slide=slide_num, doc_id=doc_id, error=str(exc),
                        )

            # ── TEXT_RICH ────────────────────────────────────────────────────
            else:
                if token_count >= 5:
                    chunks.extend(smart_chunk(raw_text, slide_num, _base_meta("text")))

        except Exception as exc:
            logger.error(
                "slide_processing_failed",
                slide=slide_num, doc_id=doc_id, error=str(exc),
            )
            # Continue to next slide

        if progress_callback:
            progress_callback(doc_id, "parsing", slide_num, total_slides)

    logger.info(
        "pptx_pipeline_complete",
        filename=filename, doc_id=doc_id, slides=total_slides, chunks=len(chunks),
    )
    return chunks
