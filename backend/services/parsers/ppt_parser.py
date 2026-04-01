"""
LAKO — PowerPoint Parser
Extracts slide text and speaker notes from .pptx files.
Uses python-pptx. Each slide becomes a separate ParsedPage.
Session 6: Fully implemented.
Session 13: _render_slides_to_images() added — LibreOffice headless primary,
             Pillow composition fallback. Enables vision pipeline for image-only slides.
"""

import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

from pptx import Presentation

from services.parsers.pdf_parser import ParsedDocument, ParsedPage


class PPTParser:
    """
    Parses .pptx files using python-pptx.
    Each slide becomes a separate 'page' in ParsedDocument.
    Extracts: slide title (prefixed with #), all text boxes, speaker notes.
    _render_slides_to_images() renders each slide as PNG for vision pipeline.
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
        Extract all text from a single slide.
        Order: title (with # prefix) → remaining text boxes → speaker notes.
        """
        parts = []

        # Title — identified via slide.shapes.title
        title_shape = slide.shapes.title
        title_id = title_shape.shape_id if title_shape else None
        if title_shape and title_shape.has_text_frame:
            title = title_shape.text_frame.text.strip()
            if title:
                parts.append(f"# {title}")

        # All other text-bearing shapes (text boxes, content placeholders)
        for shape in slide.shapes:
            if shape.shape_id == title_id:
                continue
            if shape.has_text_frame:
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

    def _render_slides_to_images(self, pptx_path: Path) -> List[bytes]:
        """
        Render each slide of a PPTX file as PNG bytes.
        Tries LibreOffice headless first; falls back to Pillow shape composition.
        Returns [] gracefully if both methods fail (text-only mode continues).
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
        """
        Use LibreOffice headless to convert each slide to a PNG.
        Command: soffice --headless --convert-to png --outdir <tmpdir> <file>
        LibreOffice names outputs: <stem>.png (1 slide) or <stem>0.png, <stem>1.png, ...
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = subprocess.run(
                [soffice, "--headless", "--convert-to", "png", "--outdir", tmpdir, str(pptx_path)],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"LibreOffice exit {proc.returncode}: {proc.stderr.strip()}")

            # Collect all PNGs in temp dir (all belong to this conversion)
            png_files = sorted(Path(tmpdir).glob("*.png"), key=lambda p: p.name)
            if not png_files:
                raise RuntimeError("LibreOffice produced no PNG files")

            return [f.read_bytes() for f in png_files]

    def _render_with_pillow(self, pptx_path: Path) -> List[bytes]:
        """
        Pillow fallback: compose each slide by pasting embedded picture shapes
        onto a white canvas sized to the presentation dimensions.
        Text-only slides produce a white canvas (text is captured via parse() separately).
        Image-only slides will have their pictures composited here.
        """
        from PIL import Image as PILImage

        prs = Presentation(str(pptx_path))
        slide_width = prs.slide_width   # EMU
        slide_height = prs.slide_height  # EMU

        # Convert EMU → pixels at 96 DPI (914400 EMU = 1 inch)
        px_w = max(int(slide_width / 914400 * 96), 800)
        px_h = max(int(slide_height / 914400 * 96), 600)
        scale_x = px_w / slide_width
        scale_y = px_h / slide_height

        results = []
        for slide in prs.slides:
            canvas = PILImage.new("RGB", (px_w, px_h), "white")

            for shape in slide.shapes:
                # shape_type 13 = MSO_SHAPE_TYPE.PICTURE
                if shape.shape_type == 13:
                    try:
                        pic_bytes = shape.image.blob
                        pic_img = PILImage.open(io.BytesIO(pic_bytes)).convert("RGB")
                        left = max(int(shape.left * scale_x), 0)
                        top = max(int(shape.top * scale_y), 0)
                        w = max(int(shape.width * scale_x), 1)
                        h = max(int(shape.height * scale_y), 1)
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
