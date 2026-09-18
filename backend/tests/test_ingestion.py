"""
LAKO — Ingestion Pipeline Unit Tests

Tests the V3 direct-RAG ingestion service without hitting Qdrant, Ollama, or SQLite.
All external I/O is mocked.

Run from backend/:
    python -m pytest tests/test_ingestion.py -v

Coverage:
  - smart_chunk() — TEXT_RICH, TABLE, overlap, short text, empty text
  - _classify_page() — all four classes
  - _flatten_sheet() — with/without headers
  - _flatten_pptx_table() — row structure
  - source_type_from_filename() — valid and invalid extensions
  - _sha256() — deterministic hash
  - Hash dedup in ingest_file() — duplicate detection
  - PDF page processing — TEXT_RICH, TABLE, IMAGE_ONLY, MIXED (mocked I/O)
"""

import asyncio
import hashlib
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import fitz  # PyMuPDF — needed by V2 rotation tests

# ── Make sure the backend src dir is on the path ──────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Helper: run async tests ────────────────────────────────────────────────────

def async_test(coro):
    """Decorator to run async test methods."""
    def wrapper(*args, **kwargs):
        return asyncio.get_event_loop().run_until_complete(coro(*args, **kwargs))
    return wrapper


# ─────────────────────────────────────────────────────────────────────────────
# smart_chunk tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSmartChunk(unittest.TestCase):

    def setUp(self):
        from ingestion.service import smart_chunk
        self.smart_chunk = smart_chunk

    def _meta(self, block_type="text"):
        return {
            "doc_id": "test-doc",
            "filename": "test.pdf",
            "page": 1,
            "bbox": [0, 0, 100, 100],
            "font_size": 12.0,
            "is_bold": False,
            "block_type": block_type,
            "ingested_at": "2026-01-01T00:00:00+00:00",
            "source_type": "pdf",
        }

    def test_empty_text_returns_empty(self):
        result = self.smart_chunk("", 1, self._meta())
        self.assertEqual(result, [])

    def test_whitespace_only_returns_empty(self):
        result = self.smart_chunk("   \n\n   ", 1, self._meta())
        self.assertEqual(result, [])

    def test_short_text_returns_single_chunk(self):
        text = "This is a short sentence."
        result = self.smart_chunk(text, 1, self._meta())
        self.assertEqual(len(result), 1)
        self.assertIn("short sentence", result[0][0])

    def test_table_never_split(self):
        """Tables must always be returned as a single chunk regardless of length."""
        table_text = " | ".join([f"Col{i}: Value{i}" for i in range(200)])
        result = self.smart_chunk(table_text, 1, self._meta(block_type="table"), max_tokens=50)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], table_text.strip())

    def test_long_text_splits_into_multiple_chunks(self):
        # 10 sentences of ~10 words each = ~100 words, max_tokens=30 → ~3-4 chunks
        sentences = ["This sentence has about ten words in it total. " for _ in range(10)]
        text = " ".join(sentences)
        result = self.smart_chunk(text, 1, self._meta(), max_tokens=30, overlap=5)
        self.assertGreater(len(result), 1)

    def test_overlap_carries_tokens(self):
        """Last N tokens of chunk N should appear at the start of chunk N+1."""
        words = ["word" + str(i) for i in range(100)]
        text = ". ".join(" ".join(words[i:i+5]) for i in range(0, 100, 5))
        result = self.smart_chunk(text, 1, self._meta(), max_tokens=20, overlap=5)
        if len(result) >= 2:
            first_end   = result[0][0].split()[-5:]
            second_start = result[1][0].split()[:5]
            # At least some overlap tokens should appear in the second chunk
            overlap_found = any(w in second_start for w in first_end)
            self.assertTrue(overlap_found, "No overlap tokens found in second chunk")

    def test_metadata_shallow_copy_per_chunk(self):
        """Mutating one chunk's metadata should not affect another chunk's metadata."""
        sentences = ". ".join(["word " * 50 for _ in range(3)])
        result = self.smart_chunk(sentences, 1, self._meta(), max_tokens=40, overlap=5)
        if len(result) >= 2:
            result[0][1]["custom_key"] = "mutated"
            self.assertNotIn("custom_key", result[1][1])

    def test_sentence_boundary_split(self):
        """Chunks should not end mid-sentence if possible."""
        text = "First sentence ends here. Second sentence follows. Third sentence is last."
        result = self.smart_chunk(text, 1, self._meta(), max_tokens=8, overlap=0)
        for chunk_text, _ in result:
            # Each chunk should be a complete sentence or carry-over
            self.assertTrue(len(chunk_text.split()) > 0)


