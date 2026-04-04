"""
LAKO — PDF Parser
Extracts text, tables, and images from PDF files.
Primary: PyMuPDF (fitz) | Table extraction: pdfplumber | OCR: vision model → Tesseract fallback.
Session 5:  Fully implemented.
Session 13: Vision OCR for scanned PDFs; Tesseract fallback.
Session 15: pdfplumber table extraction — tables inserted inline at their vertical position
            using get_text("dict") bounding boxes. Output is unified prose + markdown table flow.
Session 16: Caption capture (Fix 1b); table summary prompt upgrade (Fix 1a).
Session 17: Significance marker detection — cells containing *, †, ‡ etc. are flagged in
            ParsedPage.significance_markers and flow through to chunk metadata.
            Contextual row/column injection — each data cell is prefixed with its column
            header (e.g. 'Category: Hispanic | Year: 2022 | Uninsured Rate: 8.6%') so
            every row remains self-contained after chunking.
Session 18: Raw-text safety net — when pdfplumber detects table regions but the resulting
            inline text is <70% the length of the raw PyMuPDF text, the raw text is
            appended as a supplementary block. Prevents data loss for large appendix
            tables (e.g. Table A-1) where merged cells or indented row groups cause
            pdfplumber to fragment or miss rows.
"""

import io
import logging
import shutil
from pathlib import Path
from typing import List, Optional

import fitz  # PyMuPDF

from dataclasses import dataclass, field

# Characters used as statistical significance markers in tables
_SIGNIFICANCE_CHARS = frozenset(["*", "†", "‡", "§", "¶", "^"])

try:
    import pdfplumber
    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    _PDFPLUMBER_AVAILABLE = False
    logging.warning(
        "[pdf-parser] pdfplumber not installed — table extraction disabled. "
        "Run: pip install pdfplumber"
    )


@dataclass
class ParsedPage:
    page_number: int
    text: str
    tables: List[str] = field(default_factory=list)    # kept for legacy callers; empty when inline mode active
    images: List[bytes] = field(default_factory=list)  # raw image bytes
    ocr_mode: str = ""                                 # "vision" if page needs async vision OCR
    ocr_png_bytes: Optional[bytes] = None              # PNG bytes for OCR
    significance_markers: str = ""                     # unique significance chars found in table cells (e.g. "*†")


@dataclass
class ParsedDocument:
    filename: str
    pages: List[ParsedPage] = field(default_factory=list)
    total_pages: int = 0
    used_ocr: bool = False


