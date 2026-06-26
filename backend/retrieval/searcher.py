"""
LAKO V2 — Vector Searcher

Embeds the user query with nomic-embed-text, searches Qdrant (and optionally
a BM25 keyword index), merges results via Reciprocal Rank Fusion, then applies
a two-tier MMR diversity pass to avoid returning N+ pages from one document.

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

# V3 direct-RAG collection (PDFs, DOCX, Confluence via ingest_v3 / confluence_v3)
V3_COLLECTION_NAME = "lako_documents"

# RRF smoothing constant — standard value from the original Cormack et al. paper.
# Higher k dampens the impact of rank differences; 60 is the widely accepted default.
_RRF_K = 60

logger = structlog.get_logger(__name__)


# ── MMR diversity ──────────────────────────────────────────────────────────────

def _apply_mmr_diversity(
    hits: list,
    top_k: int,
    score_threshold: float = 0.0,
    soft_threshold: float = 0.15,
) -> list:
    """
    Two-tier diversity pass ensuring every relevant document contributes
    pages to the context window.

    TWO-TIER THRESHOLD MODEL
    ─────────────────────────
    soft_threshold (default 0.15):
        Applied in Pass 1 (guaranteed slots).  A document whose best page
        scores below this is considered noise — it gets zero guaranteed slots.
        Prevents truly irrelevant documents from forcing junk into context
        while still protecting minority-domain documents that score moderately.

    score_threshold (default 0.25, set from config):
        Applied in Pass 2 (fill slots).  The existing hard floor — a page
        must score at least this high to be picked as a fill candidate.

    PASS 1 — Guaranteed representation
        Every document with at least one hit >= soft_threshold receives
        max(1, top_k // num_docs) guaranteed slots regardless of exact score.
        This protects minority-domain documents (e.g. a 7-page medical report
        indexed alongside 182-page IMF reports) from being crowded out by the
        volume of high-scoring hits from the dominant document.

    PASS 2 — Fill remaining slots
        Remaining slots go to highest-scoring hits that:
          • exceed score_threshold (hard floor), AND
          • don't exceed per_doc_cap hits per document.

    Inputs are assumed sorted by score descending (as returned by Qdrant /
    pre-sorted after RRF).
    """
    if not hits:
        return []

    # Identify documents that clear the soft threshold (have at least one
    # qualifying page).  Documents below this are treated as noise.
    qualifying_docs: set[str] = set()
    for hit in hits:
        doc_id = hit.payload.get("doc_id", "")
        if hit.score >= soft_threshold:
            qualifying_docs.add(doc_id)

    num_unique    = max(len(qualifying_docs), 1)
    per_doc_cap   = max(2, top_k // num_unique)
    guarantee_per_doc = max(1, top_k // num_unique)

    # ── Pass 1: guarantee N slots per qualifying document ─────────────────────
    guaranteed: list         = []
    per_doc_guaranteed: dict[str, int] = {}
    remainder: list          = []

    for hit in hits:
        doc_id = hit.payload.get("doc_id", "")
        if doc_id not in qualifying_docs:
            # Document scored too low — skip guaranteed slot, goes to remainder
            remainder.append(hit)
            continue
        count = per_doc_guaranteed.get(doc_id, 0)
        if count < guarantee_per_doc and len(guaranteed) < top_k:
            guaranteed.append(hit)
            per_doc_guaranteed[doc_id] = count + 1
        else:
            remainder.append(hit)

    # ── Pass 2: fill remaining slots — hard threshold enforced here ───────────
    per_doc_count: dict[str, int] = dict(per_doc_guaranteed)
    result = list(guaranteed)

    for hit in remainder:
        if len(result) >= top_k:
            break
        if hit.score < score_threshold:
            continue   # hard floor for fill slots
        doc_id = hit.payload.get("doc_id", "")
        if per_doc_count.get(doc_id, 0) < per_doc_cap:
            result.append(hit)
            per_doc_count[doc_id] = per_doc_count.get(doc_id, 0) + 1

    result.sort(key=lambda h: h.score, reverse=True)
    return result[:top_k]


# ── RRF merge ──────────────────────────────────────────────────────────────────

def _apply_rrf(
    collection_results: list[list],
    k: int = _RRF_K,
) -> list:
    """
    Reciprocal Rank Fusion across multiple result lists.

    Each element of *collection_results* is a list of Qdrant ScoredPoint objects
    (or BM25 shim objects) already sorted by their own collection's score.
    Hits are deduplicated by (doc_id, page_num) — if the same page appears in
    multiple collections its RRF contributions are summed.

    Returns the merged list sorted by RRF score descending.
    The original .score attribute (cosine similarity) is preserved on each hit
    so callers can still surface cosine scores to users.  RRF score is stored
    in a transient ._rrf_score attribute used only for ordering.
    """
    # rrf_scores: (doc_id, page_num) → accumulated RRF score
    rrf_scores: dict[tuple[str, int], float] = {}
    # best_hit:  (doc_id, page_num) → the hit object with the highest cosine score
    # (we keep the highest-scored representative so SearchResult.score is meaningful)
    best_hit: dict[tuple[str, int], object]  = {}

    for ranked_list in collection_results:
        for rank_0, hit in enumerate(ranked_list):
            rank    = rank_0 + 1            # 1-based
            doc_id  = hit.payload.get("doc_id", "")
            page_num = hit.payload.get("page_num", hit.payload.get("page", 0))
            key     = (doc_id, page_num)

            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (k + rank)

            # Representative selection: always prefer a Qdrant hit (real cosine
            # score in [0,1]) over a BM25 shim (unnormalized score, can be >> 1).
            # If both are Qdrant hits, keep the higher cosine score.
            is_bm25 = bool(hit.payload.get("_bm25_only"))
            if key not in best_hit:
                best_hit[key] = hit
            else:
                existing_bm25 = bool(best_hit[key].payload.get("_bm25_only"))
                if existing_bm25 and not is_bm25:
                    best_hit[key] = hit          # upgrade BM25 shim → real Qdrant hit
                elif not existing_bm25 and not is_bm25:
                    if hit.score > best_hit[key].score:
                        best_hit[key] = hit      # both Qdrant — keep higher cosine
                # else: existing Qdrant, new BM25 — keep existing

    # Attach the computed RRF score to each representative hit as a transient attr
    merged = []
    for key, rrf in rrf_scores.items():
        hit = best_hit[key]
        # Attach as instance attribute — ScoredPoint is a dataclass-like object
        hit._rrf_score = rrf
        merged.append(hit)

    merged.sort(key=lambda h: h._rrf_score, reverse=True)
    return merged


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
    Embed *query*, search Qdrant (+ BM25 if enabled), merge via RRF,
    apply two-tier MMR diversity, return SearchResults.

    Args:
        query:              Natural-language user question.
        top_k:              Maximum results to return after MMR.
        score_threshold:    Minimum cosine similarity (0–1) for fill slots (Pass 2 MMR).
        doc_id_filter:      If set, restrict search to this document.
        source_type_filter: If set, restrict search to this source_type ("pdf"|"pptx").

    Returns:
        List of SearchResult objects, sorted by cosine score descending.
        Empty list if no results meet the threshold.
    """
    from config import get_config
    from services.ollama_client import ollama_client

    cfg             = get_config()
    soft_threshold  = cfg.get("mmr_soft_threshold", 0.15)
    hybrid_enabled  = cfg.get("hybrid_search_enabled", True)

    # ── Embed query (use pre-computed vector if provided) ──────────────────────
    if query_vector is not None:
        vector = query_vector
    else:
        vector = await ollama_client.embed(query)

    # ── Build optional Qdrant filter ───────────────────────────────────────────
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

    # ── Search Qdrant collections ──────────────────────────────────────────────
    # Each collection is searched independently; we feed their sorted result lists
    # into RRF rather than merging by raw score (different score distributions).
    # Threshold NOT applied here — enforced selectively inside MMR.
    client = await _get_qdrant()

    collection_result_lists: list[list] = []

    # Query V2 collection (lako_page_summaries — LLM-generated summaries)
    try:
        resp_v2 = await client.query_points(
            collection_name = COLLECTION_NAME,
            query           = vector,
            limit           = top_k * 5,
            query_filter    = query_filter,
            with_payload    = True,
        )
        if resp_v2.points:
            collection_result_lists.append(list(resp_v2.points))
    except Exception as exc:
        logger.warning("v2_collection_search_failed", error=str(exc))

    # Query V3 collection (lako_documents — Confluence + V3 file uploads)
    try:
        existing_collections = {
            c.name for c in (await client.get_collections()).collections
        }
        if V3_COLLECTION_NAME in existing_collections:
            resp_v3 = await client.query_points(
                collection_name = V3_COLLECTION_NAME,
                query           = vector,
                limit           = top_k * 5,
                query_filter    = query_filter,
                with_payload    = True,
            )
            if resp_v3.points:
                collection_result_lists.append(list(resp_v3.points))
    except Exception as exc:
        logger.warning("v3_collection_search_failed", error=str(exc))

    # ── BM25 keyword search (optional third collection for RRF) ───────────────
    # Runs in parallel with the Qdrant fetch conceptually; in practice after
    # Qdrant because we share the same event loop and BM25 is CPU-bound + fast.
    # BM25 hits that are NOT already in Qdrant results are hydrated with
    # score=0.0 (cosine unknown) so they can still appear in citations.
    if hybrid_enabled:
        try:
            from retrieval.bm25_index import bm25_search, BM25Hit

            bm25_hits = await bm25_search(query, top_k=top_k * 5)
            # Apply doc_id filter post-scoring — BM25 has no native pre-filter.
            # Previously this entire branch was skipped when doc_id_filter was set,
            # which silently dropped keyword matches for named entities (e.g. place
            # names, policy titles) in single-document queries.
            if doc_id_filter:
                bm25_hits = [h for h in bm25_hits if h.doc_id == doc_id_filter]
            if bm25_hits:
                # Build a shim list that looks like Qdrant ScoredPoints so RRF
                # can process them uniformly.
                class _BM25Shim:
                    """Thin wrapper making BM25Hit look like a Qdrant ScoredPoint."""
                    __slots__ = ("score", "payload", "_rrf_score")
                    def __init__(self, hit: "BM25Hit") -> None:
                        self.score   = hit.bm25_score   # used only as tie-breaker; overridden by cosine after hydration
                        self.payload = {
                            "doc_id":   hit.doc_id,
                            "page_num": hit.page_num,
                            "page":     hit.page_num,
                            "text":     hit.text,
                            "_bm25_only": True,     # flag for post-RRF hydration
                            "_bm25_score": hit.bm25_score,
                        }
                        self._rrf_score = 0.0

                bm25_shims = [_BM25Shim(h) for h in bm25_hits]
                collection_result_lists.append(bm25_shims)
        except Exception as exc:
            logger.warning("bm25_search_failed", error=str(exc))

    if not collection_result_lists:
        logger.info("search_no_results", query=query[:80], threshold=score_threshold)
        return []

    # ── RRF merge ──────────────────────────────────────────────────────────────
    # Each collection's hits are ranked within their own list before fusion.
    # Result: sorted by RRF score; .score on each hit is still original cosine.
    merged_hits = _apply_rrf(collection_result_lists, k=_RRF_K)

    # ── Debug log: top-5 raw cosine vs top-5 RRF ──────────────────────────────
    # Flatten all raw hits for comparison.
    all_raw = [h for lst in collection_result_lists for h in lst]
    all_raw.sort(key=lambda h: h.score, reverse=True)
    top5_raw = [(h.payload.get("doc_id", "")[:8], round(h.score, 4)) for h in all_raw[:5]]
    top5_rrf = [(h.payload.get("doc_id", "")[:8], round(getattr(h, "_rrf_score", 0.0), 5)) for h in merged_hits[:5]]
    logger.debug(
        "rrf_vs_raw_top5",
        top5_raw=top5_raw,
        top5_rrf=top5_rrf,
        collections=len(collection_result_lists),
    )

    # ── Hydrate BM25-only hits with cosine score=0.0 ──────────────────────────
    # After RRF ordering, replace BM25-only shim .score with 0.0 so the
    # SearchResult carries a meaningful "cosine unknown" signal to the user.
    for hit in merged_hits:
        if hit.payload.get("_bm25_only"):
            hit.score = 0.0   # cosine unknown for keyword-only matches

    # ── MMR diversity pass ────────────────────────────────────────────────────
    # merged_hits is already sorted by RRF score; MMR uses .score (cosine) for
    # threshold checks but relies on the pre-sorted order for guaranteed slots.
    diverse_hits = _apply_mmr_diversity(
        merged_hits,
        top_k,
        score_threshold = score_threshold,
        soft_threshold  = soft_threshold,
    )

    results = []
    for hit in diverse_hits:
        p = hit.payload
        # V2 payloads use "summary_text"; V3/Confluence/BM25 payloads use "text"
        text = p.get("summary_text") or p.get("text", "")
        results.append(SearchResult(
            doc_id       = p.get("doc_id", ""),
            page_num     = p.get("page", p.get("page_num", 0)),
            filename     = p.get("filename", ""),
            source_type  = p.get("source_type", ""),
            score        = hit.score,   # cosine similarity (0.0 for BM25-only hits)
            summary_text = text,
            headers      = p.get("headers", ""),
            has_tables   = bool(p.get("has_tables", False)),
        ))

    logger.info(
        "search_complete",
        query=query[:80],
        hits_raw=len(all_raw),
        hits_after_rrf=len(merged_hits),
        hits_after_mmr=len(results),
        collections=len(collection_result_lists),
    )
    return results