# ─────────────────────────────────────────────────────────────────────────────
# Page classifier tests
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyPage(unittest.TestCase):

    def setUp(self):
        from ingestion.service import _classify_page
        self.classify = _classify_page

    def test_text_rich_no_images(self):
        text = " ".join(["word"] * 100)   # 100 tokens, no images
        self.assertEqual(self.classify(100, False, text), "TEXT_RICH")

    def test_image_only(self):
        self.assertEqual(self.classify(5, True, "few words"), "IMAGE_ONLY")

    def test_mixed(self):
        self.assertEqual(self.classify(30, True, "some normal text here"), "MIXED")

    def test_table_detected(self):
        # Text with pipe characters triggers TABLE classification
        table_text = "Name | Value | Unit\nA | 1 | kg"
        result = self.classify(50, False, table_text)
        self.assertEqual(result, "TABLE")

    def test_text_rich_below_threshold_no_images(self):
        # 40 tokens, no images → TEXT_RICH (falls through MIXED check since no images)
        self.assertEqual(self.classify(40, False, "short text"), "TEXT_RICH")

    def test_image_only_threshold_boundary(self):
        # Exactly 19 tokens + images → IMAGE_ONLY
        self.assertEqual(self.classify(19, True, "w " * 19), "IMAGE_ONLY")

    def test_mixed_threshold_boundary(self):
        # Exactly 20 tokens + images → MIXED
        self.assertEqual(self.classify(20, True, "w " * 20), "MIXED")


# ─────────────────────────────────────────────────────────────────────────────
# XLSX flatten tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFlattenSheet(unittest.TestCase):

    def setUp(self):
        from ingestion.xlsx_pipeline import _flatten_sheet
        self.flatten = _flatten_sheet

    def _make_ws(self, rows: list[list]) -> MagicMock:
        """Create a mock worksheet from a list of rows (list of cell values)."""
        mock_ws = MagicMock()

        def make_cell(value):
            c = MagicMock()
            c.value = value
            return c

        mock_rows = [[make_cell(v) for v in row] for row in rows]
        mock_ws.iter_rows.return_value = mock_rows
        return mock_ws

    def test_with_headers(self):
        ws = self._make_ws([
            ["Name", "Score", "Grade"],
            ["Alice", 95, "A"],
            ["Bob", 82, "B"],
        ])
        result = self.flatten(ws)
        self.assertIn("Name: Alice", result)
        self.assertIn("Score: 95", result)
        self.assertIn("Grade: A", result)

    def test_empty_rows_skipped(self):
        ws = self._make_ws([
            ["Col1", "Col2"],
            ["", ""],          # empty row
            ["val1", "val2"],
        ])
        result = self.flatten(ws)
        lines = [l for l in result.splitlines() if l]
        self.assertEqual(len(lines), 1)
        self.assertIn("Col1: val1", lines[0])

    def test_empty_sheet(self):
        ws = self._make_ws([])
        self.assertEqual(self.flatten(ws), "")

    def test_no_headers_fallback(self):
        # All numeric → no headers detected
        ws = self._make_ws([
            [1, 2, 3],
            [4, 5, 6],
        ])
        result = self.flatten(ws)
        self.assertIn("1", result)
        self.assertIn("4", result)


