"""
LAKO V2 — Page Summarizer (Pass 2)

Calls Ollama to generate a 2-3 sentence summary for each page.
Uses the primary_model from config with temperature=0.1, num_ctx=8192.

Edge cases:
  • Empty pages (< 50 chars)  → stored as "[Empty page]"
  • Pages > 6000 chars        → truncated before sending, note appended
  • LLM timeout / error       → one retry, then "[Summarization failed]"

Session 4:
  • _call_ollama uses the shared httpx client (connection pooling)
  • summarize_batch() batches up to 3 pages per Ollama call (~3× faster ingestion)
"""

import logging
from typing import Optional

import httpx
import structlog

from config import get_config, get_ollama_runtime_options
from db.document_store import insert_page_summary

logger = structlog.get_logger(__name__)

_EMPTY_MARKER   = "[Empty page]"
_FAILED_MARKER  = "[Summarization failed]"
_MAX_CHARS      = 6_000
_BATCH_SEP      = "---PAGE_BREAK---"
_MAX_SUMMARY    = 1_500   # hard cap on stored/embedded summary length


import re as _re

def _clean_summary(text: str, page_num: int) -> str:
    """
    Strip echoed page headers/separators that small models sometimes include,
    then hard-cap the result at _MAX_SUMMARY characters.
    """
    # Remove lines like "=== Page 12 ===" or "--- PAGE_BREAK ---"
    text = _re.sub(r'={2,}.*?={2,}', '', text)
    text = _re.sub(r'-{3,}.*?-{3,}', '', text)
    # Remove "Page N:" or "Page N\n" prefixes
    text = _re.sub(r'(?i)^page\s+\d+[:\s]*', '', text.strip())
    text = text.strip()
    if len(text) > _MAX_SUMMARY:
        text = text[:_MAX_SUMMARY].rsplit(' ', 1)[0] + '…'
    return text or _FAILED_MARKER


def _build_prompt(
    raw_text: str,
    page_num: int,
    total_pages: int,
    headers: list[str],
    doc_name: str,
) -> str:
    total_str   = f" of {total_pages}" if total_pages else ""
    headers_str = ", ".join(headers) if headers else "none"
    return (
        "Summarize this page in 2-3 sentences. "
        "Preserve: key entities, numbers, policy names, decisions, and "
        "relationships between concepts. "
        "Be specific — use names, dates, and figures from the text.\n\n"
        f"Document: {doc_name}\n"
        f"Page {page_num}{total_str}\n"
        f"Headers on this page: {headers_str}\n"
        "---\n"
        f"{raw_text}"
    )


async def _call_ollama(prompt: str) -> str:
    """POST to Ollama /api/generate via the shared connection-pooled client."""
    from services.http_client import get_ollama_http_client
    config = get_config()
    # Use summarization_model if configured — a small/fast model is ideal here.
    # Falls back to primary_model if the field is empty.
    model = config.get("summarization_model") or config["primary_model"]
    rt = get_ollama_runtime_options()
    body = {
        "model":      model,
        "prompt":     prompt,
        "stream":     False,
        "options":    rt["options"],
        "keep_alive": rt["keep_alive"],
        "think":      rt["think"],
    }
    client = get_ollama_http_client()
    r = await client.post(f"{config['ollama_url']}/api/generate", json=body)
    r.raise_for_status()
    return r.json().get("response", "").strip()


