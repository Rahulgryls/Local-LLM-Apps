"""
LAKO — ChromaDB Client Service
Local vector database — no Docker required.
Stores and retrieves embedded document chunks.
Session 1: Stub — wired in Session 4.
"""

from typing import List, Optional
from config import get_config

COLLECTION_NAME = "lako_knowledge_base"


class ChromaClient:
    """Client for the local ChromaDB vector store."""

    def __init__(self):
        config = get_config()
        self.path = config["chromadb_path"]
        self._client = None
        self._collection = None

    def _get_client(self):
        """Lazy-load ChromaDB client."""
        if self._client is None:
            # TODO (Session 4): initialize chromadb.PersistentClient(path=self.path)
            raise NotImplementedError("ChromaClient._get_client() — Session 4")
        return self._client

    def get_collection(self):
        """Get or create the LAKO knowledge base collection."""
        # TODO (Session 4): implement
        raise NotImplementedError("ChromaClient.get_collection() — Session 4")

    def add_chunks(self, chunks: List[dict]) -> None:
        """
        Add embedded document chunks to ChromaDB.
        Each chunk: {id, embedding, document, metadata}
        metadata: {filename, page, chunk_type, timestamp}
        TODO (Session 4): implement.
        """
        raise NotImplementedError("ChromaClient.add_chunks() — Session 4")

    def similarity_search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        threshold: float = 0.7,
    ) -> List[dict]:
        """
        Query ChromaDB for most similar chunks to the query embedding.
        Returns list of {document, metadata, score} dicts.
        TODO (Session 4): implement.
        """
        raise NotImplementedError("ChromaClient.similarity_search() — Session 4")

    def get_stats(self) -> dict:
        """
        Return collection stats: chunk count, collection name, path.
        Used by GET /api/vector/status.
        TODO (Session 4): implement.
        """
        return {
            "status": "stub",
            "collection": COLLECTION_NAME,
            "total_chunks": 0,
            "path": self.path,
        }

    def clear_collection(self) -> None:
        """Delete all chunks from the collection. Use with caution."""
        raise NotImplementedError("ChromaClient.clear_collection() — Session 4")


# Singleton instance
chroma_client = ChromaClient()