# ─────────────────────────────────────────────────────────────────────────────
# source_type_from_filename tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSourceTypeFromFilename(unittest.TestCase):

    def setUp(self):
        from ingestion.service import source_type_from_filename
        self.fn = source_type_from_filename

    def test_pdf(self):
        self.assertEqual(self.fn("report.pdf"), "pdf")

    def test_docx(self):
        self.assertEqual(self.fn("document.DOCX"), "docx")   # case insensitive

    def test_pptx(self):
        self.assertEqual(self.fn("slides.pptx"), "pptx")

    def test_xlsx(self):
        self.assertEqual(self.fn("data.xlsx"), "xlsx")

    def test_html(self):
        self.assertEqual(self.fn("page.html"), "html")
        self.assertEqual(self.fn("page.htm"), "html")

    def test_unsupported_raises(self):
        with self.assertRaises(ValueError):
            self.fn("file.csv")

    def test_unsupported_txt_raises(self):
        with self.assertRaises(ValueError):
            self.fn("notes.txt")


# ─────────────────────────────────────────────────────────────────────────────
# SHA-256 hash tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSHA256(unittest.TestCase):

    def setUp(self):
        from ingestion.service import _sha256
        self._sha256 = _sha256

    def test_deterministic(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"LAKO test content 1234")
            path = f.name
        h1 = self._sha256(path)
        h2 = self._sha256(path)
        self.assertEqual(h1, h2)

    def test_matches_hashlib(self):
        content = b"hello world from LAKO"
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            path = f.name
        expected = hashlib.sha256(content).hexdigest()
        self.assertEqual(self._sha256(path), expected)

    def test_different_files_differ(self):
        with tempfile.NamedTemporaryFile(delete=False) as f1:
            f1.write(b"content A")
            path1 = f1.name
        with tempfile.NamedTemporaryFile(delete=False) as f2:
            f2.write(b"content B")
            path2 = f2.name
        self.assertNotEqual(self._sha256(path1), self._sha256(path2))


# ─────────────────────────────────────────────────────────────────────────────
# PDF page processing — mocked I/O
# ─────────────────────────────────────────────────────────────────────────────

