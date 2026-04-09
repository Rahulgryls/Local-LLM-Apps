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

def _apply_mmr_diversity(
    hits: list,
    top_k: int,
    score_threshold: float = 0.0,
) -> list:
    """
    Diversity pass with two goals:
      1. Guarantee — every unique document gets max(1, top_k // num_docs)
         slots unconditionally (threshold-free). With 3 docs + top_k=8 that
         is 2 guaranteed slots per document, so a minority-domain document
         (e.g. a medical report alongside economic reports) always contributes
         multiple pages instead of just its single highest-scoring page.
      2. Fill — remaining slots (up to top_k) go to highest-scoring hits
         that meet score_threshold, capped at per_doc_cap per document.

    The threshold is NOT applied to guaranteed slots (Pass 1), only to
    fill slots (Pass 2).

    Inputs are assumed sorted by score descending (as returned by Qdrant).
    """
    if not hits:
        return []

    # Count unique docs to compute per-doc cap for fill slots
    seen_ids: set[str] = set()
    for hit in hits:
        seen_ids.add(hit.payload.get("doc_id", ""))
    num_unique = len(seen_ids)
    per_doc_cap = max(2, top_k // max(num_unique, 1))

    # ── Pass 1: guarantee N slots per document (threshold-free) ──────────────
    # When multiple documents are indexed, guarantee max(1, top_k // num_docs)
    # slots per doc so minority-domain documents always contribute multiple
    # pages. Both slots bypass score_threshold — the doc earned them by being
    # indexed, not by beating cross-domain semantic similarity.
    guarantee_per_doc = max(1, top_k // max(num_unique, 1))

    guaranteed: list = []
    per_doc_guaranteed: dict[str, int] = {}
    remainder: list = []

    for hit in hits:
        doc_id = hit.payload.get("doc_id", "")
        count  = per_doc_guaranteed.get(doc_id, 0)
        if count < guarantee_per_doc and len(guaranteed) < top_k:
            guaranteed.append(hit)
            per_doc_guaranteed[doc_id] = count + 1
        else:
            remainder.append(hit)

    # ── Pass 2: fill remaining slots — threshold enforced here ─────────────────
    per_doc_count: dict[str, int] = dict(per_doc_guaranteed)
    result = list(guaranteed)

    for hit in remainder:
        if len(result) >= top_k:
            break
        if hit.score < score_threshold:
            continue   # threshold only blocks fill slots, not guaranteed slots
        doc_id = hit.payload.get("doc_id", "")
        if per_doc_count.get(doc_id, 0) < per_doc_cap:
            result.append(hit)
            per_doc_count[doc_id] = per_doc_count.get(doc_id, 0) + 1

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

    # ── Search — fetch WITHOUT score_threshold so no document is pre-excluded ───
    # The threshold is enforced inside MMR: guaranteed slots (1 per doc) bypass
    # it; fill slots must clear it. This prevents cross-domain documents from
    # being silently dropped before the diversity pass runs.
    client   = await _get_qdrant()
    response = await client.query_points(
        collection_name = COLLECTION_NAME,
        query           = vector,
        limit           = top_k * 5,
        # No score_threshold here — applied selectively inside _apply_mmr_diversity
        query_filter    = query_filter,
        with_payload    = True,
    )
    hits = response.points

    if not hits:
        logger.info("search_no_results", query=query[:80], threshold=score_threshold)
        return []

    # ── MMR diversity pass (threshold enforced for fill slots only) ────────────
    diverse_hits = _apply_mmr_diversity(hits, top_k, score_threshold=score_threshold)

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
