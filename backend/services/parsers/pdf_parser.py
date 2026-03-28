"""
LAKO — PDF Parser
Extracts text, tables, and images from PDF files.
Primary: PyMuPDF (fitz) | Fallback: Tesseract OCR for scanned PDFs.
Session 1: Stub — wired in Session 5.
"""

from pathlib import Path
from typing import List, Optional
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
        Extract all text, tables, and images from a PDF.
        Returns ParsedDocument with per-page content.
        TODO (Session 5): implement with fitz (PyMuPDF).
        """
        raise NotImplementedError("PDFParser.parse() — Session 5")

    def _extract_page_text(self, page) -> str:
        """Extract text from a single PyMuPDF page object."""
        raise NotImplementedError("PDFParser._extract_page_text() — Session 5")

    def _extract_page_images(self, page, doc) -> List[bytes]:
        """Extract all images from a single PyMuPDF page as raw bytes."""
        raise NotImplementedError("PDFParser._extract_page_images() — Session 5 / 7")

    def _ocr_page(self, page) -> str:
        """
        Apply Tesseract OCR to a page rendered as an image.
        Used when PyMuPDF returns empty text (scanned PDF).
        TODO (Session 5): implement with pytesseract.
        """
        raise NotImplementedError("PDFParser._ocr_page() — Session 5")

    def _is_scanned(self, text: str) -> bool:
        """Return True if extracted text is empty/too short (likely scanned)."""
        return len(text.strip()) < 50


# Singleton instance
pdf_parser = PDFParser()
