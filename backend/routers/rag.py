"""
LAKO — RAG Router
POST /api/rag/query      — streaming RAG (NDJSON): tokens arrive live, sources at end
POST /api/rag/query/sync — non-streaming RAG: full JSON response (for API/testing)
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Any

from services.rag_engine import rag_engine, _query_cache, invalidate_query_cache

router = APIRouter()


class RAGRequest(BaseModel):
    query: str
    model: Optional[str] = None
    top_k: Optional[int] = None
    use_rag: bool = True


class SourceChunk(BaseModel):
    filename: str
    page: int
    chunk_type: str
    score: float
    content: str


class RAGResponse(BaseModel):
    answer: str
    sources: List[SourceChunk] = []
    model: str
    rag_used: bool
    intent: Optional[str] = None            # "single" | "comparison" | "aggregation"
    sub_queries: Optional[List[str]] = None # populated for multi-doc only
    retrieval_mode: Optional[str] = None    # "standard" | "multi-doc"


@router.get("/cache/stats")
async def cache_stats():
    """Return current query-cache occupancy (V1 + V2 combined)."""
    from cache import query_cache as v2_cache
    v2_stats = v2_cache.stats()
    return {
        "cached_queries": len(_query_cache) + v2_stats["size"],
        "v1_cached":      len(_query_cache),
        "v2_cached":      v2_stats["size"],
        "max_size":       50,
        "ttl_seconds":    3600,
    }


@router.delete("/cache")
async def clear_cache():
    """Invalidate all cached RAG query results (V1 + V2)."""
    from cache import query_cache as v2_cache
    before_v1 = len(_query_cache)
    v2_before = v2_cache.stats()["size"]
    invalidate_query_cache()
    await v2_cache.clear()
    total = before_v1 + v2_before
    logging.info(f"[cache] Manually cleared {total} cached entries (v1={before_v1}, v2={v2_before})")
    return {"cleared": total, "cached_queries": 0}


@router.post("/rag/query")
async def rag_query(request: RAGRequest):
    """
    Streaming RAG endpoint — returns NDJSON stream.
    Each line is a JSON object:
      {"t":"token","v":"<token>"}  — LLM token (stream these to display)
      {"t":"sources","v":[...]}    — source citations (shown after answer)
      {"t":"error","v":"<msg>"}    — on failure

    use_rag=false: falls back to plain streaming chat (no retrieval).
    """
    if not request.use_rag:
        # Direct streaming chat — no retrieval
        from services.ollama_client import ollama_client
        from config import get_config
        import json

        effective_model = request.model or get_config()["primary_model"]

        async def direct_stream():
            try:
                async for token in ollama_client.stream_chat(
                    request.query, model=effective_model
                ):
                    yield json.dumps({"t": "token", "v": token}) + "\n"
                yield json.dumps({"t": "sources", "v": []}) + "\n"
            except Exception as exc:
                yield json.dumps({"t": "error", "v": str(exc)}) + "\n"

        return StreamingResponse(direct_stream(), media_type="application/x-ndjson")

    return StreamingResponse(
        rag_engine.stream_query(
            question=request.query,
            model=request.model,
            top_k=request.top_k,
        ),
        media_type="application/x-ndjson",
    )


@router.post("/rag/query/sync")
async def rag_query_sync(request: RAGRequest):
    """
    Non-streaming RAG — returns full JSON response.
    Useful for API clients, testing via Swagger UI.
    """
    try:
        result = await rag_engine.query(
            question=request.query,
            model=request.model,
            top_k=request.top_k,
            use_rag=request.use_rag,
        )
        return RAGResponse(
            answer=result["answer"],
            sources=[SourceChunk(**s) for s in result["sources"]],
            model=result["model"],
            rag_used=result["rag_used"],
            intent=result.get("intent"),
            sub_queries=result.get("sub_queries"),
            retrieval_mode=result.get("retrieval_mode"),
        )
    except Exception as exc:
        logging.exception("RAG sync query failed")
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "detail": "RAG query failed — check backend logs."},
        )
