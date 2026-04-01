"""
LAKO — RAG Engine Service
Retrieval-Augmented Generation pipeline.
Query → hybrid search (vector + BM25 + RRF) → MMR diversification → inject chunks → LLM → answer + citations.
Session 8: Core pipeline.
Session 8 (post): Hybrid search, query expansion, RRF fusion.
Session 12: Query caching (TTLCache, 1h, 50 entries) + MMR chunk diversification.
Session 14: Query decomposition pipeline for cross-document comparison queries.
           Stage 1: Intent classifier (rule-based)
           Stage 2: LLM query decomposer
           Stage 3: Per-sub-query retrieval
           Stage 4: Context assembly with source-diversity guarantee
           Stage 5: Intent-aware synthesis prompt
"""

import asyncio
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

COMPARISON_SYSTEM_PROMPT = """You are LAKO, an AI knowledge assistant for bank staff at Rabobank.
You are answering a question that requires comparing information from multiple documents in the knowledge base.

INSTRUCTIONS:
- Carefully read ALL context sections provided below
- Every factual claim must be attributed to its source document
- Structure your answer using this format:

  ## [First Document / Topic]
  [Key points from this source]

  ## [Second Document / Topic]
  [Key points from this source]

  ## Comparison & Synthesis
  [Similarities, differences, and your analytical conclusion]

- If a document does not address a specific point, state that explicitly
- Do not invent or infer information not present in the provided context
- Be precise and professional — this is for a bank compliance team
- Always respond in the same language as the question (EN or NL)."""

AGGREGATION_SYSTEM_PROMPT = """You are LAKO, an AI knowledge assistant for bank staff at Rabobank.
You are synthesizing information across multiple documents in the knowledge base.
Combine key points from all sources.
Note where documents agree, complement, or contradict each other.
Always attribute claims to their source document by name.
Always respond in the same language as the question (EN or NL)."""

# ── Query cache ────────────────────────────────────────────────────────────────
# Key: normalised query string. Value: {"answer": str, "sources": list}.
# TTL = 3600s (1 hour). maxsize = 50 entries. Thread-safe for asyncio.
_query_cache: TTLCache = TTLCache(maxsize=50, ttl=3600)

logger = logging.getLogger(__name__)

# ── Intent classifier signals ─────────────────────────────────────────────────
COMPARISON_SIGNALS = [
    "compare", "contrast", "difference between", "versus", "vs",
    "how does", "differ", "similarities", "whereas", "while",
    "on the other hand", "in contrast", "compared to",
    "both documents", "according to both",
]

AGGREGATION_SIGNALS = [
    "across all", "all documents", "summarize everything",
    "combine", "overall", "in general",
]

