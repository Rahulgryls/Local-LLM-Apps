"""
LAKO — ChromaDB Client Service
Local vector database — no Docker required.
Stores and retrieves embedded document chunks with metadata.
Session 4: Fully implemented.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import chromadb
from chromadb.config import Settings as ChromaSettings

from config import get_config

COLLECTION_NAME = "lako_knowledge_base"


def _resolve_path(config_path: str) -> Path:
    """
    Resolve the chromadb_path from config.json.
    On the bank server, /lako/storage/chromadb is a real absolute path.
    On a dev machine where the project lives elsewhere, the config stores
    the actual absolute path (e.g. /Users/rahul/lako/storage/chromadb).
    Always creates the directory if it does not exist.
    """
    p = Path(config_path)
    p.mkdir(parents=True, exist_ok=True)
    return p


class ChromaClient:
    """Client for the local ChromaDB vector store."""

    def __init__(self):
        self._client = None
        self._collection = None

    def _get_client(self) -> chromadb.PersistentClient:
        """Lazy-initialize ChromaDB PersistentClient on first use."""
        if self._client is None:
            path = _resolve_path(get_config()["chromadb_path"])
            self._client = chromadb.PersistentClient(
                path=str(path),
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        return self._client

    def get_collection(self):
        """
        Get or create the LAKO knowledge base collection.
        Uses cosine similarity metric — threshold values in config.json
        (e.g. 0.7) correspond to cosine similarity, not raw distance.
        ChromaDB stores cosine distance = 1 - cosine_similarity,
        so threshold 0.7 similarity → distance <= 0.3.
        If the cached collection reference is stale (e.g. cleared externally),
        it resets and recreates automatically.
        """
        if self._collection is None:
            self._collection = self._get_client().get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
        else:
            # Verify the cached reference is still valid
            try:
                self._collection.count()
            except Exception:
                self._collection = None
                return self.get_collection()
        return self._collection

    def add_chunks(self, chunks: List[dict]) -> None:
        """
        Add embedded document chunks to ChromaDB.

        Each chunk dict must contain:
          - embedding:  List[float]  — vector from embedder
          - document:   str          — the text content
          - metadata:   dict         — filename, page, chunk_type, timestamp
          - id:         str (opt)    — auto-generated if absent
        """
        if not chunks:
            return

        collection = self.get_collection()
        now = datetime.now(timezone.utc).isoformat()

        ids, embeddings, documents, metadatas = [], [], [], []

        for chunk in chunks:
            chunk_id = chunk.get("id") or str(uuid.uuid4())
            raw_meta = chunk.get("metadata", {})
            # Start with all provided metadata fields (allows source-specific
            # fields like source, url, title, author from Confluence ingestion).
            # Then ensure the four core fields are present and correctly typed.
            meta = {k: v for k, v in raw_meta.items() if isinstance(v, (str, int, float, bool))}
            meta["filename"]   = raw_meta.get("filename", "unknown")
            meta["page"]       = int(raw_meta.get("page", 0))
            meta["chunk_type"] = raw_meta.get("chunk_type", "text")
            meta["timestamp"]  = raw_meta.get("timestamp", now)
            ids.append(chunk_id)
            embeddings.append(chunk["embedding"])
            documents.append(chunk["document"])
            metadatas.append(meta)

        collection.add(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    def similarity_search(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        threshold: float = 0.7,
    ) -> List[dict]:
        """
        Find the top_k most similar chunks to query_embedding.
        Filters results to only those with cosine similarity >= threshold.

        ChromaDB returns cosine distance (0 = identical, 2 = opposite).
        We convert: similarity = 1 - distance, then filter by threshold.

        Returns list of dicts: {document, metadata, score}
        where score is cosine similarity (0–1).
        """
        collection = self.get_collection()
        if collection.count() == 0:
            return []

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        hits = []
        distances  = results["distances"][0]
        documents  = results["documents"][0]
        metadatas  = results["metadatas"][0]

        for dist, doc, meta in zip(distances, documents, metadatas):
            similarity = 1.0 - dist          # cosine: distance → similarity
            if similarity >= threshold:
                hits.append({
                    "document": doc,
                    "metadata": meta,
                    "score":    round(similarity, 4),
                })

        # Sort descending by score
        hits.sort(key=lambda x: x["score"], reverse=True)
        return hits

    def get_stats(self) -> dict:
        """
        Return collection stats for the Dashboard and Vector DB page.
        Returns: status, collection name, total_chunks, path.
        """
        try:
            collection = self.get_collection()
            return {
                "status":       "ok",
                "collection":   COLLECTION_NAME,
                "total_chunks": collection.count(),
                "path":         get_config()["chromadb_path"],
            }
        except Exception as e:
            return {
                "status":       "error",
                "collection":   COLLECTION_NAME,
                "total_chunks": 0,
                "path":         get_config()["chromadb_path"],
                "error":        str(e),
            }

    def get_all_documents(self) -> List[dict]:
        """
        Fetch all stored documents for BM25 index construction.
        Returns list of {id, document, metadata} dicts.
        Called by rag_engine when BM25 index needs a rebuild.
        """
        collection = self.get_collection()
        if collection.count() == 0:
            return []
        result = collection.get(include=["documents", "metadatas"])
        return [
            {"id": id_, "document": doc, "metadata": meta}
            for id_, doc, meta in zip(
                result["ids"], result["documents"], result["metadatas"]
            )
        ]

    def clear_collection(self) -> int:
        """
        Delete all documents from the collection.
        Recreates the collection so it is empty but still exists.
        Returns the number of chunks that were deleted.
        """
        try:
            collection = self.get_collection()
            count = collection.count()
            client = self._get_client()
            client.delete_collection(COLLECTION_NAME)
            self._collection = None          # force re-creation on next access
            self.get_collection()            # recreate immediately
            return count
        except Exception:
            return 0


# Singleton instance
chroma_client = ChromaClient()
