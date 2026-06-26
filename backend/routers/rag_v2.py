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
import re
import time
from typing import Optional

import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from cache import embedding_cache, query_cache
from config import get_ollama_runtime_options
from retrieval.budget_manager import apply_budget
from retrieval.context_fetcher import fetch_context
from retrieval.models import QueryRequest, SearchResult
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


def _sse_done(
    sources: list,
    timing: Optional[dict] = None,
    retrieval_warning: Optional[dict] = None,
) -> str:
    payload: dict = {"token": "", "done": True, "sources": sources}
    if timing:
        payload["timing"] = timing
    if retrieval_warning:
        payload["retrieval_warning"] = retrieval_warning
    return _sse(payload)


# ── Retrieval miss detection ────────────────────────────────────────────────────

_MISSING_PHRASES_EN = (
    "missing from", "not contain", "not in the provided",
    "cannot provide", "is not present", "no mention",
)
_MISSING_PHRASES_NL = (
    "geen informatie", "niet beschikbaar", "niet aanwezig",
    "kan ik niet", "ontbreekt",
)


def _detect_retrieval_miss(
    query: str,
    answer: str,
    context_pages: list,
) -> Optional[dict]:
    """
    Heuristically detect when the LLM signals a retrieval miss.

    Returns a warning dict if the answer contains missing-information phrases
    AND at least one query token is absent from the retrieved context.
    Returns None when no miss is detected.

    Args:
        query:         The user's original question.
        answer:        The full LLM response text.
        context_pages: List of PageContent objects from the assembled context.
    """
    answer_lower = answer.lower()
    phrases = _MISSING_PHRASES_EN + _MISSING_PHRASES_NL
    if not any(p in answer_lower for p in phrases):
        return None

    # Pull capitalised acronyms (3+ chars) and words 4+ chars from the query
    query_tokens = set(re.findall(r"\b[A-Z]{3,}\b|\b[A-Za-z]{4,}\b", query))
    if not query_tokens:
        return None

    retrieved = " ".join(
        getattr(p, "raw_text", "") for p in context_pages
    ).lower()
    missing = sorted(t for t in query_tokens if t.lower() not in retrieved)
    if not missing:
        return None

    return {
        "type": "retrieval_miss_suspected",
        "missing_tokens": missing,
        "suggestion": (
            "These terms from your query did not appear in the retrieved "
            "chunks. The answer may exist elsewhere in your documents but "
            "wasn't selected by retrieval. Consider rephrasing or filtering "
            "to a specific document."
        ),
    }


def _sse_error(message: str) -> str:
    return _sse({"token": "", "done": True, "error": message, "sources": []})


# ── Think-tag stream filter ────────────────────────────────────────────────────

class _ThinkStripper:
    """
    Buffer-based filter that removes <think>…</think> blocks from a streaming
    token output. Qwen3 with think=True emits chain-of-thought reasoning inside
    <think> tags before producing the visible answer. This class discards those
    tokens so only the answer reaches the SSE stream.

    The buffer keeps a small tail equal to the length of the opening/closing tag
    minus one, so a tag split across two adjacent tokens is always caught.
    """
    _OPEN  = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._in_think: bool = False
        self._buf:      str  = ""

    def feed(self, token: str) -> str:
        """Return the visible portion of *token* (empty string during think block)."""
        self._buf += token
        output = ""

        while self._buf:
            if self._in_think:
                idx = self._buf.find(self._CLOSE)
                if idx != -1:
                    self._in_think = False
                    # Skip the closing tag and any immediate leading newline
                    self._buf = self._buf[idx + len(self._CLOSE):].lstrip("\n")
                else:
                    keep = len(self._CLOSE) - 1
                    if len(self._buf) > keep:
                        self._buf = self._buf[-keep:]
                    break
            else:
                idx = self._buf.find(self._OPEN)
                if idx != -1:
                    output += self._buf[:idx]
                    self._in_think = True
                    self._buf = self._buf[idx + len(self._OPEN):]
                else:
                    keep = len(self._OPEN) - 1
                    if len(self._buf) > keep:
                        output += self._buf[:-keep]
                        self._buf = self._buf[-keep:]
                    break

        return output

    def flush(self) -> str:
        """Flush any buffered content at end-of-stream."""
        if not self._in_think:
            out, self._buf = self._buf, ""
            return out
        return ""