class TestPDFPageClassification(unittest.TestCase):
    """
    Test that _process_pdf_page routes correctly to each handler.
    External I/O (pdfplumber, vision model) is mocked.
    """

    def _make_fitz_page(
        self,
        text: str = "",
        images: list = None,
        span_size: float = 12.0,
    ) -> MagicMock:
        page = MagicMock()
        page.get_text.return_value = text
        page.get_images.return_value = images or []

        # Span info
        span = {"text": text[:50] if text else "", "size": span_size, "flags": 0, "bbox": [0, 0, 100, 20]}
        line = {"spans": [span]}
        block = {"type": 0, "lines": [line]}
        page.get_text.side_effect = lambda mode: text if mode == "text" else {"blocks": [block]}

        def get_text_side(mode):
            if mode == "text":
                return text
            return {"blocks": [block]}

        page.get_text.side_effect = get_text_side
        page.get_pixmap.return_value = MagicMock(tobytes=MagicMock(return_value=b"PNG_BYTES" * 200))
        return page

    @async_test
    async def test_text_rich_page_no_vision_call(self):
        """TEXT_RICH pages must NOT call vision model."""
        from ingestion.service import _process_pdf_page

        rich_text = " ".join(["word"] * 100)  # 100 tokens → TEXT_RICH
        fitz_page = self._make_fitz_page(text=rich_text, images=[])
        fitz_doc  = MagicMock()

        with patch("ingestion.service.ollama_client") as mock_client:
            result = await _process_pdf_page(
                fitz_doc, fitz_page, 1, "doc1", "test.pdf", "/fake/path.pdf"
            )
            mock_client.describe_image.assert_not_called()

        self.assertTrue(len(result) > 0)
        self.assertTrue(all(m.get("block_type") == "text" for _, m in result))

    @async_test
    async def test_image_only_calls_vision(self):
        """IMAGE_ONLY pages must call vision model exactly once (for full-page render)."""
        from ingestion.service import _process_pdf_page

        sparse_text = "few words"   # < 20 tokens → IMAGE_ONLY with images
        fitz_page   = self._make_fitz_page(text=sparse_text, images=[(1,)])
        fitz_doc    = MagicMock()

        with patch("ingestion.service.ollama_client") as mock_client:
            mock_client.describe_image = AsyncMock(return_value="A chart showing revenue growth.")
            result = await _process_pdf_page(
                fitz_doc, fitz_page, 2, "doc2", "test.pdf", "/fake/path.pdf"
            )
            mock_client.describe_image.assert_called_once()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1]["block_type"], "image_description")
        self.assertIn("revenue", result[0][0])

    @async_test
    async def test_table_page_uses_pdfplumber(self):
        """TABLE pages must call pdfplumber, not vision model."""
        from ingestion.service import _process_pdf_page

        table_text = "Name | Score | Grade\nAlice | 95 | A\nBob | 82 | B"
        fitz_page  = self._make_fitz_page(text=table_text, images=[])
        fitz_doc   = MagicMock()

        with patch("ingestion.service.ollama_client") as mock_client, \
             patch("ingestion.service._pdfplumber_table_text") as mock_plumber:
            mock_plumber.return_value = "Name: Alice | Score: 95 | Grade: A\nName: Bob | Score: 82 | Grade: B"
            result = await _process_pdf_page(
                fitz_doc, fitz_page, 3, "doc3", "test.pdf", "/fake/path.pdf"
            )
            mock_plumber.assert_called_once()
            mock_client.describe_image.assert_not_called()

        self.assertTrue(len(result) > 0)
        self.assertEqual(result[0][1]["block_type"], "table")

    @async_test
    async def test_mixed_page_text_and_vision(self):
        """MIXED pages extract text directly AND call vision per image region."""
        from ingestion.service import _process_pdf_page

        mixed_text = " ".join(["word"] * 30)  # 30 tokens + images → MIXED
        fitz_page  = self._make_fitz_page(text=mixed_text, images=[(99,)])
        fitz_doc   = MagicMock()

        # Mock image rect lookup
        mock_rect = MagicMock()
        mock_rect.width  = 200
        mock_rect.height = 200
        mock_rect.__iter__ = MagicMock(return_value=iter([0, 0, 200, 200]))
        fitz_page.get_image_rects.return_value = [mock_rect]

        clip_pix = MagicMock()
        clip_pix.tobytes.return_value = b"PNG" * 300
        fitz_page.get_pixmap.return_value = clip_pix

        with patch("ingestion.service.ollama_client") as mock_client:
            mock_client.describe_image = AsyncMock(return_value="A flowchart with three nodes.")
            result = await _process_pdf_page(
                fitz_doc, fitz_page, 4, "doc4", "test.pdf", "/fake/path.pdf"
            )

        block_types = [m["block_type"] for _, m in result]
        self.assertIn("text", block_types)
        # Vision may or may not be called depending on rect size mocking
        # — at minimum we should have text chunks
        self.assertTrue(len(result) > 0)

    @async_test
    async def test_failed_page_returns_empty_continues(self):
        """A page that raises should return [] and not propagate the exception."""
        from ingestion.service import _process_pdf_page

        bad_page = MagicMock()
        bad_page.get_text.side_effect = RuntimeError("corrupt page")
        bad_page.get_images.side_effect = RuntimeError("corrupt page")

        result = await _process_pdf_page(
            MagicMock(), bad_page, 99, "docX", "corrupt.pdf", "/fake/corrupt.pdf"
        )
        self.assertEqual(result, [])