class PDFParser:
    """
    Parses PDF files using PyMuPDF + pdfplumber.

    Native pages:  pdfplumber locates tables (bounding boxes), PyMuPDF get_text("dict")
                   provides text blocks with bounding boxes. Both are merged by y-position
                   to produce a single inline text flow: prose → table → prose → …
                   Tables are emitted as markdown (| col | col |) so the chunker can
                   detect and handle them without splitting mid-row.

    Scanned pages: Rendered as 2× PNG and flagged ocr_mode="vision". The async vision
                   pipeline in ingest.py fills in the text after parse() returns.
                   Tesseract is available as fallback.
    """

    def parse(self, file_path: Path) -> ParsedDocument:
        """
        Extract text and images from a PDF, page by page.
        Returns ParsedDocument with inline prose+table text per page.
        """
        file_path = Path(file_path)
        doc_fitz = fitz.open(str(file_path))
        parsed = ParsedDocument(filename=file_path.name, total_pages=len(doc_fitz))
        used_ocr = False

        doc_plumber = None
        if _PDFPLUMBER_AVAILABLE:
            try:
                doc_plumber = pdfplumber.open(str(file_path))
            except Exception as exc:
                logging.warning(f"[pdf-parser] pdfplumber failed to open {file_path.name}: {exc}")

        try:
            for page_index in range(len(doc_fitz)):
                page_fitz = doc_fitz[page_index]
                page_number = page_index + 1

                # Use plain get_text for scanned-page detection (fast)
                raw_text = page_fitz.get_text()
                images = self._extract_page_images(page_fitz, doc_fitz)

                if self._is_scanned(raw_text):
                    png_bytes = self._vision_ocr_page(page_fitz)
                    used_ocr = True
                    parsed.pages.append(ParsedPage(
                        page_number=page_number,
                        text="",          # filled by vision OCR in ingest.py
                        images=images,
                        ocr_mode="vision",
                        ocr_png_bytes=png_bytes,
                    ))
                else:
                    # Inline reconstruction: prose + tables merged by vertical position
                    if doc_plumber is not None:
                        page_plumber = doc_plumber.pages[page_index]
                        inline_text, sig_markers = self._extract_page_inline(
                            page_fitz, page_plumber, raw_text=raw_text
                        )
                    else:
                        inline_text, sig_markers = raw_text, ""

                    parsed.pages.append(ParsedPage(
                        page_number=page_number,
                        text=inline_text,
                        images=images,
                        significance_markers=sig_markers,
                    ))
        finally:
            doc_fitz.close()
            if doc_plumber is not None:
                doc_plumber.close()

        parsed.used_ocr = used_ocr
        return parsed

    # ── Inline reconstruction ─────────────────────────────────────────────────

    def _extract_page_inline(self, page_fitz, page_plumber, raw_text: str = "") -> tuple:
        """
        Position-aware inline reconstruction using both parsers.
        Returns (inline_text: str, significance_markers: str).

        1. Find all pdfplumber tables and their bounding boxes (y0, y1).
        2. Capture the text block immediately above each table (≤30px gap) as
           its caption — prepend it to the markdown so the chunk contains the
           title text ("Table 1.1 Overview…") and BM25 can hit it directly.
        3. Extract PyMuPDF text blocks, skipping table regions and absorbed
           caption blocks.
        4. Sort text blocks + table markdown by y0 position and join.
        5. Collect any statistical significance markers found across all table
           cells on the page (e.g. "*", "†") into a deduplicated string.
        6. Raw-text safety net: if pdfplumber excluded text blocks (table regions)
           but its markdown output is sparse, the raw PyMuPDF text is appended as
           a supplementary block so no demographic row labels are lost.
        """
        elements: List[tuple] = []  # (y0, content_str)

        # ── Pre-extract text blocks for caption detection ─────────────────────
        raw_text_blocks: List[tuple] = []  # (by0, by1, block_text)
        try:
            blocks = page_fitz.get_text("dict").get("blocks", [])
            for block in blocks:
                if block.get("type") != 0:
                    continue
                by0 = block["bbox"][1]
                by1 = block["bbox"][3]
                lines_text = []
                for line in block.get("lines", []):
                    span_text = "".join(s["text"] for s in line.get("spans", []))
                    if span_text.strip():
                        lines_text.append(span_text)
                block_text = "\n".join(lines_text).strip()
                if block_text:
                    raw_text_blocks.append((by0, by1, block_text))
        except Exception as exc:
            logging.warning(f"[pdf-parser] PyMuPDF dict pre-extraction error: {exc}")
            return page_fitz.get_text(), ""

        # ── Tables from pdfplumber (with caption capture) ─────────────────────
        table_y_regions: List[tuple] = []  # (y0, y1) of each detected table
        absorbed_caption_y0s: set = set()  # by0 of blocks absorbed as captions
        page_sig_markers: set = set()       # significance chars found across all tables

        try:
            pl_tables = page_plumber.find_tables()
            for pt in pl_tables:
                data = pt.extract()
                if not data:
                    continue
                md, table_markers = self._table_data_to_markdown(data)
                if table_markers:
                    page_sig_markers.update(table_markers)
                if md:
                    y0, y1 = pt.bbox[1], pt.bbox[3]
                    table_y_regions.append((y0, y1))

                    # Look for caption: nearest text block ending ≤30px above table
                    caption_text = ""
                    best_gap = 31
                    for (by0, by1_blk, btext) in raw_text_blocks:
                        gap = y0 - by1_blk
                        if 0 <= gap <= 30 and gap < best_gap:
                            caption_text = btext
                            best_gap = gap
                            best_caption_y0 = by0

                    if caption_text:
                        absorbed_caption_y0s.add(best_caption_y0)
                        table_content = f"{caption_text}\n{md}"
                    else:
                        table_content = md

                    elements.append((y0, table_content))
        except Exception as exc:
            logging.warning(f"[pdf-parser] pdfplumber table extraction error: {exc}")

        # ── Text blocks from PyMuPDF, skipping table regions + captions ───────
        for (by0, by1, block_text) in raw_text_blocks:
            if by0 in absorbed_caption_y0s:
                continue
            if any(not (by1 < ty0 or by0 > ty1) for ty0, ty1 in table_y_regions):
                continue
            elements.append((by0, block_text))

        # ── Sort by vertical position and join ────────────────────────────────
        elements.sort(key=lambda x: x[0])
        text = "\n\n".join(content for _, content in elements)
        markers_str = "".join(sorted(page_sig_markers))

        # ── Raw-text safety net ───────────────────────────────────────────────
        # If pdfplumber excluded text regions (table bounding boxes) but its
        # markdown output is sparse — e.g. large appendix tables with merged
        # cells or indented row groups that pdfplumber fragments — the inline
        # text can be significantly shorter than the raw PyMuPDF text, leaving
        # row labels like "Naturalized citizen" unindexed.
        # When this is detected, append the raw text as a supplementary block.
        # Threshold: inline < 70% of raw AND there were detected table regions
        # (meaning pdfplumber actively excluded text blocks from the prose flow).
        if (
            raw_text
            and table_y_regions
            and len(text.strip()) < len(raw_text.strip()) * 0.70
        ):
            logging.debug(
                f"[pdf-parser] raw-text safety net triggered "
                f"(inline={len(text)}, raw={len(raw_text)})"
            )
            text = text + "\n\n" + raw_text.strip()

        return text, markers_str

    def _table_data_to_markdown(self, data: List[List]) -> tuple:
        """
        Convert pdfplumber table data (list of lists) to a markdown table string.
        Returns (markdown_str, markers_str).

        Fix 2 — Contextual row/column injection: each data cell is rendered as
        "ColHeader: value" so every row is self-contained after chunking — the
        model never loses track of what column a value belongs to.

        Fix 1 — Significance marker detection: scans all data cell values for
        known significance characters (*, †, ‡, §, ¶, ^). Returns a deduplicated
        string of found markers (e.g. "*" or "*†") as the second element.
        """
        if not data or not data[0]:
            return "", ""

        def clean(cell) -> str:
            if cell is None:
                return ""
            return str(cell).strip().replace("\n", " ")

        headers = [clean(h) for h in data[0]]
        if not any(headers):
            return "", ""

        col_count = len(headers)
        separator = ["---"] * col_count

        # ── Significance marker scan ──────────────────────────────────────────
        found_markers: set = set()
        for row in data[1:]:
            for i in range(col_count):
                val = clean(row[i]) if i < len(row) else ""
                for ch in val:
                    if ch in _SIGNIFICANCE_CHARS:
                        found_markers.add(ch)
        markers_str = "".join(sorted(found_markers))

        # ── Header row + separator (kept for structure reference) ─────────────
        lines = ["| " + " | ".join(headers) + " |"]
        lines.append("| " + " | ".join(separator) + " |")

        # ── Data rows with header injection ──────────────────────────────────
        # Each cell: "ColHeader: value" — self-contained after any split.
        # Empty cells are left blank to avoid padding noise.
        for row in data[1:]:
            cells = []
            for i in range(col_count):
                val = clean(row[i]) if i < len(row) else ""
                header = headers[i]
                if val and header:
                    cells.append(f"{header}: {val}")
                else:
                    cells.append(val)
            lines.append("| " + " | ".join(cells) + " |")

        return "\n".join(lines), markers_str

    # ── Standard helpers (unchanged from Session 5 / 13) ─────────────────────

    def _extract_page_images(self, page, doc) -> List[bytes]:
        """Extract all embedded images from a PyMuPDF page."""
        image_bytes_list = []
        for img_ref in page.get_images(full=True):
            xref = img_ref[0]
            try:
                base_image = doc.extract_image(xref)
                image_bytes_list.append(base_image["image"])
            except Exception:
                continue
        return image_bytes_list

    def _vision_ocr_page(self, page) -> bytes:
        """
        Render a PDF page as a high-resolution PNG for vision model OCR.
        The caller (ingest.py) sends these bytes to vision_service.
        """
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        return pix.tobytes("png")

    def _ocr_page_tesseract(self, png_bytes: bytes) -> str:
        """Tesseract OCR fallback: used when vision model call fails or times out."""
        _check_tesseract()
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(png_bytes))
        return pytesseract.image_to_string(img)

    def _is_scanned(self, text: str) -> bool:
        """Return True if extracted text is too short — likely a scanned page."""
        return len(text.strip()) < 50


def _check_tesseract():
    """
    Verify that the Tesseract binary is installed and on PATH.
    Raises RuntimeError with a clear install instruction.
    """
    if shutil.which("tesseract") is None:
        raise RuntimeError(
            "Tesseract OCR is not installed or not on PATH. "
            "Install it with: brew install tesseract\n"
            "Then restart the backend server."
        )


# Singleton instance
pdf_parser = PDFParser()
