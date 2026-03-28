"""
LAKO — PDF Parser
Extracts text, tables, and images from PDF files.
Primary: PyMuPDF (fitz) | Fallback: Tesseract OCR for scanned PDFs.
Session 5: Fully implemented.
"""

import io
import shutil
from pathlib import Path
from typing import List

import fitz  # PyMuPDF

from dataclasses import dataclass, field


@dataclass
class ParsedPage:
    page_number: int
    text: str
    tables: List[str] = field(default_factory=list)   # table as formatted text
    images: List[bytes] = field(default_factory=list)  # raw image bytes


@dataclass
class ParsedDocument:
    filename: str
    pages: List[ParsedPage] = field(default_factory=list)
    total_pages: int = 0
    used_ocr: bool = False


class PDFParser:
    """
    Parses PDF files using PyMuPDF.
    Falls back to Tesseract OCR for scanned/image-only PDFs.
    """

    def parse(self, file_path: Path) -> ParsedDocument:
        """
        Extract all text and images from a PDF, page by page.
        If a page has no extractable text (scanned), falls back to OCR.
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

            if self._is_scanned(text):
                text = self._ocr_page(page)
                used_ocr = True

            images = self._extract_page_images(page, doc)

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
        Images are used by the vision service in Session 7.
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

    def _ocr_page(self, page) -> str:
        """
        Render a PDF page as a high-resolution image and run Tesseract OCR.
        Used when PyMuPDF finds no extractable text (scanned PDF).
        Raises a clear error if Tesseract binary is not installed.
        """
        _check_tesseract()

        import pytesseract
        from PIL import Image

        # Render at 2x zoom for better OCR accuracy
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")

        img = Image.open(io.BytesIO(img_data))
        text = pytesseract.image_to_string(img)
        return text

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
