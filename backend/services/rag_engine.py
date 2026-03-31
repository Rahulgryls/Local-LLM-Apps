"""
LAKO — RAG Engine Service
Retrieval-Augmented Generation pipeline.
Query → hybrid search (vector + BM25 + RRF) → MMR diversification → inject chunks → LLM → answer + citations.
Session 8: Core pipeline.
Session 8 (post): Hybrid search, query expansion, RRF fusion.
Session 12: Query caching (TTLCache, 1h, 50 entries) + MMR chunk diversification.
"""

import json
import logging
import time
from typing import AsyncGenerator, List, Optional

from cachetools import TTLCache

from services.embedder import embedder
from services.chroma_client import chroma_client
from services.ollama_client import ollama_client
from services.bm25_index import bm25_index
from config import get_config


SYSTEM_PROMPT = """You are LAKO, an AI knowledge assistant for bank staff at Rabobank.
You are given relevant excerpts from internal documents. Use them to compose a clear, complete, and helpful answer in your own words.
Write in flowing prose — synthesise the information naturally. Do NOT list source references inline; citations are shown separately by the system.
If the provided context does not contain enough information to answer the question, say exactly: 'This information was not found in the knowledge base.'
Always respond in the same language as the question (EN or NL)."""

# ── Query cache ────────────────────────────────────────────────────────────────
# Key: normalised query string. Value: {"answer": str, "sources": list}.
# TTL = 3600s (1 hour). maxsize = 50 entries. Thread-safe for asyncio.
_query_cache: TTLCache = TTLCache(maxsize=50, ttl=3600)

logger = logging.getLogger(__name__)


def invalidate_query_cache() -> None:
    """Clear the query cache. Call this after any new document ingestion."""
    before = len(_query_cache)
    _query_cache.clear()
    logger.info(f"[cache] Invalidated — {before} entr{'y' if before == 1 else 'ies'} cleared")


def _cache_key(query: str) -> str:
    """Normalise query to a stable cache key."""
    return query.strip().lower()


