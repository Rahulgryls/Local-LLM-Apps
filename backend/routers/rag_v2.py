"""
LAKO V2 — RAG Query Router

POST /api/v2/query

Request body (JSON):
  query        — user question (string, required)
  language     — "en" | "nl"  (default "en")
  rag_enabled  — true = search documents; false = web search (default true)
  doc_id       — optional UUID to restrict search to one document

SSE streaming response format:
  data: {"token": "<chunk>", "done": false}   — one per LLM token
  data: {"token": "", "done": true, "sources": [...], "timing": {...}}  — final event

Sources list item:
  {doc_id, filename, page_num, score}   (RAG mode)
  {title, url}                          (web mode)

Session 4 additions:
  - Query cache: LRU 50, 1-hour TTL. Skip for doc_id-filtered queries.
  - Embedding cache: avoids re-calling Ollama embed for the same query text.
  - Per-step timing: embedding_ms, search_ms, fetch_ms, assembly_ms,
    llm_first_token_ms, llm_total_ms — included in the final SSE event.
  - Cache invalidation: handled by ingest_v2 calling query_cache.clear().
"""

import asyncio
import json
import time
from typing import Optional

import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from cache import embedding_cache, query_cache
from config import get_ollama_runtime_options
from retrieval.budget_manager import apply_budget
from retrieval.context_fetcher import fetch_context
from retrieval.models import QueryRequest
from retrieval.prompt_builder import build_query_prompt, build_web_prompt
from retrieval.searcher import search_pages
from retrieval.web_searcher import web_search

logger = structlog.get_logger(__name__)
router = APIRouter()

# Chunk size for streaming cached responses (maintains typewriter feel)
_CACHE_CHUNK = 40


# ── SSE helpers ────────────────────────────────────────────────────────────────

def _sse(payload: dict) -> str:
    """Format a dict as a single SSE event (data: ...\n\n)."""
    return f"data: {json.dumps(payload)}\n\n"


def _sse_token(token: str) -> str:
    return _sse({"token": token, "done": False})


def _sse_done(sources: list, timing: Optional[dict] = None) -> str:
    payload: dict = {"token": "", "done": True, "sources": sources}
    if timing:
        payload["timing"] = timing
    return _sse(payload)


def _sse_error(message: str) -> str:
    return _sse({"token": "", "done": True, "error": message, "sources": []})


# ── RAG streaming pipeline ─────────────────────────────────────────────────────

async def _stream_rag(request: QueryRequest):
    """Async generator: full RAG pipeline → SSE token stream, with timing and cache."""
    from services.ollama_client import ollama_client

    _rt = get_ollama_runtime_options()
    logger.info(
        "rag_query_runtime",
        num_ctx=_rt["options"]["num_ctx"],
        keep_alive=_rt["keep_alive"],
        think=_rt["think"],
        query=request.query[:80],
    )

    timing: dict = {}

    # ── Cache check (skip for doc_id-filtered queries) ─────────────────────────
    use_cache = not request.doc_id
    if use_cache:
        cached = await query_cache.get(request.query)
        if cached:
            logger.info("query_cache_hit", query=request.query[:80])
            response_text = cached["response"]
            for i in range(0, len(response_text), _CACHE_CHUNK):
                yield _sse_token(response_text[i : i + _CACHE_CHUNK])
            yield _sse_done(cached["sources"], timing={"cache_hit": True})
            return

    # ── Embed query with cache ─────────────────────────────────────────────────
    t0 = time.perf_counter()
    try:
        vector = await embedding_cache.get(request.query)
        if vector is None:
            vector = await ollama_client.embed(request.query)
            await embedding_cache.put(request.query, vector)
        timing["embedding_ms"] = round((time.perf_counter() - t0) * 1000)
    except Exception as exc:
        logger.error("embed_failed", error=str(exc))
        yield _sse_error(f"Embedding unavailable: {exc}")
        return

    # ── Vector search ──────────────────────────────────────────────────────────
    t1 = time.perf_counter()
    try:
        from config import get_config
        cfg             = get_config()
        score_threshold = cfg.get("similarity_threshold", 0.25)
        top_k           = cfg.get("top_k", 8)
        search_results = await search_pages(
            query              = request.query,
            top_k              = top_k,
            score_threshold    = score_threshold,
            doc_id_filter      = request.doc_id,
            query_vector       = vector,
        )
        timing["search_ms"] = round((time.perf_counter() - t1) * 1000)
    except Exception as exc:
        logger.error("rag_search_failed", error=str(exc))
        yield _sse_error(f"Search index unavailable: {exc}")
        return

    # No relevant results
    if not search_results:
        no_results_msg = (
            "Ik kon geen relevante informatie in uw documenten vinden voor deze vraag. "
            "Probeer de vraag anders te formuleren of schakel over naar webzoeken."
            if request.language.startswith("nl") else
            "I couldn't find relevant information in your documents for this question. "
            "Try rephrasing or switching to web search."
        )
        yield _sse_error(no_results_msg)
        return

    # ── Context fetch + budget trimming ───────────────────────────────────────
    t2 = time.perf_counter()
    assembled = await fetch_context(search_results, buffer_pages=0)
    timing["fetch_ms"] = round((time.perf_counter() - t2) * 1000)

    # ── Prompt assembly ────────────────────────────────────────────────────────
    t3 = time.perf_counter()
    trimmed = await apply_budget(assembled)
    user_prompt, system_prompt = build_query_prompt(
        request.query, trimmed, request.language
    )
    timing["assembly_ms"] = round((time.perf_counter() - t3) * 1000)

    # ── LLM stream ─────────────────────────────────────────────────────────────
    response_tokens: list[str] = []
    first_token     = True
    t_llm           = time.perf_counter()

    try:
        async for token in ollama_client.stream_chat(
            prompt = user_prompt,
            system = system_prompt,
        ):
            if first_token:
                timing["llm_first_token_ms"] = round(
                    (time.perf_counter() - t_llm) * 1000
                )
                first_token = False
            response_tokens.append(token)
            yield _sse_token(token)
    except Exception as exc:
        logger.error("rag_llm_stream_failed", error=str(exc))
        yield _sse_error(f"AI engine error: {exc}")
        return

    timing["llm_total_ms"] = round((time.perf_counter() - t_llm) * 1000)
    logger.info("rag_query_timing", query=request.query[:80], **timing)

    # ── Final event with sources + timing ──────────────────────────────────────
    yield _sse_done(trimmed.sources, timing=timing)

    # ── Async cache store (non-blocking) ──────────────────────────────────────
    if use_cache and response_tokens:
        full_response = "".join(response_tokens)
        asyncio.create_task(
            query_cache.put(
                request.query,
                {"response": full_response, "sources": trimmed.sources},
            )
        )