async def summarize_page(
    doc_id:      str,
    page_num:    int,
    raw_text:    str,
    headers:     list[str],
    doc_name:    str,
    total_pages: int = 0,
) -> str:
    """
    Generate and persist a 2-3 sentence summary for a single page.

    Returns the summary text (one of the edge-case markers if applicable).
    The result is always written to page_summaries before returning.
    """
    # ── Edge case: empty / scanned page ───────────────────────────────────────
    if len(raw_text.strip()) < 50:
        await insert_page_summary(doc_id, page_num, _EMPTY_MARKER)
        return _EMPTY_MARKER

    # ── Truncate very long pages ──────────────────────────────────────────────
    text = raw_text
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + "\n(truncated)"
        logger.debug(
            "page_text_truncated",
            doc_id=doc_id, page_num=page_num,
            original_len=len(raw_text),
        )

    prompt  = _build_prompt(text, page_num, total_pages, headers, doc_name)
    summary = _FAILED_MARKER

    # ── LLM call with one retry ───────────────────────────────────────────────
    for attempt in range(2):
        try:
            result = await _call_ollama(prompt)
            if result:
                summary = result
                break
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning(
                "summarize_timeout",
                doc_id=doc_id, page_num=page_num,
                attempt=attempt, error=str(exc),
            )
        except Exception as exc:
            logger.error(
                "summarize_error",
                doc_id=doc_id, page_num=page_num, error=str(exc),
            )
            break   # non-transient error — don't retry

    if summary not in (_FAILED_MARKER, _EMPTY_MARKER):
        summary = _clean_summary(summary, page_num)
    await insert_page_summary(doc_id, page_num, summary)
    return summary


# ── Batch summarization (Session 4) ───────────────────────────────────────────

async def summarize_batch(
    pages: list[dict],
) -> list[str]:
    """
    Summarise up to 3 pages in a single Ollama call.

    Each entry in *pages* must have keys:
        doc_id, page_num, raw_text, headers (list[str]),
        doc_name, total_pages (int)

    Returns a list of summary strings in the same order as *pages*.
    Falls back to per-page summarization on LLM parse failure.
    Writes every summary to page_summaries before returning.
    """
    if not pages:
        return []
    if len(pages) == 1:
        p = pages[0]
        result = await summarize_page(
            doc_id      = p["doc_id"],
            page_num    = p["page_num"],
            raw_text    = p["raw_text"],
            headers     = p["headers"],
            doc_name    = p["doc_name"],
            total_pages = p["total_pages"],
        )
        return [result]

    # ── Handle empty pages immediately (no LLM call needed) ───────────────────
    # Split pages into those needing LLM and those already handled
    needs_llm:   list[dict] = []
    pre_handled: dict[int, str] = {}   # page_num → marker

    for p in pages:
        if len(p["raw_text"].strip()) < 50:
            await insert_page_summary(p["doc_id"], p["page_num"], _EMPTY_MARKER)
            pre_handled[p["page_num"]] = _EMPTY_MARKER
        else:
            needs_llm.append(p)

    if not needs_llm:
        return [pre_handled[p["page_num"]] for p in pages]

    # ── Build batch prompt ─────────────────────────────────────────────────────
    sections = []
    for p in needs_llm:
        text = p["raw_text"]
        if len(text) > _MAX_CHARS:
            text = text[:_MAX_CHARS] + "\n(truncated)"
        sections.append(f"=== Page {p['page_num']} ===\n{text}")

    batch_prompt = (
        "Summarize each of the following pages in 2-3 sentences each. "
        "Preserve: key entities, numbers, policy names, decisions, and "
        "relationships between concepts. "
        f"Return summaries separated by {_BATCH_SEP}\n\n"
        + "\n\n".join(sections)
    )

    raw = _FAILED_MARKER
    for attempt in range(2):
        try:
            raw = await _call_ollama(batch_prompt)
            if raw:
                break
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning(
                "batch_summarize_timeout",
                attempt=attempt,
                pages=[p["page_num"] for p in needs_llm],
                error=str(exc),
            )
        except Exception as exc:
            logger.error("batch_summarize_error", error=str(exc))
            break

    # ── Parse and persist ──────────────────────────────────────────────────────
    parts = [s.strip() for s in raw.split(_BATCH_SEP)]
    llm_summaries: dict[int, str] = {}

    for i, p in enumerate(needs_llm):
        if i < len(parts) and parts[i] and parts[i] != _FAILED_MARKER:
            summary = _clean_summary(parts[i], p["page_num"])
        else:
            summary = _FAILED_MARKER
        await insert_page_summary(p["doc_id"], p["page_num"], summary)
        llm_summaries[p["page_num"]] = summary

    # ── Reassemble in original page order ─────────────────────────────────────
    result = []
    for p in pages:
        if p["page_num"] in pre_handled:
            result.append(pre_handled[p["page_num"]])
        else:
            result.append(llm_summaries[p["page_num"]])

    return result
