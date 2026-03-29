"""
LAKO — Chunker Service
Splits extracted document text into overlapping chunks for embedding.
Chunk size: ~450 chars, overlap: ~75 chars.
Chunk types: text / table / image-caption
Session 4: chunk_text, chunk_table, chunk_image_caption, chunk_document implemented.
"""

from typing import List
from dataclasses import dataclass


@dataclass
class Chunk:
    content: str
    chunk_type: str       # text / table / image-caption
    page: int
    filename: str
    char_start: int = 0
    char_end: int = 0


class Chunker:
    """
    Splits document content into overlapping semantic chunks.
    Preserves chunk_type metadata so RAG can cite source format.
    """

    def __init__(
        self,
        chunk_size: int = 900,   # target characters per chunk (~180 words)
        overlap: int = 180,      # character overlap — 20% of chunk size
    ):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_text(self, text: str, filename: str, page: int = 0) -> List[Chunk]:
        """
        Split plain text into overlapping chunks using a sliding window.
        Tries to break at sentence or paragraph boundaries to avoid
        cutting mid-sentence.
        """
        text = text.strip()
        if not text:
            return []

        chunks: List[Chunk] = []
        start = 0

        while start < len(text):
            end = min(start + self.chunk_size, len(text))

            # If not at the end of the text, try to break cleanly
            if end < len(text):
                # Prefer paragraph break, then sentence-ending punctuation
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

            # Advance start by (chunk_size - overlap), but never go backwards
            next_start = end - self.overlap
            if next_start <= start:
                next_start = start + max(1, self.chunk_size // 2)
            start = next_start

        return chunks

    def chunk_table(self, table_text: str, filename: str, page: int = 0) -> List[Chunk]:
        """
        Wrap table content as a single chunk — tables are not split mid-row
        because that would break the meaning of the data.
        If the table is very long, it is still kept as one chunk so that
        row context is preserved for the LLM.
        """
        table_text = table_text.strip()
        if not table_text:
            return []
        return [Chunk(
            content=table_text,
            chunk_type="table",
            page=page,
            filename=filename,
            char_start=0,
            char_end=len(table_text),
        )]

    def chunk_image_caption(self, caption: str, filename: str, page: int = 0) -> Chunk:
        """
        Wrap an image or diagram description (from llava vision model) as a
        single image-caption chunk. Called by vision_service in Session 7.
        """
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
        Master chunking function.
        Routes each content type from the extracted document dict to the
        correct chunk_ method and returns all chunks combined.

        Expected extracted dict structure:
        {
            "filename": str,
            "text_blocks": [{"text": str, "page": int}, ...],
            "tables":      [{"text": str, "page": int}, ...],
            "images":      [{"caption": str, "page": int}, ...],
        }

        image-captions are produced by vision_service (Session 7).
        """
        filename = extracted.get("filename", "unknown")
        all_chunks: List[Chunk] = []

        for block in extracted.get("text_blocks", []):
            all_chunks.extend(
                self.chunk_text(block["text"], filename, block.get("page", 0))
            )

        for table in extracted.get("tables", []):
            all_chunks.extend(
                self.chunk_table(table["text"], filename, table.get("page", 0))
            )

        for image in extracted.get("images", []):
            caption = image.get("caption", "")
            if caption:
                all_chunks.append(
                    self.chunk_image_caption(caption, filename, image.get("page", 0))
                )

        return all_chunks


# Singleton instance
chunker = Chunker()
