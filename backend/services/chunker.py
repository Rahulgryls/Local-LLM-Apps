"""
LAKO — Chunker Service
Splits extracted document text into overlapping chunks for embedding.
Chunk size: ~900 chars, overlap: ~180 chars.
Chunk types: text / table / mixed / image-caption
Session 4:  chunk_text, chunk_table, chunk_image_caption, chunk_document.
Session 15: chunk_inline (prose + embedded markdown tables).
            Header-prepend for oversized tables — no orphaned data rows.
            has_table flag + table_summary field for metadata enrichment.
Session 17: significance_marker field on Chunk — propagated from ParsedPage
            (pdf_parser significance detection) through chunk_document so
            ChromaDB metadata carries the marker for LLM reasoning checks.
"""

import re
from typing import List, Optional
from dataclasses import dataclass, field


@dataclass
class Chunk:
    content: str
    chunk_type: str        # text / table / mixed / image-caption
    page: int
    filename: str
    char_start: int = 0
    char_end: int = 0
    has_table: bool = False
    table_summary: str = ""        # filled by ingest.py after LLM summary generation
    significance_marker: str = ""  # significance chars found in table cells (e.g. "*†")


class Chunker:
    """
    Splits document content into overlapping semantic chunks.
    Preserves chunk_type metadata so RAG can cite source format.

    chunk_inline() is the primary path for PDF / DOCX / PPTX — it handles
    mixed prose + markdown-table content and never splits a table mid-body.
    chunk_table() is the primary path for XLSX sheets.
    chunk_text() handles plain TXT and any prose-only blocks.
    """

    def __init__(
        self,
        chunk_size: int = 900,   # target characters per chunk (~180 words)
        overlap: int = 180,      # character overlap — 20% of chunk_size
    ):
        self.chunk_size = chunk_size
        self.overlap = overlap

    # ══════════════════════════════════════════════════════════════════════════
    # Public chunking methods
    # ══════════════════════════════════════════════════════════════════════════

    def chunk_text(self, text: str, filename: str, page: int = 0) -> List[Chunk]:
        """
        Split plain text into overlapping chunks using a sliding window.
        Tries to break at sentence or paragraph boundaries.
        """
        text = text.strip()
        if not text:
            return []

        chunks: List[Chunk] = []
        start = 0

        while start < len(text):
            end = min(start + self.chunk_size, len(text))

            if end < len(text):
                for sep in ["\n\n", ".\n", ". ", "? ", "! ", "\n"]:
                    pos = text.rfind(sep, start + self.overlap, end)
                    if pos != -1:
                        end = pos + len(sep)
                        break

            content = text[start:end].strip()
            if content:
                chunks.append(Chunk(
                    content=content,
                    chunk_type="text",
                    page=page,
                    filename=filename,
                    char_start=start,
                    char_end=end,
                ))

            next_start = end - self.overlap
            if next_start <= start:
                next_start = start + max(1, self.chunk_size // 2)
            start = next_start

        return chunks

    def chunk_table(self, table_text: str, filename: str, page: int = 0) -> List[Chunk]:
        """
        Chunk a markdown or pipe-separated table.

        - Fits within chunk_size  → single chunk, intact.
        - Exceeds chunk_size      → split by row groups with the header row
          prepended to every sub-chunk so no chunk has orphaned data rows.
        """
        table_text = table_text.strip()
        if not table_text:
            return []

        if len(table_text) <= self.chunk_size:
            return [Chunk(
                content=table_text,
                chunk_type="table",
                page=page,
                filename=filename,
                has_table=True,
                char_start=0,
                char_end=len(table_text),
            )]

        # Oversized — split by rows, prepend header to each sub-chunk
        lines = table_text.split("\n")
        header_lines, data_lines = self._split_table_header(lines)
        header_text = "\n".join(header_lines)

        chunks: List[Chunk] = []
        current_rows: List[str] = []
        current_size = len(header_text) + 1  # +1 for separator newline

        for row in data_lines:
            row_size = len(row) + 1
            if current_size + row_size > self.chunk_size and current_rows:
                content = header_text + "\n" + "\n".join(current_rows)
                chunks.append(Chunk(
                    content=content,
                    chunk_type="table",
                    page=page,
                    filename=filename,
                    has_table=True,
                ))
                current_rows = [row]
                current_size = len(header_text) + 1 + row_size
            else:
                current_rows.append(row)
                current_size += row_size

        if current_rows:
            content = header_text + "\n" + "\n".join(current_rows)
            chunks.append(Chunk(
                content=content,
                chunk_type="table",
                page=page,
                filename=filename,
                has_table=True,
            ))

        return chunks

    def chunk_inline(self, text: str, filename: str, page: int = 0) -> List[Chunk]:
        """
        Chunk mixed content where markdown tables are embedded inline with prose.

        Strategy:
          - Segment the text into alternating prose and table blocks.
          - The last prose paragraph before a table is kept in the same chunk
            as the table (contextual proximity).
          - Tables are never split mid-body.
          - Oversized tables use header-prepend splitting (see chunk_table).
        """
        text = text.strip()
        if not text:
            return []

        segments = self._split_prose_and_tables(text)
        chunks: List[Chunk] = []
        prose_buffer = ""

        for seg_type, seg_content in segments:
            if seg_type == "prose":
                prose_buffer += ("\n\n" if prose_buffer else "") + seg_content

                # Flush early if prose buffer is growing very large,
                # but retain the last paragraph as context for the next table.
                if len(prose_buffer) > self.chunk_size * 1.5:
                    paras = prose_buffer.rsplit("\n\n", 1)
                    if len(paras) == 2:
                        chunks.extend(self.chunk_text(paras[0], filename, page))
                        prose_buffer = paras[1]
                    else:
                        chunks.extend(self.chunk_text(prose_buffer, filename, page))
                        prose_buffer = ""

            else:  # table segment
                # Grab the last paragraph of prose as context prefix for this table
                if prose_buffer.strip():
                    paras = prose_buffer.rsplit("\n\n", 1)
                    if len(paras) == 2 and paras[0].strip():
                        chunks.extend(self.chunk_text(paras[0], filename, page))
                        context_prefix = paras[1].strip()
                    else:
                        context_prefix = prose_buffer.strip()
                    prose_buffer = ""
                else:
                    context_prefix = ""

                combined = (
                    (context_prefix + "\n\n" + seg_content).strip()
                    if context_prefix
                    else seg_content
                )

                if len(combined) <= self.chunk_size:
                    chunk_type = "mixed" if context_prefix else "table"
                    chunks.append(Chunk(
                        content=combined,
                        chunk_type=chunk_type,
                        page=page,
                        filename=filename,
                        has_table=True,
                    ))
                else:
                    # Too large to combine — context prefix gets its own chunk,
                    # table uses header-prepend splitting.
                    if context_prefix:
                        chunks.append(Chunk(
                            content=context_prefix,
                            chunk_type="text",
                            page=page,
                            filename=filename,
                        ))
                    chunks.extend(self.chunk_table(seg_content, filename, page))

        # Flush any remaining prose
        if prose_buffer.strip():
            chunks.extend(self.chunk_text(prose_buffer, filename, page))

        return chunks

    def chunk_image_caption(self, caption: str, filename: str, page: int = 0) -> Chunk:
        """Wrap an image/diagram description as a single image-caption chunk."""
        caption = caption.strip()
        return Chunk(
            content=caption,
            chunk_type="image-caption",
            page=page,
            filename=filename,
            char_start=0,
            char_end=len(caption),
        )

    def chunk_document(self, extracted: dict) -> List[Chunk]:
        """
        Master chunking function. Routes each content type to the correct method.

        Expected extracted dict structure:
        {
            "filename":      str,
            "inline_blocks": [{"text": str, "page": int}, ...],  # prose + inline tables (PDF/DOCX/PPTX)
            "text_blocks":   [{"text": str, "page": int}, ...],  # plain prose only (TXT, legacy)
            "tables":        [{"text": str, "page": int}, ...],  # standalone tables (XLSX)
            "images":        [{"caption": str, "page": int}, ...],
        }
        """
        filename = extracted.get("filename", "unknown")
        all_chunks: List[Chunk] = []

        # Inline blocks — prose with embedded markdown tables (PDF, DOCX, PPTX)
        for block in extracted.get("inline_blocks", []):
            sig = block.get("significance_markers", "")
            block_chunks = self.chunk_inline(block["text"], filename, block.get("page", 0))
            if sig:
                for c in block_chunks:
                    c.significance_marker = sig
            all_chunks.extend(block_chunks)

        # Plain text blocks — TXT files and legacy fallback paths
        for block in extracted.get("text_blocks", []):
            all_chunks.extend(
                self.chunk_text(block["text"], filename, block.get("page", 0))
            )

        # Standalone table blocks — XLSX sheets
        for table in extracted.get("tables", []):
            all_chunks.extend(
                self.chunk_table(table["text"], filename, table.get("page", 0))
            )

        # Image captions from vision model
        for image in extracted.get("images", []):
            caption = image.get("caption", "")
            if caption:
                all_chunks.append(
                    self.chunk_image_caption(caption, filename, image.get("page", 0))
                )

        return all_chunks

    # ══════════════════════════════════════════════════════════════════════════
    # Private helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _split_prose_and_tables(self, text: str) -> List[tuple]:
        """
        Split text into alternating ("prose", content) and ("table", content) segments.
        A table block is a contiguous group of lines where each line starts with '|'.
        """
        lines = text.split("\n")
        segments: List[tuple] = []
        current_type: Optional[str] = None
        current_lines: List[str] = []

        for line in lines:
            line_type = "table" if line.strip().startswith("|") else "prose"

            if line_type != current_type:
                if current_lines and current_type is not None:
                    content = "\n".join(current_lines).strip()
                    if content:
                        segments.append((current_type, content))
                current_type = line_type
                current_lines = [line]
            else:
                current_lines.append(line)

        if current_lines and current_type is not None:
            content = "\n".join(current_lines).strip()
            if content:
                segments.append((current_type, content))

        return segments

    def _split_table_header(self, lines: List[str]) -> tuple:
        """
        Split table lines into (header_lines, data_lines).

        Markdown tables:   header row + separator row (---|---) → header = first 2 lines.
        Pipe-separated:    first line is the header → header = first 1 line.
        """
        if len(lines) < 2:
            return lines, []

        # Markdown separator row: contains only |, -, :, spaces
        if re.match(r"^\|?[\s\-:|]+\|", lines[1]):
            return lines[:2], lines[2:]

        return lines[:1], lines[1:]


# Singleton instance
chunker = Chunker()
