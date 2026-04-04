"""
LAKO V2 — Vector Searcher

Embeds the user query with nomic-embed-text, searches Qdrant,
then applies a simple MMR diversity pass to avoid returning 3+
pages from the same document.

Public API:
  search_pages(query, top_k, score_threshold, doc_id_filter, source_type_filter)
    -> list[SearchResult]
"""

import logging
from typing import Optional

import structlog
from qdrant_client.http.models import FieldCondition, Filter, MatchValue

from ingestion.embedder_v2 import COLLECTION_NAME, _get_qdrant
from retrieval.models import SearchResult

logger = structlog.get_logger(__name__)


# ── MMR diversity ──────────────────────────────────────────────────────────────

def _apply_mmr_diversity(hits: list, top_k: int) -> list:
    """
    Cap any single document at 2 results when 3+ would otherwise be returned.
    Freed slots are filled by the next-best hits from other documents.

    Inputs are assumed sorted by score descending (as returned by Qdrant).
    """
    # Separate hits into "kept" (≤2 per doc) and "overflow" (>2 per doc)
    per_doc: dict[str, int] = {}
    kept:     list = []
    overflow: list = []

    for hit in hits:
        doc_id = hit.payload.get("doc_id", "")
        count  = per_doc.get(doc_id, 0)
        if count < 2:
            kept.append(hit)
            per_doc[doc_id] = count + 1
        else:
            overflow.append(hit)

    # Fill up to top_k using overflow (already scored lower, sorted descending)
    result = kept[:top_k]
    if len(result) < top_k:
        needed = top_k - len(result)
        result.extend(overflow[:needed])

    # Re-sort by score descending (kept was already ordered, overflow may not be)
    result.sort(key=lambda h: h.score, reverse=True)
    return result[:top_k]


# ── Main search function ───────────────────────────────────────────────────────

async def search_pages(
    query:               str,
    top_k:               int   = 5,
    score_threshold:     float = 0.3,
    doc_id_filter:       Optional[str] = None,
    source_type_filter:  Optional[str] = None,
    query_vector:        Optional[list] = None,
) -> list[SearchResult]:
    """
    Embed *query*, search Qdrant, apply MMR diversity, return SearchResults.

    Args:
        query:              Natural-language user question.
        top_k:              Maximum results to return after MMR.
        score_threshold:    Minimum cosine similarity (0–1) to include a hit.
        doc_id_filter:      If set, restrict search to this document.
        source_type_filter: If set, restrict search to this source_type ("pdf"|"pptx").

    Returns:
        List of SearchResult objects, sorted by score descending.
        Empty list if no results meet the threshold.
    """
    from services.ollama_client import ollama_client

    # ── Embed query (use pre-computed vector if provided) ──────────────────────
    if query_vector is not None:
        vector = query_vector
    else:
        vector = await ollama_client.embed(query)

    # ── Build optional filter ──────────────────────────────────────────────────
    conditions = []
    if doc_id_filter:
        conditions.append(
            FieldCondition(key="doc_id", match=MatchValue(value=doc_id_filter))
        )
    if source_type_filter:
        conditions.append(
            FieldCondition(key="source_type", match=MatchValue(value=source_type_filter))
        )
    query_filter = Filter(must=conditions) if conditions else None

    # ── Search — over-fetch so MMR has candidates to work with ─────────────────
    client   = await _get_qdrant()
    response = await client.query_points(
        collection_name = COLLECTION_NAME,
        query           = vector,
        limit           = top_k * 3,
        score_threshold = score_threshold,
        query_filter    = query_filter,
        with_payload    = True,
    )
    hits = response.points

    if not hits:
        logger.info("search_no_results", query=query[:80], threshold=score_threshold)
        return []

    # ── MMR diversity pass ─────────────────────────────────────────────────────
    diverse_hits = _apply_mmr_diversity(hits, top_k)

    results = []
    for hit in diverse_hits:
        p = hit.payload
        results.append(SearchResult(
            doc_id       = p.get("doc_id", ""),
            page_num     = p.get("page_num", 0),
            filename     = p.get("filename", ""),
            source_type  = p.get("source_type", ""),
            score        = hit.score,
            summary_text = p.get("summary_text", ""),
            headers      = p.get("headers", ""),
            has_tables   = bool(p.get("has_tables", False)),
        ))

    logger.info(
        "search_complete",
        query=query[:80],
        hits_raw=len(hits),
        hits_after_mmr=len(results),
    )
    return results
