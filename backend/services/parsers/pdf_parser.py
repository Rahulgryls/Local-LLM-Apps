"""
LAKO — PDF Parser
Extracts text, tables, and images from PDF files.
Primary: PyMuPDF (fitz) | Fallback: vision model OCR for scanned PDFs.
Session 5: Fully implemented.
Session 13: _vision_ocr_page() replaces Tesseract as primary OCR;
             Tesseract kept as fallback via _ocr_page_tesseract().
"""

import io
import shutil
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF

from dataclasses import dataclass, field


@dataclass
class ParsedPage:
    page_number: int
    text: str
    tables: List[str] = field(default_factory=list)   # table as formatted text
    images: List[bytes] = field(default_factory=list)  # raw image bytes
    ocr_mode: str = ""                    # "vision" if page needs async vision OCR
    ocr_png_bytes: Optional[bytes] = None  # PNG bytes for OCR (vision or Tesseract fallback)


@dataclass
class ParsedDocument:
    filename: str
    pages: List[ParsedPage] = field(default_factory=list)
    total_pages: int = 0
    used_ocr: bool = False


class PDFParser:
    """
    Parses PDF files using PyMuPDF.
    For scanned/image-only pages, renders to PNG and flags for vision OCR in ingest.py.
    Tesseract remains available as a fallback via _ocr_page_tesseract().
    """

    def parse(self, file_path: Path) -> ParsedDocument:
        """
        Extract all text and images from a PDF, page by page.
        If a page has no extractable text (scanned), renders it as PNG and sets
        ocr_mode="vision" on the ParsedPage — the text field will be filled by
        vision_service in ingest.py after parse() returns.
        Returns a ParsedDocument with one ParsedPage per PDF page.
        """
        file_path = Path(file_path)
        doc = fitz.open(str(file_path))
        parsed = ParsedDocument(filename=file_path.name, total_pages=len(doc))
        used_ocr = False

        for page_index in range(len(doc)):
            page = doc[page_index]
            page_number = page_index + 1

            text = self._extract_page_text(page)
            images = self._extract_page_images(page, doc)

            if self._is_scanned(text):
                png_bytes = self._vision_ocr_page(page)
                used_ocr = True
                parsed.pages.append(ParsedPage(
                    page_number=page_number,
                    text="",          # filled by vision OCR in ingest.py
                    images=images,
                    ocr_mode="vision",
                    ocr_png_bytes=png_bytes,
                ))
            else:
                parsed.pages.append(ParsedPage(
                    page_number=page_number,
                    text=text,
                    images=images,
                ))

        doc.close()
        parsed.used_ocr = used_ocr
        return parsed

    def _extract_page_text(self, page) -> str:
        """Extract plain text from a single PyMuPDF page object."""
        return page.get_text()

    def _extract_page_images(self, page, doc) -> List[bytes]:
        """
        Extract all embedded images from a PyMuPDF page.
        Returns a list of raw image bytes (one per image found on the page).
        """
        image_bytes_list = []
        image_list = page.get_images(full=True)

        for img_ref in image_list:
            xref = img_ref[0]
            try:
                base_image = doc.extract_image(xref)
                image_bytes_list.append(base_image["image"])
            except Exception:
                # Skip unextractable images — don't crash the whole page
                continue

        return image_bytes_list

    def _vision_ocr_page(self, page) -> bytes:
        """
        Render a PDF page as a high-resolution PNG for vision model OCR.
        Returns PNG bytes. Does NOT call Tesseract.
        The caller (ingest.py) sends these bytes to vision_service.describe_image_bytes().
        """
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        return pix.tobytes("png")

    def _ocr_page_tesseract(self, png_bytes: bytes) -> str:
        """
        Tesseract OCR fallback: run pytesseract on pre-rendered PNG bytes.
        Used when vision model call fails or times out.
        """
        _check_tesseract()

        import pytesseract
        from PIL import Image

        img = Image.open(io.BytesIO(png_bytes))
        return pytesseract.image_to_string(img)

    def _is_scanned(self, text: str) -> bool:
        """Return True if extracted text is empty/too short — likely a scanned page."""
        return len(text.strip()) < 50


def _check_tesseract():
    """
    Verify that the Tesseract binary is installed and on PATH.
    Raises RuntimeError with a clear install instruction rather than
    crashing with an obscure pytesseract error.
    """
    if shutil.which("tesseract") is None:
        raise RuntimeError(
            "Tesseract OCR is not installed or not on PATH. "
            "Install it with: brew install tesseract\n"
            "Then restart the backend server."
        )


# Singleton instance
pdf_parser = PDFParser()
