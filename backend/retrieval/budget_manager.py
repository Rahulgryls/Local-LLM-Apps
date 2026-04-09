"""
LAKO V2 — Context Budget Manager

Trims the assembled context to fit within MAX_CONTEXT_TOKENS.

Trim strategy (in order, stopping as soon as budget is met):
  1. Drop buffer pages, starting from the lowest-scored result's buffers.
  2. Drop buffer pages from ALL results (keep only direct matches).
  3. Truncate the lowest-scored direct-match pages to _TRUNCATION_CHARS each.

Direct-match pages (is_direct_match=True) are NEVER fully dropped.
"""

import logging

import structlog

from retrieval.models import AssembledContext, PageContent

logger = structlog.get_logger(__name__)

MAX_CONTEXT_TOKENS = 12_000     # safe limit for 20K num_ctx (leaves ~8K for output + system prompt)
_TRUNCATION_CHARS  = 4_000      # chars to keep when truncating a direct-match page
_CHARS_PER_TOKEN   = 4          # rough estimate


def _tokens(pages: list[PageContent]) -> int:
    return sum(len(p.raw_text) for p in pages) // _CHARS_PER_TOKEN


def _clone_page(p: PageContent, raw_text: str) -> PageContent:
    """Return a copy of *p* with a different raw_text (for truncation)."""
    return PageContent(
        doc_id          = p.doc_id,
        filename        = p.filename,
        page_num        = p.page_num,
        raw_text        = raw_text,
        is_direct_match = p.is_direct_match,
        score           = p.score,
    )


async def apply_budget(assembled: AssembledContext) -> AssembledContext:
    """
    Return an AssembledContext guaranteed to be within MAX_CONTEXT_TOKENS.
    The sources list is preserved unchanged (citations are not trimmed).
    """
    if assembled.total_tokens <= MAX_CONTEXT_TOKENS:
        return assembled

    pages = list(assembled.pages)   # mutable copy

    logger.warning(
        "context_over_budget",
        total_tokens=assembled.total_tokens,
        max_tokens=MAX_CONTEXT_TOKENS,
        page_count=len(pages),
    )

    # ── Step 1: drop buffer pages lowest-score-first ──────────────────────────
    # Sort buffer pages by score ascending so we drop the least relevant first.
    buffer_pages  = sorted(
        [p for p in pages if not p.is_direct_match],
        key=lambda p: p.score,   # ascending → drop cheapest first
    )
    direct_pages  = [p for p in pages if p.is_direct_match]

    remaining_buffers = list(buffer_pages)
    while remaining_buffers and _tokens(direct_pages + remaining_buffers) > MAX_CONTEXT_TOKENS:
        dropped = remaining_buffers.pop(0)   # lowest-score buffer
        logger.debug("budget_drop_buffer", doc_id=dropped.doc_id, page_num=dropped.page_num)

    pages = direct_pages + remaining_buffers
    if _tokens(pages) <= MAX_CONTEXT_TOKENS:
        logger.info("budget_ok_after_buffer_drop", page_count=len(pages))
        return AssembledContext(
            pages        = sorted(pages, key=lambda p: (p.doc_id, p.page_num)),
            total_tokens = _tokens(pages),
            sources      = assembled.sources,
        )

    # ── Step 2: all buffers dropped, only direct matches remain ───────────────
    pages = direct_pages
    if _tokens(pages) <= MAX_CONTEXT_TOKENS:
        logger.info("budget_ok_after_all_buffers_dropped", page_count=len(pages))
        return AssembledContext(
            pages        = sorted(pages, key=lambda p: (p.doc_id, p.page_num)),
            total_tokens = _tokens(pages),
            sources      = assembled.sources,
        )

    # ── Step 3: truncate lowest-scored direct-match pages ─────────────────────
    # Sort by score ascending so we truncate the least relevant first.
    pages_sorted = sorted(pages, key=lambda p: p.score)
    truncated    = []

    for p in pages_sorted:
        if _tokens(truncated + [p]) > MAX_CONTEXT_TOKENS:
            # Truncate this page to fit
            remaining_budget = MAX_CONTEXT_TOKENS - _tokens(truncated)
            chars_allowed    = remaining_budget * _CHARS_PER_TOKEN
            chars_allowed    = min(chars_allowed, _TRUNCATION_CHARS)
            if chars_allowed > 100:
                truncated.append(_clone_page(p, p.raw_text[:chars_allowed] + "\n[truncated]"))
                logger.debug(
                    "budget_truncate_page",
                    doc_id=p.doc_id, page_num=p.page_num,
                    kept_chars=chars_allowed,
                )
            # else skip entirely (< 100 chars not worth including)
        else:
            truncated.append(p)

    final_tokens = _tokens(truncated)
    logger.warning(
        "budget_applied_truncation",
        pages_before=len(pages),
        pages_after=len(truncated),
        final_tokens=final_tokens,
    )
    return AssembledContext(
        pages        = sorted(truncated, key=lambda p: (p.doc_id, p.page_num)),
        total_tokens = final_tokens,
        sources      = assembled.sources,
    )
