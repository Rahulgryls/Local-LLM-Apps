"""
LAKO — Chunker Service
Splits extracted document text into semantic chunks for embedding.
Chunk size: 300–600 tokens, overlap: 50–100 tokens.
Chunk types: text / table / diagram / image-caption
Session 1: Stub — wired in Session 4.
"""

from typing import List
from dataclasses import dataclass


@dataclass
class Chunk:
    content: str
    chunk_type: str       # text / table / diagram / image-caption
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
        chunk_size: int = 450,    # target tokens per chunk
        overlap: int = 75,         # token overlap between chunks
    ):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_text(self, text: str, filename: str, page: int = 0) -> List[Chunk]:
        """
        Split plain text into overlapping chunks.
        Approximate token count: 1 token ≈ 4 characters.
        TODO (Session 4): implement sliding window chunking.
        """
        raise NotImplementedError("Chunker.chunk_text() — Session 4")

    def chunk_table(self, table_text: str, filename: str, page: int = 0) -> List[Chunk]:
        """
        Wrap table content as a single table chunk (tables not split mid-row).
        TODO (Session 4): implement.
        """
        raise NotImplementedError("Chunker.chunk_table() — Session 4")

    def chunk_image_caption(self, caption: str, filename: str, page: int = 0) -> Chunk:
        """
        Wrap an image/diagram description as a single image-caption chunk.
        TODO (Session 7): implement (called after vision_service describes image).
        """
        raise NotImplementedError("Chunker.chunk_image_caption() — Session 7")

    def chunk_document(self, extracted: dict) -> List[Chunk]:
        """
        Master chunking function — takes full extracted document dict and
        routes each element to the correct chunk_ method.
        extracted = {text_blocks, tables, images, filename}
        TODO (Session 5): implement.
        """
        raise NotImplementedError("Chunker.chunk_document() — Session 5")


# Singleton instance
chunker = Chunker()
