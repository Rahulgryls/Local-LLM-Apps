"""
LAKO — Rotation Detection Unit Tests

Tests _detect_page_rotation() using real PyMuPDF document fixtures.
No mocking — these tests exercise the actual PyMuPDF text-direction metadata.

Run from backend/:
    python -m pytest tests/test_rotation_detection.py -v

Coverage:
  - Normal horizontal text → None
  - Text rotated 90° → 'rotated'
  - Mixed page below 30% threshold → None
  - Mixed page above 30% threshold → 'rotated'
  - Blank page → None
  - Image-only page → None
"""

import io
import sys
import unittest
from pathlib import Path

# ── Make sure the backend src dir is on the path ──────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

import fitz  # PyMuPDF


def _make_doc_with_horizontal_text(text: str, font_size: int = 11) -> fitz.Document:
    """Return a single-page fitz.Document with horizontal text."""
    doc  = fitz.open()
    page = doc.new_page(width=595, height=842)   # A4 portrait
    page.insert_text((72, 100), text, fontsize=font_size)
    return doc


def _make_doc_with_rotated_text(text: str, rotate: int = 90) -> fitz.Document:
    """Return a single-page fitz.Document with text rendered at *rotate* degrees."""
    doc  = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((300, 400), text, fontsize=11, rotate=rotate)
    return doc


def _make_doc_mixed(
    horiz_lines: int,
    rotated_inserts: int,
) -> fitz.Document:
    """
    Return a single-page document with *horiz_lines* lines of horizontal text
    (each ~80 extracted chars) and *rotated_inserts* rotated text inserts
    (each ~65 extracted chars), placed at non-overlapping positions.

    Design rationale: PyMuPDF clips text at page boundaries, so raw char
    counts don't map 1-to-1 to get_text output.  Using line/insert counts
    gives predictable ratios for threshold tests.

    Approximate yield: ~80 chars per horizontal line, ~65 chars per rotated
    insert → rotated fraction = (65*r) / (80*h + 65*r).
    """
    doc  = fitz.open()
    page = doc.new_page(width=595, height=842)

    # Insert horizontal lines starting from top, 13pt line spacing
    line_template = "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcde "  # ~33 chars, repeat twice ≈ 66
    for i in range(horiz_lines):
        y = 50 + i * 13
        if y > 800:
            break
        page.insert_text((30, y), line_template * 2, fontsize=9)

    # Insert rotated text at staggered x positions (each ~65 chars long)
    rot_template = "FGHIJKLMNOPQRSTUVWXY FGHIJKLMNOPQRSTUVWXY FGHIJKLMNO"  # ~53 chars
    for j in range(rotated_inserts):
        x = 80 + j * 60
        if x > 550:
            break
        page.insert_text((x, 780), rot_template, fontsize=9, rotate=90)

    return doc


class TestDetectPageRotation(unittest.TestCase):

    def setUp(self):
        from ingestion.service import _detect_page_rotation
        self._detect = _detect_page_rotation

    # ── 1: Normal horizontal page ─────────────────────────────────────────────

    def test_horizontal_page_returns_none(self):
        """A page with only horizontal text must return None."""
        long_text = (
            "This document contains financial data for the fiscal year 2022. "
            "The following tables present revenue, expenses and profit margins "
            "across all operating divisions of the organisation. " * 3
        )
        doc  = _make_doc_with_horizontal_text(long_text)
        page = doc[0]
        result = self._detect(page)
        self.assertIsNone(result, f"Expected None for horizontal text, got {result!r}")
        doc.close()

    # ── 2: Fully rotated page ─────────────────────────────────────────────────

    def test_rotated_page_returns_rotated(self):
        """A page where all text is rotated 90° must return 'rotated'."""
        # Use enough text to exceed the 50-char minimum for a decision
        rotated_text = (
            "WBHDCL WEST BENGAL HIGHWAY DEVELOPMENT CORPORATION LIMITED "
            "NET LOSS AFTER TAX APPENDIX FIVE POINT ONE FINANCIAL RESULTS "
            "OPERATING REVENUE TOTAL EXPENSES PROFIT BEFORE TAX"
        )
        doc  = _make_doc_with_rotated_text(rotated_text, rotate=90)
        page = doc[0]
        result = self._detect(page)
        self.assertEqual(result, "rotated", f"Expected 'rotated', got {result!r}")
        doc.close()

    # ── 3: Mixed page — rotated share below 30% threshold ─────────────────────

    def test_mixed_orientation_below_threshold(self):
        """
        Many horizontal lines + 1 rotated insert → rotated fraction < 30% → None.

        With ~12 horizontal lines (~960 extracted chars) and 1 rotated insert
        (~60 extracted chars), the rotated fraction is ~6%, well below 30%.
        """
        # 12 horizontal lines × ~80 chars = ~960 horiz; 1 rotated × ~60 = ~60 rot
        # ratio ≈ 60/1020 = 6% → below 30% threshold
        doc  = _make_doc_mixed(horiz_lines=12, rotated_inserts=1)
        page = doc[0]
        result = self._detect(page)
        self.assertIsNone(
            result,
            f"Expected None for low rotated fraction (below 30% threshold), got {result!r}",
        )
        doc.close()

    # ── 4: Mixed page — rotated share above 30% threshold ─────────────────────

    def test_mixed_orientation_above_threshold(self):
        """
        Few horizontal lines + many rotated inserts → rotated fraction > 30% → 'rotated'.

        With ~2 horizontal lines (~160 chars) and 4 rotated inserts (~240 chars),
        the rotated fraction is ~60%, well above the 30% threshold.
        """
        # 2 horizontal × ~80 = ~160 horiz; 4 rotated × ~60 = ~240 rot
        # ratio ≈ 240/400 = 60% → above 30% threshold
        doc  = _make_doc_mixed(horiz_lines=2, rotated_inserts=4)
        page = doc[0]
        result = self._detect(page)
        self.assertEqual(
            result, "rotated",
            f"Expected 'rotated' for high rotated fraction (above 30% threshold), got {result!r}",
        )
        doc.close()

    # ── 5: Empty / blank page ─────────────────────────────────────────────────

    def test_empty_page_returns_none(self):
        """A blank page with no text must return None (too little text to judge)."""
        doc  = fitz.open()
        page = doc.new_page(width=595, height=842)  # no text inserted
        result = self._detect(page)
        self.assertIsNone(result, f"Expected None for blank page, got {result!r}")
        doc.close()

    # ── 6: Image-only page ────────────────────────────────────────────────────

    def test_image_only_page_returns_none(self):
        """
        A page whose only content is an embedded image (no text blocks) must
        return None — there is no text to judge direction from.
        """
        # Create a tiny 1x1 white PNG to embed
        import struct, zlib

        def _minimal_png() -> bytes:
            def _chunk(tag: bytes, data: bytes) -> bytes:
                c = struct.pack(">I", len(data)) + tag + data
                return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

            sig    = b"\x89PNG\r\n\x1a\n"
            ihdr   = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            raw    = b"\x00\xff\xff\xff"           # filter byte + 1 RGB pixel
            idat   = _chunk(b"IDAT", zlib.compress(raw))
            iend   = _chunk(b"IEND", b"")
            return sig + ihdr + idat + iend

        doc  = fitz.open()
        page = doc.new_page(width=595, height=842)
        png_bytes = _minimal_png()
        img_xref  = page.insert_image(
            fitz.Rect(50, 50, 545, 792),
            stream=png_bytes,
        )
        result = self._detect(page)
        self.assertIsNone(result, f"Expected None for image-only page, got {result!r}")
        doc.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
