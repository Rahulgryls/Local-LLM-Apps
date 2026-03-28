"""
LAKO — Embedder Service
Converts text into vector embeddings via nomic-embed-text through Ollama.
Session 1: Stub — wired in Session 4.
"""

from typing import List
from services.ollama_client import ollama_client


class Embedder:
    """Generates text embeddings using the configured embedding model."""

    async def embed_text(self, text: str) -> List[float]:
        """
        Embed a single piece of text.
        Returns a float vector.
        TODO (Session 4): call ollama_client.embed(text)
        """
        raise NotImplementedError("Embedder.embed_text() — Session 4")

    async def embed_chunks(self, chunks: List[str]) -> List[List[float]]:
        """
        Embed a list of text chunks in sequence.
        Returns a list of float vectors.
        TODO (Session 4): iterate embed_text() over all chunks.
        """
        raise NotImplementedError("Embedder.embed_chunks() — Session 4")

    async def embed_query(self, query: str) -> List[float]:
        """
        Embed a user query for similarity search.
        Alias for embed_text — kept separate for clarity.
        TODO (Session 4): call ollama_client.embed(query)
        """
        raise NotImplementedError("Embedder.embed_query() — Session 4")


# Singleton instance
embedder = Embedder()