# Conjunction keywords used for fallback query splitting
_SPLIT_CONJUNCTIONS = ["and", "with", "versus", "vs", "compared to", "while", "whereas"]


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

    # ══════════════════════════════════════════════════════════════════════════
    # Stage 1 — Intent Classifier
    # ══════════════════════════════════════════════════════════════════════════

    def classify_query_intent(self, query: str) -> dict:
        """
        Rule-based intent classifier — no LLM, instant.

        Returns:
          {"intent": "single"|"comparison"|"aggregation", "signals_found": [...]}
        """
        q = query.lower()

        comparison_found = [s for s in COMPARISON_SIGNALS if s in q]
        aggregation_found = [s for s in AGGREGATION_SIGNALS if s in q]

        if comparison_found:
            intent = "comparison"
            signals = comparison_found
        elif aggregation_found:
            intent = "aggregation"
            signals = aggregation_found
        else:
            intent = "single"
            signals = []

        if intent != "single":
            logger.info(f"[intent] '{intent}' detected (signals: {', '.join(signals)})")
        else:
            logger.debug(f"[intent] 'single' — no multi-doc signals detected")

        return {"intent": intent, "signals_found": signals}

    # ══════════════════════════════════════════════════════════════════════════
    # Stage 2 — Query Decomposer
    # ══════════════════════════════════════════════════════════════════════════

    async def decompose_query(self, query: str) -> List[str]:
        """
        LLM-powered query decomposer — breaks a multi-doc query into focused sub-queries.
        Only called when intent is 'comparison' or 'aggregation'.

        Returns a list of 2–4 focused sub-query strings.
        Falls back to conjunction splitting or the original query on failure.
        """
        config = get_config()
        model = config["primary_model"]

        system_prompt = (
            "You are a query decomposition engine for a document retrieval system. "
            "Break complex multi-document queries into simple, focused sub-queries. "
            "Each sub-query must be self-contained and answerable from a single document or topic area."
        )

        user_prompt = (
            f"Break this query into 2-4 simple focused sub-queries.\n"
            f"Each sub-query should target ONE specific topic or document.\n"
            f"Return ONLY a valid JSON array of strings. Nothing else.\n"
            f"No explanation. No markdown. Just the JSON array.\n\n"
            f"Query: {query}\n\n"
            f"Example input:\n"
            f'"Compare ACROI Local Execution approach with ECB cloud outsourcing policy"\n\n'
            f"Example output:\n"
            f'[\n'
            f'  "What is the ACROI approach to local execution and data sovereignty?",\n'
            f'  "What is the ECB policy on cloud outsourcing and operational resilience?"\n'
            f']'
        )

        try:
            raw = await asyncio.wait_for(
                ollama_client.chat(user_prompt, model=model, system=system_prompt),
                timeout=15.0,
            )

            # Strip markdown fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            raw = raw.strip()

            sub_queries = json.loads(raw)
            if not isinstance(sub_queries, list) or not sub_queries:
                raise ValueError("LLM returned empty or non-list JSON")

            sub_queries = [str(q).strip() for q in sub_queries if str(q).strip()]
            logger.info(
                f"[decompose] {len(sub_queries)} sub-queries generated:\n"
                + "\n".join(f"  [{i+1}] {q}" for i, q in enumerate(sub_queries))
            )
            return sub_queries

        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning(f"[decompose] LLM decompose failed ({exc}) — trying fallback split")

        # Fallback: split on conjunctions
        q_lower = query.lower()
        for conj in _SPLIT_CONJUNCTIONS:
            idx = q_lower.find(f" {conj} ")
            if idx != -1:
                part1 = query[:idx].strip()
                part2 = query[idx + len(conj) + 2:].strip()
                if part1 and part2:
                    logger.info(f"[decompose] fallback used — split on '{conj}': 2 parts")
                    return [part1, part2]

        logger.info("[decompose] fallback used — returning original query as single sub-query")
        return [query]

    # ══════════════════════════════════════════════════════════════════════════
    # Stage 3 — Per-Sub-query Retrieval
    # ══════════════════════════════════════════════════════════════════════════

    async def retrieve_for_subqueries(
        self, sub_queries: List[str], top_k_per: int = 3
    ) -> List[dict]:
        """
        Run hybrid retrieval independently for each sub-query.
        Returns flat list of all chunks with 'sub_query_index' added to metadata.
        """
        config = get_config()
        threshold = config["similarity_threshold"]

        all_chunks: List[dict] = []

        for idx, sub_q in enumerate(sub_queries):
            chunks = await self._hybrid_search(
                query=self._expand_query(sub_q),
                top_k=top_k_per,
                threshold=threshold,
            )
            # Tag each chunk with its sub-query origin
            for chunk in chunks:
                chunk = dict(chunk)
                chunk["metadata"] = dict(chunk["metadata"])
                chunk["metadata"]["sub_query_index"] = idx
                all_chunks.append(chunk)

            logger.info(f"[retrieve] sub-query {idx + 1}: {len(chunks)} chunks retrieved")

        logger.info(f"[retrieve] total: {len(all_chunks)} chunks before assembly")
        return all_chunks

    # ══════════════════════════════════════════════════════════════════════════
    # Stage 4 — Context Assembly
    # ══════════════════════════════════════════════════════════════════════════

    def assemble_context(self, all_chunks: List[dict], query: str) -> List[dict]:
        """
        Deduplicate → source-diversity interleave → MMR → diversity guarantee.
        Returns at most 6 chunks with guaranteed representation from each source file.
        """
        MAX_FINAL = 6

        # Step A — Deduplicate by first 120 chars of document text
        seen: set = set()
        deduped: List[dict] = []
        for chunk in all_chunks:
            key = chunk["document"][:120]
            if key not in seen:
                seen.add(key)
                deduped.append(chunk)

        logger.info(f"[assemble] {len(all_chunks)} raw → {len(deduped)} after dedup")

        # Step B — Source-diversity interleaving (round-robin by source_file)
        by_source: dict = {}
        for chunk in deduped:
            src = chunk["metadata"].get("filename", "unknown")
            by_source.setdefault(src, []).append(chunk)

        interleaved: List[dict] = []
        max_len = max(len(v) for v in by_source.values()) if by_source else 0
        sources_ordered = list(by_source.keys())
        for i in range(max_len):
            for src in sources_ordered:
                if i < len(by_source[src]):
                    interleaved.append(by_source[src][i])

        # Step C — MMR diversification (cap at MAX_FINAL)
        mmr_result = self._mmr_select(interleaved, top_k=MAX_FINAL)

        # Step D — Diversity guarantee: ensure every source has ≥1 chunk
        present_sources = {c["metadata"].get("filename") for c in mmr_result}
        for src, chunks in by_source.items():
            if src not in present_sources:
                mmr_result.append(chunks[0])
                logger.info(f"[assemble] force-added chunk from '{src}' (diversity guarantee)")

        # Log final source distribution
        final_sources: dict = {}
        for c in mmr_result:
            s = c["metadata"].get("filename", "unknown")
            final_sources[s] = final_sources.get(s, 0) + 1
        src_summary = ", ".join(f"{s}({n})" for s, n in final_sources.items())
        logger.info(f"[assemble] {len(deduped)} after dedup → {len(mmr_result)} after MMR | sources: {src_summary}")

        return mmr_result

    # ══════════════════════════════════════════════════════════════════════════
    # Public entry point — query()
    # ══════════════════════════════════════════════════════════════════════════

    async def query(
        self,
        question: str,
        model: Optional[str] = None,
        top_k: Optional[int] = None,
        use_rag: bool = True,
    ) -> dict:
        """
        Full RAG pipeline with query decomposition for multi-doc queries.
        Single-doc path is completely unchanged (same cache, MMR, top_k).
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
                "intent": "single",
                "sub_queries": None,
                "retrieval_mode": "standard",
            }

        # Stage 1 — Intent classification
        intent_result = self.classify_query_intent(question)
        intent = intent_result["intent"]

        if intent in ("comparison", "aggregation"):
            return await self._multi_doc_query(question, effective_model, intent)

        # ── Standard single-doc pipeline (unchanged) ─────────────────────────
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
                "intent":    "single",
                "sub_queries": None,
                "retrieval_mode": "standard",
            }
        logger.info(f"[cache] MISS — '{question[:60]}'")

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
                "intent": "single",
                "sub_queries": None,
                "retrieval_mode": "standard",
            }

        chunks = self._mmr_select(chunks, top_k=effective_top_k)
        prompt = self._build_prompt(question, chunks)
        answer = await ollama_client.chat(prompt, model=effective_model, system=SYSTEM_PROMPT)
        sources = self._format_sources(chunks)

        _query_cache[key] = {"answer": answer, "sources": sources}
        logger.info(f"[cache] STORED — '{question[:60]}' ({len(_query_cache)}/50 entries)")

        return {
            "answer":    answer,
            "sources":   sources,
            "model":     effective_model,
            "rag_used":  True,
            "cache_hit": False,
            "intent":    "single",
            "sub_queries": None,
            "retrieval_mode": "standard",
        }

    async def _multi_doc_query(
        self, question: str, model: str, intent: str
    ) -> dict:
        """Stages 2–5 for comparison/aggregation queries."""
        logger.info(f"[multi-doc] Starting multi-doc pipeline (intent={intent})")

        # Stage 2 — Decompose
        sub_queries = await self.decompose_query(question)

        # Stage 3 — Per-sub-query retrieval
        all_chunks = await self.retrieve_for_subqueries(sub_queries, top_k_per=3)

        if not all_chunks:
            return {
                "answer": "This information was not found in the knowledge base.",
                "sources": [],
                "model": model,
                "rag_used": True,
                "cache_hit": False,
                "intent": intent,
                "sub_queries": sub_queries,
                "retrieval_mode": "multi-doc",
            }

        # Stage 4 — Assemble context
        final_chunks = self.assemble_context(all_chunks, question)

        # Stage 5 — Intent-aware prompt + LLM
        system = COMPARISON_SYSTEM_PROMPT if intent == "comparison" else AGGREGATION_SYSTEM_PROMPT
        prompt = self._build_prompt(question, final_chunks)
        answer = await ollama_client.chat(prompt, model=model, system=system)

        sources = self._format_sources(final_chunks)
        logger.info(f"[multi-doc] Pipeline complete — {len(final_chunks)} chunks, {len(sources)} sources")

        return {
            "answer":    answer,
            "sources":   sources,
            "model":     model,
            "rag_used":  True,
            "cache_hit": False,
            "intent":    intent,
            "sub_queries": sub_queries,
            "retrieval_mode": "multi-doc",
        }

    # ══════════════════════════════════════════════════════════════════════════
    # Streaming RAG
    # ══════════════════════════════════════════════════════════════════════════

    async def stream_query(
        self,
        question: str,
        model: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming RAG pipeline — yields NDJSON lines:
          {"t":"cache_hit","v":true/false}  — first line
          {"t":"meta","v":{intent,retrieval_mode,sub_queries}}  — before tokens
          {"t":"token","v":"<token>"}        — one per LLM token
          {"t":"sources","v":[...]}          — after last token
          {"t":"error","v":"<msg>"}          — on failure

        Comparison/aggregation queries use the multi-doc pipeline (non-cached).
        Single queries use the existing cache-aware pipeline.
        """
        config = get_config()
        effective_model = model or config["primary_model"]
        effective_top_k = top_k or config["top_k"]

        try:
            # Stage 1 — Intent classification
            intent_result = self.classify_query_intent(question)
            intent = intent_result["intent"]

            if intent in ("comparison", "aggregation"):
                async for line in self._stream_multi_doc(question, effective_model, intent):
                    yield line
                return

            # ── Single-doc streaming pipeline (unchanged) ─────────────────────
            key = _cache_key(question)
            if key in _query_cache:
                cached = _query_cache[key]
                logger.info(f"[cache] HIT (stream) — '{question[:60]}'")
                yield json.dumps({"t": "cache_hit", "v": True}) + "\n"
                yield json.dumps({"t": "meta", "v": {"intent": "single", "retrieval_mode": "standard", "sub_queries": None}}) + "\n"
                words = cached["answer"].split(" ")
                for i, word in enumerate(words):
                    chunk = word if i == len(words) - 1 else word + " "
                    yield json.dumps({"t": "token", "v": chunk}) + "\n"
                yield json.dumps({"t": "sources", "v": cached["sources"]}) + "\n"
                return

            yield json.dumps({"t": "cache_hit", "v": False}) + "\n"
            yield json.dumps({"t": "meta", "v": {"intent": "single", "retrieval_mode": "standard", "sub_queries": None}}) + "\n"
            logger.info(f"[cache] MISS (stream) — '{question[:60]}'")

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

            chunks = self._mmr_select(chunks, top_k=effective_top_k)
            prompt = self._build_prompt(question, chunks)

            full_answer_parts = []
            async for token in ollama_client.stream_chat(
                prompt, model=effective_model, system=SYSTEM_PROMPT
            ):
                full_answer_parts.append(token)
                yield json.dumps({"t": "token", "v": token}) + "\n"

            sources = self._format_sources(chunks)
            yield json.dumps({"t": "sources", "v": sources}) + "\n"

            full_answer = "".join(full_answer_parts)
            _query_cache[key] = {"answer": full_answer, "sources": sources}
            logger.info(f"[cache] STORED (stream) — '{question[:60]}' ({len(_query_cache)}/50 entries)")

        except Exception as exc:
            logging.exception("RAG stream_query failed")
            yield json.dumps({"t": "error", "v": str(exc)}) + "\n"

    async def _stream_multi_doc(
        self, question: str, model: str, intent: str
    ) -> AsyncGenerator[str, None]:
        """Streaming multi-doc pipeline for comparison/aggregation queries."""
        try:
            yield json.dumps({"t": "cache_hit", "v": False}) + "\n"

            # Stage 2 — Decompose
            sub_queries = await self.decompose_query(question)
            yield json.dumps({"t": "meta", "v": {
                "intent": intent,
                "retrieval_mode": "multi-doc",
                "sub_queries": sub_queries,
            }}) + "\n"

            # Stage 3 — Retrieve
            all_chunks = await self.retrieve_for_subqueries(sub_queries, top_k_per=3)

            if not all_chunks:
                yield json.dumps({"t": "token", "v": "This information was not found in the knowledge base."}) + "\n"
                yield json.dumps({"t": "sources", "v": []}) + "\n"
                return

            # Stage 4 — Assemble
            final_chunks = self.assemble_context(all_chunks, question)

            # Stage 5 — Stream LLM response
            system = COMPARISON_SYSTEM_PROMPT if intent == "comparison" else AGGREGATION_SYSTEM_PROMPT
            prompt = self._build_prompt(question, final_chunks)

            async for token in ollama_client.stream_chat(prompt, model=model, system=system):
                yield json.dumps({"t": "token", "v": token}) + "\n"

            sources = self._format_sources(final_chunks)
            yield json.dumps({"t": "sources", "v": sources}) + "\n"
            logger.info(f"[multi-doc] Stream complete — {len(sources)} sources")

        except Exception as exc:
            logging.exception("RAG _stream_multi_doc failed")
            yield json.dumps({"t": "error", "v": str(exc)}) + "\n"

    # ══════════════════════════════════════════════════════════════════════════
    # Hybrid search (unchanged)
    # ══════════════════════════════════════════════════════════════════════════

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

        query_embedding = await embedder.embed_query(query)
        vector_hits = chroma_client.similarity_search(
            query_embedding,
            top_k=candidates,
            threshold=threshold,
        )

        if bm25_index.is_dirty or bm25_index.size == 0:
            docs = chroma_client.get_all_documents()
            bm25_index.build(docs)
            logging.info(f"BM25 index rebuilt — {bm25_index.size} documents")

        bm25_hits = bm25_index.search(query, top_k=candidates)

        fused = self._rrf_combine(vector_hits, bm25_hits)
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

        max_score = max(c["score"] for c in candidates) or 1.0
        normed = [c["score"] / max_score for c in candidates]

        word_sets = [set(c["document"].lower().split()) for c in candidates]

        selected_idx: List[int] = []

        while len(selected_idx) < top_k:
            best_i, best_score = -1, float("-inf")

            for i, (candidate, rel) in enumerate(zip(candidates, normed)):
                if i in selected_idx:
                    continue

                if not selected_idx:
                    mmr_score = rel
                else:
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