class RAGEngine:
    """Orchestrates the full RAG pipeline for LAKO."""

    # ── Public entry point ──────────────────────────────────────────────────

    async def query(
        self,
        question: str,
        model: Optional[str] = None,
        top_k: Optional[int] = None,
        use_rag: bool = True,
    ) -> dict:
        """
        Full RAG pipeline:
        1. Check query cache — return instantly on hit
        2. Expand short queries for better embedding coverage
        3. Hybrid search: vector (cosine) + BM25 keyword, fused with RRF
        4. MMR diversification to select final top_k chunks
        5. Build augmented prompt with retrieved chunks
        6. Call LLM (non-streaming)
        7. Cache + return answer + source citations

        Returns dict: {answer, sources, model, rag_used, cache_hit}
        """
        config = get_config()
        effective_model = model or config["primary_model"]
        effective_top_k = top_k or config["top_k"]

        if not use_rag:
            answer = await ollama_client.chat(
                question, model=effective_model, system=SYSTEM_PROMPT
            )
            return {
                "answer": answer,
                "sources": [],
                "model": effective_model,
                "rag_used": False,
                "cache_hit": False,
            }

        # ── Cache check ──────────────────────────────────────────────────────
        key = _cache_key(question)
        if key in _query_cache:
            cached = _query_cache[key]
            logger.info(f"[cache] HIT — '{question[:60]}'")
            return {
                "answer":    cached["answer"],
                "sources":   cached["sources"],
                "model":     effective_model,
                "rag_used":  True,
                "cache_hit": True,
            }
        logger.info(f"[cache] MISS — '{question[:60]}'")

        # ── Retrieval ────────────────────────────────────────────────────────
        expanded_question = self._expand_query(question)
        chunks = await self._hybrid_search(
            query=expanded_question,
            top_k=effective_top_k,
            threshold=config["similarity_threshold"],
        )

        if not chunks:
            return {
                "answer": "This information was not found in the knowledge base.",
                "sources": [],
                "model": effective_model,
                "rag_used": True,
                "cache_hit": False,
            }

        # ── MMR diversification ──────────────────────────────────────────────
        chunks = self._mmr_select(chunks, top_k=effective_top_k)

        prompt = self._build_prompt(question, chunks)
        answer = await ollama_client.chat(
            prompt, model=effective_model, system=SYSTEM_PROMPT
        )

        sources = self._format_sources(chunks)

        # ── Cache store ──────────────────────────────────────────────────────
        _query_cache[key] = {"answer": answer, "sources": sources}
        logger.info(f"[cache] STORED — '{question[:60]}' ({len(_query_cache)}/50 entries)")

        return {
            "answer":    answer,
            "sources":   sources,
            "model":     effective_model,
            "rag_used":  True,
            "cache_hit": False,
        }

    # ── Streaming RAG ───────────────────────────────────────────────────────

    async def stream_query(
        self,
        question: str,
        model: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming RAG pipeline — yields NDJSON lines:
          {"t":"token","v":"<token>"}      — one per LLM token as it arrives
          {"t":"sources","v":[...]}        — source citations, sent after last token
          {"t":"cache_hit","v":true/false} — first line emitted before tokens
          {"t":"error","v":"<msg>"}        — on failure

        On cache hit: emits the cached answer as a single token chunk, then sources.
        """
        config = get_config()
        effective_model = model or config["primary_model"]
        effective_top_k = top_k or config["top_k"]

        try:
            # ── Cache check ──────────────────────────────────────────────────
            key = _cache_key(question)
            if key in _query_cache:
                cached = _query_cache[key]
                logger.info(f"[cache] HIT (stream) — '{question[:60]}'")
                yield json.dumps({"t": "cache_hit", "v": True}) + "\n"
                # Stream cached answer word-by-word so the UI renders smoothly
                words = cached["answer"].split(" ")
                for i, word in enumerate(words):
                    chunk = word if i == len(words) - 1 else word + " "
                    yield json.dumps({"t": "token", "v": chunk}) + "\n"
                yield json.dumps({"t": "sources", "v": cached["sources"]}) + "\n"
                return

            yield json.dumps({"t": "cache_hit", "v": False}) + "\n"
            logger.info(f"[cache] MISS (stream) — '{question[:60]}'")

            # ── Retrieval ────────────────────────────────────────────────────
            expanded = self._expand_query(question)
            chunks = await self._hybrid_search(
                query=expanded,
                top_k=effective_top_k,
                threshold=config["similarity_threshold"],
            )

            if not chunks:
                yield json.dumps({"t": "token", "v": "This information was not found in the knowledge base."}) + "\n"
                yield json.dumps({"t": "sources", "v": []}) + "\n"
                return

            # ── MMR diversification ──────────────────────────────────────────
            chunks = self._mmr_select(chunks, top_k=effective_top_k)

            prompt = self._build_prompt(question, chunks)

            # ── Stream LLM tokens + collect full answer for caching ──────────
            full_answer_parts = []
            async for token in ollama_client.stream_chat(
                prompt, model=effective_model, system=SYSTEM_PROMPT
            ):
                full_answer_parts.append(token)
                yield json.dumps({"t": "token", "v": token}) + "\n"

            sources = self._format_sources(chunks)
            yield json.dumps({"t": "sources", "v": sources}) + "\n"

            # Store in cache after streaming completes
            full_answer = "".join(full_answer_parts)
            _query_cache[key] = {"answer": full_answer, "sources": sources}
            logger.info(f"[cache] STORED (stream) — '{question[:60]}' ({len(_query_cache)}/50 entries)")

        except Exception as exc:
            logging.exception("RAG stream_query failed")
            yield json.dumps({"t": "error", "v": str(exc)}) + "\n"

    # ── Hybrid search ───────────────────────────────────────────────────────

    async def _hybrid_search(
        self, query: str, top_k: int, threshold: float
    ) -> List[dict]:
        """
        Combines vector similarity search and BM25 keyword search via
        Reciprocal Rank Fusion (RRF). Retrieves 3× top_k candidates from
        each method, fuses, then returns top 3×top_k results for MMR to
        select from.
        """
        candidates = top_k * 3

        # ── Vector search ───────────────────────────────────────────────────
        query_embedding = await embedder.embed_query(query)
        vector_hits = chroma_client.similarity_search(
            query_embedding,
            top_k=candidates,
            threshold=threshold,
        )

        # ── BM25 search (rebuild index if dirty) ────────────────────────────
        if bm25_index.is_dirty or bm25_index.size == 0:
            docs = chroma_client.get_all_documents()
            bm25_index.build(docs)
            logging.info(f"BM25 index rebuilt — {bm25_index.size} documents")

        bm25_hits = bm25_index.search(query, top_k=candidates)

        # ── Reciprocal Rank Fusion ───────────────────────────────────────────
        fused = self._rrf_combine(vector_hits, bm25_hits)

        # Return 3× top_k so MMR has enough candidates to choose from
        return fused[:candidates]

    def _rrf_combine(
        self,
        vector_hits: List[dict],
        bm25_hits: List[dict],
        k: int = 60,
    ) -> List[dict]:
        """
        Reciprocal Rank Fusion: score(d) = Σ 1/(k + rank_i(d))
        k=60 is the standard constant from the original RRF paper (Cormack 2009).
        """
        rrf_scores: dict[str, float] = {}
        doc_store:  dict[str, dict]  = {}

        for rank, hit in enumerate(vector_hits):
            key = hit["document"][:120]
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            doc_store[key] = hit

        for rank, hit in enumerate(bm25_hits):
            key = hit["document"][:120]
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            if key not in doc_store:
                doc_store[key] = {
                    "document": hit["document"],
                    "metadata": hit["metadata"],
                    "score":    0.0,
                }

        results = []
        for key in sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True):
            item = dict(doc_store[key])
            item["score"] = round(rrf_scores[key], 6)
            results.append(item)

        return results

    # ── MMR diversification ─────────────────────────────────────────────────

    def _mmr_select(self, candidates: List[dict], top_k: int, lam: float = 0.6) -> List[dict]:
        """
        Maximal Marginal Relevance — selects top_k chunks that are both
        relevant AND diverse.

        score(d) = λ * relevance(d) - (1-λ) * max(jaccard(d, s) for s in selected)

        relevance = normalised RRF score (0–1).
        diversity = Jaccard similarity on word sets (no extra embeddings needed).
        λ=0.6 weights relevance slightly above diversity.

        Falls back to plain top-k slice if candidates <= top_k.
        """
        if len(candidates) <= top_k:
            return candidates

        # Normalise scores to 0–1
        max_score = max(c["score"] for c in candidates) or 1.0
        normed = [c["score"] / max_score for c in candidates]

        # Pre-compute word sets for Jaccard
        word_sets = [set(c["document"].lower().split()) for c in candidates]

        selected_idx: List[int] = []

        while len(selected_idx) < top_k:
            best_i, best_score = -1, float("-inf")

            for i, (candidate, rel) in enumerate(zip(candidates, normed)):
                if i in selected_idx:
                    continue

                if not selected_idx:
                    # First pick: pure relevance
                    mmr_score = rel
                else:
                    # Penalise by max similarity to already-selected chunks
                    max_sim = max(
                        self._jaccard(word_sets[i], word_sets[j])
                        for j in selected_idx
                    )
                    mmr_score = lam * rel - (1 - lam) * max_sim

                if mmr_score > best_score:
                    best_score = mmr_score
                    best_i = i

            if best_i == -1:
                break
            selected_idx.append(best_i)

        return [candidates[i] for i in selected_idx]

    @staticmethod
    def _jaccard(a: set, b: set) -> float:
        """Jaccard similarity between two word sets."""
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    # ── Query enhancement ───────────────────────────────────────────────────

    def _expand_query(self, question: str) -> str:
        """
        Expand short queries so they embed more similarly to document text.
        Queries under 8 words are reformulated as a detailed information request.
        """
        words = question.strip().split()
        if len(words) < 8:
            return (
                f"Provide detailed information about the following topic from bank documents: "
                f"{question}. Include definitions, context, and any relevant details."
            )
        return question

    # ── Prompt assembly ─────────────────────────────────────────────────────

    def _build_prompt(self, question: str, chunks: List[dict]) -> str:
        """Assemble the augmented prompt with source context."""
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            meta = chunk["metadata"]
            context_parts.append(
                f"--- Excerpt {i} (from {meta['filename']}, page {meta['page']}) ---\n"
                f"{chunk['document']}"
            )
        context = "\n\n".join(context_parts)
        return (
            f"Using the document excerpts below, answer the question at the end.\n\n"
            f"{context}\n\n"
            f"Question: {question}"
        )

    def _format_sources(self, chunks: List[dict]) -> List[dict]:
        """Format chunk metadata into source citation dicts."""
        return [
            {
                "filename":   c["metadata"]["filename"],
                "page":       c["metadata"]["page"],
                "chunk_type": c["metadata"]["chunk_type"],
                "score":      c["score"],
                "content":    c["document"],
                "source":     c["metadata"].get("source", "document"),
                "url":        c["metadata"].get("url", ""),
            }
            for c in chunks
        ]


# Singleton instance
rag_engine = RAGEngine()
