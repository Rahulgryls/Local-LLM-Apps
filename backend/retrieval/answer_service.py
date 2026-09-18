"""
LAKO — Non-Streaming Answer Service

Mirrors routers/rag_v2.py's _stream_rag()/_stream_web() step-for-step
(contextualize → embed → search → fetch_context → apply_budget → build
prompt), but returns one finished answer instead of an SSE token stream.
Used by the MCP server, where a tool call needs a single JSON result rather
than a token stream.

No query-cache use here — same reasoning already applied to the SSE path
when `history` is present: a cached answer from one conversation shouldn't
be replayed into a different one just because the raw question text matches.
"""

import asyncio
import re
import time
from typing import Optional

import structlog

from cache import embedding_cache
from retrieval.budget_manager import apply_budget
from retrieval.context_fetcher import fetch_context
from retrieval.models import Message
from retrieval.prompt_builder import build_query_prompt, build_web_prompt
from retrieval.query_processing import (
    contextualize_query,
    decompose_query,
    is_multi_topic,
    multi_topic_search,
)
from retrieval.searcher import search_pages
from retrieval.web_searcher import web_search

logger = structlog.get_logger(__name__)

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _strip_think(text: str) -> str:
    """Non-streaming counterpart to rag_v2.py's _ThinkStripper — the full
    response is already in hand, so a single regex pass is enough."""
    return _THINK_BLOCK_RE.sub("", text)


async def _answer_rag(
    query:       str,
    language:    str,
    doc_id:      Optional[str],
    history:     list[Message],
) -> dict:
    from services.ollama_client import ollama_client

    timing: dict = {}

    search_query = query
    if history:
        search_query = await contextualize_query(query, history)

    t0 = time.perf_counter()
    try:
        vector = await embedding_cache.get(search_query)
        if vector is None:
            vector = await ollama_client.embed(search_query)
            await embedding_cache.put(search_query, vector)
        timing["embedding_ms"] = round((time.perf_counter() - t0) * 1000)
    except Exception as exc:
        logger.error("embed_failed", error=str(exc))
        raise RuntimeError(f"Embedding unavailable: {exc}") from exc

    use_thinking = is_multi_topic(search_query)
    sub_queries  = [search_query]
    sub_vectors  = [vector]
    if use_thinking:
        decomposed = await decompose_query(search_query)
        if len(decomposed) > 1:
            sub_queries = decomposed
            raw_vecs = await asyncio.gather(*[
                ollama_client.embed(sq) for sq in sub_queries
            ])
            sub_vectors = list(raw_vecs)
            for sq, sv in zip(sub_queries, sub_vectors):
                asyncio.create_task(embedding_cache.put(sq, sv))

    t1 = time.perf_counter()
    try:
        from config import get_config
        cfg             = get_config()
        score_threshold = cfg.get("similarity_threshold", 0.25)
        top_k           = cfg.get("top_k", 8)
        buffer_pages    = cfg.get("buffer_pages", 1)
        if len(sub_queries) == 1:
            search_results = await search_pages(
                query           = search_query,
                top_k           = top_k,
                score_threshold = score_threshold,
                doc_id_filter   = doc_id,
                query_vector    = vector,
            )
        else:
            search_results = await multi_topic_search(
                sub_queries     = sub_queries,
                sub_vectors     = sub_vectors,
                top_k           = top_k,
                score_threshold = score_threshold,
                doc_id_filter   = doc_id,
            )
        timing["search_ms"] = round((time.perf_counter() - t1) * 1000)
    except Exception as exc:
        logger.error("rag_search_failed", error=str(exc))
        raise RuntimeError(f"Search index unavailable: {exc}") from exc

    if not search_results:
        no_results_msg = (
            "Ik kon geen relevante informatie in uw documenten vinden voor deze vraag. "
            "Probeer de vraag anders te formuleren of schakel over naar webzoeken."
            if language.startswith("nl") else
            "I couldn't find relevant information in your documents for this question. "
            "Try rephrasing or switching to web search."
        )
        return {"answer": no_results_msg, "sources": [], "timing": timing}

    t2 = time.perf_counter()
    assembled = await fetch_context(search_results, buffer_pages=buffer_pages)
    timing["fetch_ms"] = round((time.perf_counter() - t2) * 1000)

    t3 = time.perf_counter()
    trimmed = await apply_budget(assembled)
    user_prompt, system_prompt = build_query_prompt(
        query, trimmed, language, history=history
    )
    timing["assembly_ms"] = round((time.perf_counter() - t3) * 1000)

    t_llm = time.perf_counter()
    try:
        raw_answer = await ollama_client.chat(
            prompt = user_prompt,
            system = system_prompt,
            think  = True if use_thinking else None,
        )
    except Exception as exc:
        logger.error("rag_llm_failed", error=str(exc))
        raise RuntimeError(f"AI engine error: {exc}") from exc
    timing["llm_total_ms"] = round((time.perf_counter() - t_llm) * 1000)

    answer = _strip_think(raw_answer).strip() if use_thinking else raw_answer
    logger.info("rag_answer_timing", query=query[:80], **timing)

    return {"answer": answer, "sources": trimmed.sources, "timing": timing}


async def _answer_web(query: str, language: str, history: list[Message]) -> dict:
    search_query = query
    if history:
        search_query = await contextualize_query(query, history)

    web_results = await web_search(search_query, num_results=5)
    if not web_results:
        unavailable_msg = (
            "Webzoeken is niet beschikbaar. "
            "Schakel over naar documentzoeken of controleer of SearXNG actief is."
            if language.startswith("nl") else
            "Web search is unavailable. "
            "Switch to document search or check that SearXNG is running."
        )
        return {"answer": unavailable_msg, "sources": [], "timing": {}}

    user_prompt, system_prompt = build_web_prompt(query, web_results, language, history=history)

    from services.ollama_client import ollama_client
    t_llm = time.perf_counter()
    try:
        answer = await ollama_client.chat(prompt=user_prompt, system=system_prompt)
    except Exception as exc:
        logger.error("web_llm_failed", error=str(exc))
        raise RuntimeError(f"AI engine error: {exc}") from exc
    timing = {"llm_total_ms": round((time.perf_counter() - t_llm) * 1000)}

    sources = [{"title": r.title, "url": r.url} for r in web_results]
    return {"answer": answer, "sources": sources, "timing": timing}


async def generate_answer(
    query:       str,
    language:    str = "en",
    rag_enabled: bool = True,
    doc_id:      Optional[str] = None,
    history:     Optional[list[Message]] = None,
) -> dict:
    """
    Non-streaming counterpart to rag_v2.py's _stream_rag()/_stream_web().

    Returns {"answer": str, "sources": list[dict], "timing": dict}.
    Raises RuntimeError with a user-facing message on embedding/search/LLM
    failure — callers (e.g. the MCP server) translate that into their own
    error-reporting shape.
    """
    history = history or []
    if rag_enabled:
        return await _answer_rag(query, language, doc_id, history)
    return await _answer_web(query, language, history)
