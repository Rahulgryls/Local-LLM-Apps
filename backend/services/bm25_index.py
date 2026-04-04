"""
LAKO — BM25 Index Service
Keyword search index that complements vector search.
Used in hybrid retrieval: BM25 + vector → Reciprocal Rank Fusion → LLM.

BM25 (Best Match 25) captures exact keyword matches that pure vector search
misses — critical for proper nouns, model names, acronyms like "LAKO".

The index is held in memory and rebuilt from ChromaDB on first query after
startup or after any ingestion. No extra storage needed.
"""

import re
import logging
from typing import List

from rank_bm25 import BM25Okapi


def _tokenize(text: str) -> List[str]:
    """Lowercase word tokenization — splits on non-alphanumeric characters."""
    return re.findall(r"\w+", text.lower())


class BM25Index:
    """
    In-memory BM25 index over all ChromaDB documents.
    Thread-safe for reads; rebuild is triggered explicitly after ingestion.
    """

    def __init__(self):
        self._corpus: List[dict] = []   # [{id, document, metadata}, ...]
        self._bm25: BM25Okapi | None = None
        self._dirty: bool = True        # True = needs rebuild from ChromaDB

    def mark_dirty(self):
        """Call after any ingestion to trigger rebuild on next query."""
        self._dirty = True

    def build(self, documents: List[dict]):
        """
        Build (or rebuild) index from a list of document dicts.
        Each dict must have: id (str), document (str), metadata (dict).
        """
        self._corpus = documents
        self._dirty = False

        if not documents:
            self._bm25 = None
            return

        tokenized = []
        for d in documents:
            text = d["document"]
            summary = d.get("metadata", {}).get("table_summary", "")
            if summary:
                # Prepend the LLM-generated summary so BM25 can match natural-language
                # queries (e.g. "highest uninsured rate by ethnicity") against table
                # chunks whose raw markdown cells contain no such keywords.
                text = summary + " " + text
            tokenized.append(_tokenize(text))
        self._bm25 = BM25Okapi(tokenized)
        logging.info(f"BM25 index built — {len(documents)} documents")

    def search(self, query: str, top_k: int = 20) -> List[dict]:
        """
        Return up to top_k documents ranked by BM25 score.
        Only documents with score > 0 (at least one keyword match) are returned.
        Result format: {document, metadata, bm25_score}
        """
        if self._bm25 is None or not self._corpus:
            return []

        tokens = _tokenize(query)
        if not tokens:
            return []

        scores = self._bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)

        results = []
        for idx, score in ranked[:top_k]:
            if score <= 0:
                break
            doc = self._corpus[idx]
            results.append({
                "document": doc["document"],
                "metadata": doc["metadata"],
                "bm25_score": float(score),
            })
        return results

    @property
    def size(self) -> int:
        return len(self._corpus)

    @property
    def is_dirty(self) -> bool:
        return self._dirty


# Singleton instance
bm25_index = BM25Index()
