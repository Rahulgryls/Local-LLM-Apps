"""
LAKO — RAG Engine Service
Retrieval-Augmented Generation pipeline.
Query → hybrid search (vector + BM25 + RRF) → inject chunks → LLM → answer + citations.
Session 8: Core pipeline.
Session 8 (post): Hybrid search, query expansion, RRF fusion.
"""

import logging
from typing import List, Optional

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
        1. Expand short queries for better embedding coverage
        2. Hybrid search: vector (cosine) + BM25 keyword, fused with RRF
        3. Build augmented prompt with retrieved chunks
        4. Call LLM (non-streaming)
        5. Return answer + source citations

        Returns dict: {answer, sources, model, rag_used}
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
            }

        # Step 1: expand short queries
        expanded_question = self._expand_query(question)

        # Step 2: hybrid retrieval
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
            }

        # Step 3: build augmented prompt
        prompt = self._build_prompt(question, chunks)   # original question, not expanded

        # Step 4: call LLM
        answer = await ollama_client.chat(
            prompt, model=effective_model, system=SYSTEM_PROMPT
        )

        # Step 5: format sources
        sources = [
            {
                "filename":   c["metadata"]["filename"],
                "page":       c["metadata"]["page"],
                "chunk_type": c["metadata"]["chunk_type"],
                "score":      c["score"],
                "content":    c["document"],
            }
            for c in chunks
        ]

        return {
            "answer":   answer,
            "sources":  sources,
            "model":    effective_model,
            "rag_used": True,
        }

    # ── Hybrid search ───────────────────────────────────────────────────────

    async def _hybrid_search(
        self, query: str, top_k: int, threshold: float
    ) -> List[dict]:
        """
        Combines vector similarity search and BM25 keyword search via
        Reciprocal Rank Fusion (RRF). Retrieves 3× top_k candidates from
        each method, fuses, then returns the top top_k results.
        Vector results below threshold are excluded before fusion.
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

        return fused[:top_k]

    def _rrf_combine(
        self,
        vector_hits: List[dict],
        bm25_hits: List[dict],
        k: int = 60,
    ) -> List[dict]:
        """
        Reciprocal Rank Fusion: score(d) = Σ 1/(k + rank_i(d))
        k=60 is the standard constant from the original RRF paper (Cormack 2009).

        Deduplication key: first 120 chars of document text (chunks are unique).
        Returns list sorted descending by RRF score with 'score' field set.
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

        # Sort by RRF score descending, attach score to each result
        results = []
        for key in sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True):
            item = dict(doc_store[key])
            item["score"] = round(rrf_scores[key], 6)
            results.append(item)

        return results

    # ── Query enhancement ───────────────────────────────────────────────────

    def _expand_query(self, question: str) -> str:
        """
        Expand short queries so they embed more similarly to document text.
        Queries under 8 words are reformulated as a detailed information request.
        Longer queries are returned as-is.
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
        """
        Assemble the augmented prompt.
        Context chunks are labelled for traceability; the model is instructed
        via SYSTEM_PROMPT to synthesise rather than parrot them.
        """
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


# Singleton instance
rag_engine = RAGEngine()