# ── Multi-topic query helpers ──────────────────────────────────────────────────

def _is_multi_topic(query: str) -> bool:
    """
    Detect if a query spans multiple independent topics.
    Triggers decomposition when there are multiple explicit questions, or when
    the query is long with 3+ 'and' connectors (compound topic coverage).
    """
    if query.count("?") >= 2:
        return True
    if len(query) > 100 and len(re.findall(r"\band\b", query, re.IGNORECASE)) >= 3:
        return True
    return False


async def _decompose_query(query: str) -> list[str]:
    """
    Use the LLM to split a complex multi-topic query into 2–4 focused sub-queries.
    Each sub-query targets a single topic so its embedding is tight and precise.
    Falls back to [query] on LLM error or malformed output.
    """
    from services.ollama_client import ollama_client

    prompt = (
        "Split this question into 2-4 focused sub-queries, one per line.\n"
        "Each sub-query must target exactly one topic from the original question.\n"
        "Output ONLY the sub-queries — no numbering, no bullets, no explanation.\n\n"
        f"Question: {query}"
    )
    system = (
        "You are a search query decomposition assistant. "
        "Output only the sub-queries, one per line, nothing else."
    )
    try:
        response = await ollama_client.chat(prompt, system=system)
        lines = [l.strip() for l in response.strip().splitlines() if l.strip()]
        cleaned = []
        for line in lines:
            line = re.sub(r"^[\d]+[.)]\s*", "", line)
            line = re.sub(r"^[-*•]\s*", "", line).strip()
            if len(line) > 10:
                cleaned.append(line)
        if 2 <= len(cleaned) <= 6:
            logger.info("query_decomposed", subs=[s[:60] for s in cleaned])
            return cleaned
    except Exception as exc:
        logger.warning("query_decompose_failed", error=str(exc))
    return [query]


