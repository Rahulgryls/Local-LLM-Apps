"""
LAKO — PowerPoint Parser
Extracts slide text, tables, and speaker notes from .pptx files.
Uses python-pptx. Each slide becomes a separate ParsedPage.
Session 6:  Fully implemented (text + notes).
Session 13: _render_slides_to_images() — LibreOffice headless primary, Pillow fallback.
Session 15: shape.has_table detection — tables emitted as markdown inline with slide text.
"""

import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

from pptx import Presentation
from pptx.table import Table as PptxTable

from services.parsers.pdf_parser import ParsedDocument, ParsedPage


class PPTParser:
    """
    Parses .pptx files using python-pptx.
    Each slide becomes a separate 'page' in ParsedDocument.

    Shape extraction order per slide:
      1. Title (with # prefix)
      2. All other shapes in z-order:
         - Text frames → plain text
         - Tables       → markdown table (| col | col |)
         - Other shapes  → skipped
      3. Speaker notes (prefixed [Notes: ...])

    Tables are emitted inline so the chunker can keep the slide's
    explanatory text and its table in the same chunk.
    """

    def parse(self, file_path: Path) -> ParsedDocument:
        """
        Extract slide text and notes from a PowerPoint file.
        Returns ParsedDocument where each page = one slide.
        """
        file_path = Path(file_path)
        prs = Presentation(str(file_path))
        pages = []

        for slide_index, slide in enumerate(prs.slides):
            text = self._slide_to_text(slide)
            pages.append(ParsedPage(
                page_number=slide_index + 1,
                text=text,
            ))

        return ParsedDocument(
            filename=file_path.name,
            pages=pages,
            total_pages=len(prs.slides),
        )

    def _slide_to_text(self, slide) -> str:
        """
        Extract all text and tables from a single slide in shape order.
        Title → text boxes / tables → notes.
        """
        parts: List[str] = []

        # Title
        title_shape = slide.shapes.title
        title_id = title_shape.shape_id if title_shape else None
        if title_shape and title_shape.has_text_frame:
            title = title_shape.text_frame.text.strip()
            if title:
                parts.append(f"# {title}")

        # All other shapes
        for shape in slide.shapes:
            if shape.shape_id == title_id:
                continue

            if shape.has_table:
                md = self._table_to_markdown(shape.table)
                if md.strip():
                    parts.append(md)
            elif shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text:
                    parts.append(text)

        # Speaker notes
        if slide.has_notes_slide:
            notes_tf = slide.notes_slide.notes_text_frame
            if notes_tf:
                notes = notes_tf.text.strip()
                if notes:
                    parts.append(f"[Notes: {notes}]")

        return "\n\n".join(parts)

    def _table_to_markdown(self, table: PptxTable) -> str:
        """
        Convert a python-pptx Table to a markdown table string.
        First row is treated as the header row.
        """
        rows: List[List[str]] = []
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
            rows.append(cells)

        if not rows:
            return ""

        headers = rows[0]
        col_count = len(headers)
        separator = ["---"] * col_count

        lines = ["| " + " | ".join(headers) + " |"]
        lines.append("| " + " | ".join(separator) + " |")

        for row in rows[1:]:
            padded = (row + [""] * col_count)[:col_count]
            lines.append("| " + " | ".join(padded) + " |")

        return "\n".join(lines)

    # ── Slide image rendering (Session 13 — unchanged) ────────────────────────

    def _render_slides_to_images(self, pptx_path: Path) -> List[bytes]:
        """
        Render each slide as PNG bytes.
        LibreOffice headless primary; Pillow shape composition fallback.
        Returns [] gracefully if both methods fail.
        """
        pptx_path = Path(pptx_path)

        soffice = shutil.which("soffice")
        if soffice:
            try:
                result = self._render_with_libreoffice(pptx_path, soffice)
                if result:
                    logging.info(f"[pptx-vision] LibreOffice rendered {len(result)} slide(s) from {pptx_path.name}")
                    return result
            except Exception as exc:
                logging.warning(f"[pptx-vision] LibreOffice failed: {exc} — trying Pillow fallback")

        try:
            result = self._render_with_pillow(pptx_path)
            logging.info(f"[pptx-vision] Pillow rendered {len(result)} slide(s) from {pptx_path.name}")
            return result
        except Exception as exc:
            logging.warning(f"[pptx-vision] Pillow fallback also failed: {exc}")
            return []

    def _render_with_libreoffice(self, pptx_path: Path, soffice: str) -> List[bytes]:
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = subprocess.run(
                [soffice, "--headless", "--convert-to", "png", "--outdir", tmpdir, str(pptx_path)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"LibreOffice exit {proc.returncode}: {proc.stderr.strip()}")

            png_files = sorted(Path(tmpdir).glob("*.png"), key=lambda p: p.name)
            if not png_files:
                raise RuntimeError("LibreOffice produced no PNG files")

            return [f.read_bytes() for f in png_files]

    def _render_with_pillow(self, pptx_path: Path) -> List[bytes]:
        from PIL import Image as PILImage

        prs = Presentation(str(pptx_path))
        slide_width  = prs.slide_width
        slide_height = prs.slide_height

        px_w = max(int(slide_width  / 914400 * 96), 800)
        px_h = max(int(slide_height / 914400 * 96), 600)
        scale_x = px_w / slide_width
        scale_y = px_h / slide_height

        results = []
        for slide in prs.slides:
            canvas = PILImage.new("RGB", (px_w, px_h), "white")

            for shape in slide.shapes:
                if shape.shape_type == 13:   # MSO_SHAPE_TYPE.PICTURE
                    try:
                        pic_bytes = shape.image.blob
                        pic_img = PILImage.open(io.BytesIO(pic_bytes)).convert("RGB")
                        left = max(int(shape.left  * scale_x), 0)
                        top  = max(int(shape.top   * scale_y), 0)
                        w    = max(int(shape.width  * scale_x), 1)
                        h    = max(int(shape.height * scale_y), 1)
                        pic_img = pic_img.resize((w, h), PILImage.LANCZOS)
                        canvas.paste(pic_img, (left, top))
                    except Exception:
                        pass

            buf = io.BytesIO()
            canvas.save(buf, format="PNG")
            results.append(buf.getvalue())

        return results


# Singleton instance
ppt_parser = PPTParser()