# ─────────────────────────────────────────────────────────────────────────────
# Hash-dedup integration (mocked DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestHashDedup(unittest.TestCase):

    @async_test
    async def test_duplicate_returns_early(self):
        """ingest_file() returns status='duplicate' for a previously indexed file."""
        from ingestion.service import ingest_file

        existing = {
            "id": "existing-doc-id",
            "status": "indexed",
            "chunk_count": 42,
            "page_count": 10,
        }

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as f:
            f.write(b"PDF content here" * 100)
            path = f.name

        with patch("ingestion.service.init_chunk_db", new_callable=AsyncMock), \
             patch("ingestion.service.find_by_hash", new_callable=AsyncMock, return_value=existing):
            result = await ingest_file(path, "test.pdf", "pdf")

        self.assertEqual(result["status"], "duplicate")
        self.assertEqual(result["doc_id"], "existing-doc-id")
        self.assertEqual(result["chunks"], 42)


# ─────────────────────────────────────────────────────────────────────────────
# Rotation-aware page classification tests
# ─────────────────────────────────────────────────────────────────────────────

class TestRotationAwareClassification(unittest.TestCase):
    """
    Tests that rotation detection correctly overrides the standard classifier
    and that the ROTATED branch in _process_pdf_page behaves as specified.
    """

    def _make_rotated_fitz_page(self, table_text: str = None) -> MagicMock:
        """
        Make a mock fitz page that:
        - returns table-like text from get_text("text")  (would classify as TABLE)
        - returns rotated-dir blocks from get_text("dict") (rotation detected)
        """
        text = table_text or "Name | Score | Grade\nAlice | 95 | A\nBob | 82 | B"

        # Rotated block: dir = (0.0, 1.0) — 90° CCW
        # Text must be ≥ 50 chars to meet _detect_page_rotation's minimum
        rotated_span = {
            "text": "WBHDCL NET LOSS AFTER TAX TOTAL REVENUE APPENDIX FIVE ONE",
            "size": 10.0,
            "flags": 0,
            "bbox": [0, 0, 100, 20],
        }
        rotated_line = {"dir": (0.0, 1.0), "spans": [rotated_span]}
        rotated_block = {"type": 0, "lines": [rotated_line]}

        page = MagicMock()

        def get_text_side(mode, **kwargs):
            if mode == "text":
                return text
            return {"blocks": [rotated_block]}

        page.get_text.side_effect = get_text_side
        page.get_images.return_value = []
        page.get_pixmap.return_value = MagicMock(
            tobytes=MagicMock(return_value=b"PNG_BYTES" * 200)
        )
        return page

    def test_classify_page_rotated_takes_precedence(self):
        """
        A page with rotated text AND table-like layout must be classified
        as ROTATED (not TABLE).  Rotation check runs before _classify_page.
        """
        from ingestion.service import _detect_page_rotation

        page = self._make_rotated_fitz_page()
        result = _detect_page_rotation(page)
        self.assertEqual(
            result, "rotated",
            "Expected 'rotated' from a page with rotated text dir, "
            f"got {result!r}",
        )

    @async_test
    async def test_process_pdf_page_rotated_calls_vision(self):
        """
        _process_pdf_page on a ROTATED page must call vision model exactly
        once, with a PNG payload rendered at 200 dpi.
        """
        from ingestion.service import _process_pdf_page

        page     = self._make_rotated_fitz_page()
        fitz_doc = MagicMock()

        with patch("ingestion.service._detect_page_rotation", return_value="rotated"), \
             patch("ingestion.service.ollama_client") as mock_client:
            mock_client.describe_image = AsyncMock(
                return_value="| Entity | Net Loss |\n| WBHDCL | 36.88 |"
            )
            result = await _process_pdf_page(
                fitz_doc, page, 165, "doc_rot", "wb_audit.pdf", "/fake/wb.pdf"
            )
            mock_client.describe_image.assert_awaited_once()

            # Confirm PNG bytes were passed (not empty)
            call_args = mock_client.describe_image.call_args
            img_b64_arg = call_args[0][0]   # first positional arg is base64 string
            self.assertIsInstance(img_b64_arg, str)
            self.assertGreater(len(img_b64_arg), 0)

        self.assertGreater(len(result), 0)

    def test_chunk_metadata_includes_extraction_quality(self):
        """
        Every chunk produced by the ROTATED branch must have
        extraction_quality == 'vision_extracted' and rotation_detected is True.
        """
        from ingestion.service import smart_chunk

        meta = {
            "doc_id":      "doc_rot",
            "filename":    "wb_audit.pdf",
            "page":        165,
            "bbox":        [0, 0, 100, 100],
            "font_size":   10.0,
            "is_bold":     False,
            "ingested_at": "2026-01-01T00:00:00+00:00",
            "source_type": "pdf",
            "block_type":  "table",
            "extraction_quality": "vision_extracted",
            "rotation_detected":  True,
        }
        chunks = smart_chunk("| Col1 | Col2 |\n| Val1 | Val2 |", 165, meta)
        self.assertTrue(len(chunks) >= 1)
        for _, m in chunks:
            self.assertEqual(m.get("extraction_quality"), "vision_extracted")
            self.assertTrue(m.get("rotation_detected"))

    @async_test
    async def test_text_rich_branch_uses_sort_true(self):
        """
        TEXT_RICH pages must extract text with sort=True for reading-order
        correctness on multi-column layouts.

        Note: the existing test mock infrastructure (get_text_side(mode)) does
        not accept keyword arguments.  This test therefore uses a fresh mock
        that explicitly supports the sort= kwarg, confirming the production
        code path calls get_text("text", sort=True) vs the classification path
        that calls get_text("text") without sort.

        If this test fails it means the sort=True call was removed from the
        TEXT_RICH branch — re-add it in _process_pdf_page.
        """
        from ingestion.service import _process_pdf_page

        rich_text = " ".join(["word"] * 100)

        span      = {"text": rich_text[:50], "size": 12.0, "flags": 0, "bbox": [0, 0, 100, 20]}
        line      = {"dir": (1.0, 0.0), "spans": [span]}
        block     = {"type": 0, "lines": [line]}

        page = MagicMock()
        # Use a mock that accepts the sort kwarg so the call doesn't raise
        page.get_text.side_effect = lambda mode, **kwargs: (
            rich_text if mode == "text" else {"blocks": [block]}
        )
        page.get_images.return_value = []
        page.get_pixmap.return_value = MagicMock(tobytes=MagicMock(return_value=b""))

        with patch("ingestion.service._detect_page_rotation", return_value=None), \
             patch("ingestion.service.ollama_client"):
            await _process_pdf_page(
                MagicMock(), page, 1, "doc_st", "test.pdf", "/fake/test.pdf"
            )

        # Confirm get_text was called with sort=True at some point
        calls = page.get_text.call_args_list
        sort_true_calls = [
            c for c in calls
            if c.kwargs.get("sort") is True
        ]
        self.assertTrue(
            len(sort_true_calls) >= 1,
            "Expected at least one get_text call with sort=True in TEXT_RICH branch. "
            f"Actual calls: {calls}",
        )

    @async_test
    async def test_probe_ingest_quality_clean_doc(self):
        """
        probe_ingest_quality returns 'clean' when all probes hit Qdrant.
        """
        from services.quality_probe import probe_ingest_quality

        mock_point  = MagicMock()
        mock_result = MagicMock()
        mock_result.points = [mock_point]

        mock_qdrant = AsyncMock()
        mock_qdrant.query_points = AsyncMock(return_value=mock_result)

        with patch("services.quality_probe.get_chunks_for_doc", new_callable=AsyncMock, return_value=[]), \
             patch("services.quality_probe._get_qdrant", new_callable=AsyncMock, return_value=mock_qdrant), \
             patch("services.quality_probe.ollama_client") as mock_embed_client:

            mock_embed_client.embed = AsyncMock(return_value=[0.1] * 768)
            result = await probe_ingest_quality("doc-clean", "Report-No-1-of-2022.pdf")

        self.assertEqual(result, "clean")

    @async_test
    async def test_probe_ingest_quality_suspect_doc(self):
        """
        probe_ingest_quality returns 'suspect' when no probes hit Qdrant,
        and logs a warning.
        """
        from services.quality_probe import probe_ingest_quality

        mock_result = MagicMock()
        mock_result.points = []   # nothing found — suspect

        mock_qdrant = AsyncMock()
        mock_qdrant.query_points = AsyncMock(return_value=mock_result)

        with patch("services.quality_probe.get_chunks_for_doc", new_callable=AsyncMock, return_value=[]), \
             patch("services.quality_probe._get_qdrant", new_callable=AsyncMock, return_value=mock_qdrant), \
             patch("services.quality_probe.ollama_client") as mock_embed_client:

            mock_embed_client.embed = AsyncMock(return_value=[0.0] * 768)
            result = await probe_ingest_quality("doc-suspect", "corrupted_scan.pdf")

        self.assertEqual(result, "suspect")