async def _multi_topic_search(
    sub_queries:     list[str],
    sub_vectors:     list,
    top_k:           int,
    score_threshold: float,
    doc_id_filter:   Optional[str],
) -> list[SearchResult]:
    """
    Search independently per sub-query, merge results by best score per page.
    Uses top_k * 2 per sub-query for wide candidate coverage before the merge.
    The score_threshold is applied after merging so borderline-relevant pages
    from minority sub-topics aren't dropped before combination.
    """
    per_sq: list[list[SearchResult]] = await asyncio.gather(*[
        search_pages(
            query           = sq,
            top_k           = top_k * 2,
            score_threshold = 0.0,          # threshold applied after merge
            doc_id_filter   = doc_id_filter,
            query_vector    = sv,
        )
        for sq, sv in zip(sub_queries, sub_vectors)
    ])

    # Merge: keep best score per (doc_id, page_num) across all sub-query results
    best: dict[tuple, SearchResult] = {}
    for results in per_sq:
        for sr in results:
            key = (sr.doc_id, sr.page_num)
            if key not in best or sr.score > best[key].score:
                best[key] = sr

    return sorted(
        [sr for sr in best.values() if sr.score >= score_threshold],
        key=lambda x: x.score,
        reverse=True,
    )


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

    # ── Query decomposition + think mode detection ─────────────────────────────
    # A single embedding for a compound question is a semantic average that
    # drifts toward synthesis/conclusion pages rather than each topic's source
    # pages.  Decompose into sub-queries so each gets a tight, focused embedding.
    # Multi-topic queries also get think=True so Qwen3 reasons across chapters
    # before answering; <think> tags are stripped from the SSE stream below.
    use_thinking  = _is_multi_topic(request.query)
    sub_queries   = [request.query]
    sub_vectors   = [vector]
    if use_thinking:
        decomposed = await _decompose_query(request.query)
        if len(decomposed) > 1:
            sub_queries = decomposed
            raw_vecs = await asyncio.gather(*[
                ollama_client.embed(sq) for sq in sub_queries
            ])
            sub_vectors = list(raw_vecs)
            for sq, sv in zip(sub_queries, sub_vectors):
                asyncio.create_task(embedding_cache.put(sq, sv))

    # ── Vector search ──────────────────────────────────────────────────────────
    t1 = time.perf_counter()
    try:
        from config import get_config
        cfg             = get_config()
        score_threshold = cfg.get("similarity_threshold", 0.25)
        top_k           = cfg.get("top_k", 8)
        buffer_pages    = cfg.get("buffer_pages", 1)
        if len(sub_queries) == 1:
            search_results = await search_pages(
                query           = request.query,
                top_k           = top_k,
                score_threshold = score_threshold,
                doc_id_filter   = request.doc_id,
                query_vector    = vector,
            )
        else:
            search_results = await _multi_topic_search(
                sub_queries     = sub_queries,
                sub_vectors     = sub_vectors,
                top_k           = top_k,
                score_threshold = score_threshold,
                doc_id_filter   = request.doc_id,
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
    assembled = await fetch_context(search_results, buffer_pages=buffer_pages)
    timing["fetch_ms"] = round((time.perf_counter() - t2) * 1000)

    # ── Prompt assembly ────────────────────────────────────────────────────────
    t3 = time.perf_counter()
    trimmed = await apply_budget(assembled)
    user_prompt, system_prompt = build_query_prompt(
        request.query, trimmed, request.language
    )
    timing["assembly_ms"] = round((time.perf_counter() - t3) * 1000)

    # ── LLM stream ─────────────────────────────────────────────────────────────
    # For multi-topic queries, enable Qwen3 chain-of-thought (think=True) so the
    # model can reason across retrieved chapters before answering.  The stripper
    # removes the <think>…</think> block from the SSE stream — the user only sees
    # the final answer while still getting the quality benefit of CoT reasoning.
    response_tokens: list[str] = []
    first_token     = True
    t_llm           = time.perf_counter()
    stripper        = _ThinkStripper() if use_thinking else None

    try:
        async for token in ollama_client.stream_chat(
            prompt = user_prompt,
            system = system_prompt,
            think  = True if use_thinking else None,
        ):
            if stripper:
                token = stripper.feed(token)
                if not token:
                    continue
            if first_token:
                timing["llm_first_token_ms"] = round(
                    (time.perf_counter() - t_llm) * 1000
                )
                first_token = False
            response_tokens.append(token)
            yield _sse_token(token)

        # Flush any tail the stripper held back waiting for a partial tag
        if stripper:
            tail = stripper.flush()
            if tail:
                response_tokens.append(tail)
                yield _sse_token(tail)

    except Exception as exc:
        logger.error("rag_llm_stream_failed", error=str(exc))
        yield _sse_error(f"AI engine error: {exc}")
        return

    timing["llm_total_ms"] = round((time.perf_counter() - t_llm) * 1000)
    full_response = "".join(response_tokens)
    logger.info("rag_query_timing", query=request.query[:80], **timing)

    # ── Retrieval miss detection (advisory — does not block response) ──────────
    retrieval_warning = _detect_retrieval_miss(
        request.query, full_response, trimmed.pages
    )
    if retrieval_warning:
        logger.warning(
            "retrieval_miss_suspected",
            query=request.query[:80],
            missing_tokens=retrieval_warning["missing_tokens"],
            doc_ids=[s.get("doc_id") for s in trimmed.sources],
        )

    # ── Final event with sources + timing ──────────────────────────────────────
    yield _sse_done(trimmed.sources, timing=timing, retrieval_warning=retrieval_warning)

    # ── Async cache store (non-blocking) ──────────────────────────────────────
    if use_cache and full_response:
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