# ── Web-search streaming pipeline ─────────────────────────────────────────────

async def _stream_web(request: QueryRequest):
    """Async generator: SearXNG → LLM summarise → SSE token stream."""
    from services.ollama_client import ollama_client

    _rt = get_ollama_runtime_options()
    logger.info(
        "web_query_runtime",
        num_ctx=_rt["options"]["num_ctx"],
        keep_alive=_rt["keep_alive"],
        think=_rt["think"],
        query=request.query[:80],
    )

    web_results = await web_search(request.query, num_results=5)

    if not web_results:
        unavailable_msg = (
            "Webzoeken is niet beschikbaar. "
            "Schakel over naar documentzoeken of controleer of SearXNG actief is."
            if request.language.startswith("nl") else
            "Web search is unavailable. "
            "Switch to document search or check that SearXNG is running."
        )
        yield _sse_error(unavailable_msg)
        return

    user_prompt, system_prompt = build_web_prompt(
        request.query, web_results, request.language
    )

    timing: dict = {}
    t_llm     = time.perf_counter()
    first_tok = True

    try:
        async for token in ollama_client.stream_chat(
            prompt = user_prompt,
            system = system_prompt,
        ):
            if first_tok:
                timing["llm_first_token_ms"] = round(
                    (time.perf_counter() - t_llm) * 1000
                )
                first_tok = False
            yield _sse_token(token)
    except Exception as exc:
        logger.error("web_llm_stream_failed", error=str(exc))
        yield _sse_error(f"AI engine error: {exc}")
        return

    timing["llm_total_ms"] = round((time.perf_counter() - t_llm) * 1000)

    sources = [{"title": r.title, "url": r.url} for r in web_results]
    yield _sse_done(sources, timing=timing)


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post(
    "/v2/query",
    summary="Streaming RAG or web-search query (V2)",
    tags=["V2 RAG"],
    response_class=StreamingResponse,
)
async def query(request: QueryRequest):
    """
    Stream a question-answering response over SSE.

    - **rag_enabled=true**  → embed query → Qdrant search → fetch SQLite pages → stream answer
    - **rag_enabled=false** → query SearXNG → stream web-grounded answer
    - **doc_id** (optional) → restrict RAG search to one document (bypasses query cache)
    - **language** "en"|"nl" → response language

    Each SSE event is `data: {JSON}\\n\\n`.
    The final event has `"done": true`, a `"sources"` list, and a `"timing"` dict.
    """
    log = logger.bind(
        query    = request.query[:80],
        language = request.language,
        rag      = request.rag_enabled,
        doc_id   = request.doc_id,
    )
    log.info("query_received")

    generator = _stream_rag(request) if request.rag_enabled else _stream_web(request)

    return StreamingResponse(
        generator,
        media_type = "text/event-stream",
        headers    = {
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if proxied
        },
    )