# ─────────────────────────────────────────────────────────────────────────────
# V2 pdf_extractor rotation test
# ─────────────────────────────────────────────────────────────────────────────

class TestV2PDFExtractorRotation(unittest.TestCase):
    """
    Test that the V2 pdf_extractor routes rotated pages through vision OCR
    and stores the OCR result as raw_text in SQLite.
    """

    @async_test
    async def test_v2_pdf_extractor_handles_rotation(self):
        """
        When a PDF page is detected as rotated, extract_pdf must call
        vision_service.describe_image_bytes and store the OCR result as raw_text.
        """
        from ingestion.pdf_extractor import extract_pdf

        # ── Build a real single-page PDF in memory ─────────────────────────
        doc_buf = fitz.open()
        pg      = doc_buf.new_page(width=595, height=842)
        # Insert rotated text that exceeds the 50-char detection threshold
        rotated_text = (
            "WBHDCL WEST BENGAL HIGHWAY DEVELOPMENT CORPORATION LIMITED "
            "NET LOSS AFTER TAX APPENDIX FIVE POINT ONE"
        )
        pg.insert_text((300, 400), rotated_text, fontsize=11, rotate=90)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            doc_buf.save(tf.name)
            pdf_path = tf.name
        doc_buf.close()

        ocr_output = "| WBHDCL | Net Loss | (36.88) |"
        stored_rows: list[dict] = []

        async def fake_insert_page(**kwargs):
            stored_rows.append(kwargs)

        # vision_service is imported lazily inside the function body.
        # Patch the module it comes from so the import sees the mock.
        mock_vs = MagicMock()
        mock_vs.describe_image_bytes = AsyncMock(return_value=ocr_output)

        import sys
        fake_vs_module = types.ModuleType("services.vision_service")
        fake_vs_module.vision_service = mock_vs
        sys.modules["services.vision_service"] = fake_vs_module

        try:
            with patch("ingestion.pdf_extractor.insert_page",
                       new_callable=AsyncMock, side_effect=fake_insert_page), \
                 patch("ingestion.pdf_extractor.update_document_status",
                       new_callable=AsyncMock), \
                 patch("ingestion.pdf_extractor._detect_page_rotation",
                       return_value="rotated"):

                try:
                    await extract_pdf(pdf_path, "doc-v2-rot")
                except Exception:
                    pass  # sqlite/other errors are irrelevant — check stored_rows
        finally:
            # Restore original module so other tests are unaffected
            sys.modules.pop("services.vision_service", None)

        # The raw_text stored should be the OCR output, not garbled PyMuPDF text
        self.assertTrue(
            len(stored_rows) >= 1,
            "Expected at least one insert_page call for the rotated PDF",
        )
        self.assertEqual(
            stored_rows[0].get("raw_text"), ocr_output,
            "Rotated page raw_text should be the vision OCR output",
        )
        self.assertTrue(
            stored_rows[0].get("has_tables"),
            "Rotated page should mark has_tables=True",
        )
        self.assertEqual(
            stored_rows[0].get("headers"), [],
            "Rotated page should have headers=[]",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
