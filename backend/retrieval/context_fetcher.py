"""
LAKO V2 — Context Fetcher

For each Qdrant search result, fetches the matched page's raw text from
SQLite plus ±buffer_pages neighbours.  Deduplicates overlapping windows,
sorts by (doc_id, page_num), and returns an AssembledContext ready for
the budget manager.
"""

import logging
from typing import Optional

import structlog

from db.document_store import get_document, get_page_by_num
from retrieval.models import AssembledContext, PageContent, SearchResult

logger = structlog.get_logger(__name__)


async def fetch_context(
    search_results: list[SearchResult],
    buffer_pages:   int = 1,
) -> AssembledContext:
    """
    Fetch raw pages from SQLite for all search results, plus buffer neighbours.

    Strategy:
      • For each SearchResult, determine the window
            [page_num - buffer_pages, page_num + buffer_pages]
        clamped to [1, doc.total_pages].
      • Track each page as direct_match (returned by Qdrant) or buffer.
      • If a page appears in multiple windows, keep it once; prefer the
        is_direct_match flag and the highest associated score.
      • Sort all collected pages by (doc_id, page_num).

    Returns AssembledContext with pages, token estimate, and source list.
    """
    if not search_results:
        return AssembledContext(pages=[], total_tokens=0, sources=[])

    # ── Preload total_pages per document (one DB call per unique doc_id) ───────
    doc_total_pages: dict[str, int] = {}
    for sr in search_results:
        if sr.doc_id not in doc_total_pages:
            doc = await get_document(sr.doc_id)
            doc_total_pages[sr.doc_id] = doc["total_pages"] if doc else 9999

    # ── Collect page slots ─────────────────────────────────────────────────────
    # Key: (doc_id, page_num)
    # Value: {"is_direct": bool, "score": float}
    slots: dict[tuple[str, int], dict] = {}

    for sr in search_results:
        total = doc_total_pages[sr.doc_id]
        lo    = max(1, sr.page_num - buffer_pages)
        hi    = min(total, sr.page_num + buffer_pages)

        for pn in range(lo, hi + 1):
            key          = (sr.doc_id, pn)
            is_direct    = pn == sr.page_num
            existing     = slots.get(key)

            if existing is None:
                slots[key] = {"is_direct": is_direct, "score": sr.score}
            else:
                # A page already claimed: upgrade to direct if applicable,
                # keep highest score.
                slots[key]["is_direct"] = existing["is_direct"] or is_direct
                slots[key]["score"]     = max(existing["score"], sr.score)

    # ── Fetch raw text from SQLite ─────────────────────────────────────────────
    pages: list[PageContent] = []
    filenames: dict[str, str] = {sr.doc_id: sr.filename for sr in search_results}

    for (doc_id, page_num), meta in sorted(slots.items()):
        row = await get_page_by_num(doc_id, page_num)
        if row is None:
            logger.debug("buffer_page_missing", doc_id=doc_id, page_num=page_num)
            continue

        pages.append(PageContent(
            doc_id          = doc_id,
            filename        = filenames.get(doc_id, row.get("filename", "")),
            page_num        = page_num,
            raw_text        = row["raw_text"],
            is_direct_match = meta["is_direct"],
            score           = meta["score"],
        ))

    # ── Compute token estimate and sources ─────────────────────────────────────
    total_tokens = sum(len(p.raw_text) for p in pages) // 4

    seen_sources: set[str] = set()
    sources: list[dict]    = []
    for sr in search_results:
        if sr.doc_id not in seen_sources:
            seen_sources.add(sr.doc_id)
            sources.append({
                "doc_id":   sr.doc_id,
                "filename": sr.filename,
                "page_num": sr.page_num,
                "score":    round(sr.score, 4),
            })

    logger.info(
        "context_fetched",
        results=len(search_results),
        pages_fetched=len(pages),
        total_tokens=total_tokens,
    )
    return AssembledContext(pages=pages, total_tokens=total_tokens, sources=sources)
