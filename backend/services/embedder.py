"""
LAKO — Embedder Service
Converts text into vector embeddings via nomic-embed-text through Ollama.
Session 4: Fully implemented.
"""

from typing import List
from services.ollama_client import ollama_client


class Embedder:
    """Generates text embeddings using the configured embedding model."""

    async def embed_text(self, text: str) -> List[float]:
        """
        Embed a single piece of text.
        Returns a float vector (768 dims for nomic-embed-text).
        """
        return await ollama_client.embed(text)

    async def embed_chunks(self, chunks: List[str]) -> List[List[float]]:
        """
        Embed a list of text chunks using batch embedding.
        Returns a list of float vectors, one per chunk.
        Uses ollama_client.embed_batch() for efficiency.
        """
        if not chunks:
            return []
        return await ollama_client.embed_batch(chunks)

    async def embed_query(self, query: str) -> List[float]:
        """
        Embed a user query for similarity search.
        Functionally identical to embed_text — kept separate so RAG code
        is explicit about whether it is embedding a document or a query.
        """
        return await ollama_client.embed(query)


# Singleton instance
embedder = Embedder()
