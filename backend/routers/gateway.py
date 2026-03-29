"""
LAKO — REST API Gateway Router
Exposes LAKO capabilities as an authenticated REST API for internal bank systems.

All endpoints require a valid X-API-Key header.
Keys are managed via /api/admin/keys (see admin.py).

Session 10: Full implementation.
"""

import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.api_key_manager import api_key_manager
from services.rag_engine import rag_engine
from services.confluence_client import confluence_client
from services.embedder import embedder
from services.chroma_client import chroma_client
from services.bm25_index import bm25_index

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Auth dependency ──────────────────────────────────────────────────────────

async def _require_key(x_api_key: str = Header(..., alias="X-API-Key")) -> dict:
    """
    FastAPI dependency — validates X-API-Key header.
    Raises 401 if key is missing or invalid/revoked.
    """
    key_data = api_key_manager.validate_key(x_api_key)
    if not key_data:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
    return key_data


async def _require_query_permission(x_api_key: str = Header(..., alias="X-API-Key")) -> dict:
    key_data = api_key_manager.validate_key(x_api_key)
    if not key_data:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
    if not api_key_manager.check_permission(key_data, "query"):
        raise HTTPException(status_code=403, detail="This key does not have 'query' permission.")
    return key_data


async def _require_ingest_permission(x_api_key: str = Header(..., alias="X-API-Key")) -> dict:
    key_data = api_key_manager.validate_key(x_api_key)
    if not key_data:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
    if not api_key_manager.check_permission(key_data, "ingest"):
        raise HTTPException(status_code=403, detail="This key does not have 'ingest' permission.")
    return key_data


# ── Request / Response models ────────────────────────────────────────────────

class GatewayQueryRequest(BaseModel):
    question: str
    top_k: int = 3
    model: Optional[str] = None


class GatewaySource(BaseModel):
    title: str
    url: str
    source: str       # "confluence" | "document"
    chunk_type: str
    excerpt: str
    score: float


class GatewayQueryResponse(BaseModel):
    answer: str
    sources: List[GatewaySource]
    model: str
    rag_used: bool
    processing_time: float


class GatewayConfluenceRequest(BaseModel):
    url: str
    api_token: Optional[str] = None
    mock: bool = False


class GatewayConfluenceResponse(BaseModel):
    status: str
    page_title: str
    page_id: str
    chunks_indexed: int
    processing_time: float


class GatewayDocumentResponse(BaseModel):
    status: str
    filename: str
    chunks_indexed: int
    processing_time: float


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/gateway/query", response_model=GatewayQueryResponse)
async def gateway_query(request: GatewayQueryRequest, _key: dict = Depends(_require_query_permission)):
    """
    Query the LAKO knowledge base via the REST gateway.

    Requires: X-API-Key header with 'query' permission.

    Returns the RAG answer and source citations. Sources from Confluence
    include a clickable URL; PDF sources include the document title.
    """
    start = time.time()
    try:
        result = await rag_engine.query(
            question=request.question,
            model=request.model,
            top_k=request.top_k,
            use_rag=True,
        )
    except Exception as e:
        logger.exception("Gateway query failed")
        raise HTTPException(status_code=500, detail=f"RAG query failed: {e}")

    sources = [
        GatewaySource(
            title=s.get("filename", "Unknown"),
            url=s.get("url", ""),
            source=s.get("source", "document"),
            chunk_type=s.get("chunk_type", "text"),
            excerpt=s.get("content", "")[:300],
            score=s.get("score", 0.0),
        )
        for s in result.get("sources", [])
    ]

    return GatewayQueryResponse(
        answer=result["answer"],
        sources=sources,
        model=result["model"],
        rag_used=result["rag_used"],
        processing_time=round(time.time() - start, 2),
    )


@router.post("/gateway/ingest/confluence", response_model=GatewayConfluenceResponse)
async def gateway_ingest_confluence(
    request: GatewayConfluenceRequest,
    _key: dict = Depends(_require_ingest_permission),
):
    """
    Ingest a Confluence page via the REST gateway.

    Requires: X-API-Key header with 'ingest' permission.
    """
    start = time.time()
    url = request.url.strip()

    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Invalid URL.")

    try:
        page_id = confluence_client.extract_page_id(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        if request.mock:
            page_info, raw_chunks = confluence_client.generate_mock_data(url, page_id)
        else:
            page_info = await confluence_client.fetch_page(url, request.api_token)
            raw_chunks = confluence_client.parse_page_content(page_info["content"])
    except PermissionError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail=str(e))

    if not raw_chunks:
        raise HTTPException(status_code=422, detail="No content chunks found in page.")

    page_title = page_info["title"]
    embed_texts = [
        f"[Confluence: {page_title} | Section: {c['metadata']['type']}]\n{c['text']}"
        for c in raw_chunks
    ]
    embeddings = await embedder.embed_chunks(embed_texts)

    now = datetime.now(timezone.utc).isoformat()
    chroma_chunks = [
        {
            "embedding": emb,
            "document":  chunk["text"],
            "metadata": {
                "filename":   page_title,
                "page":       0,
                "chunk_type": chunk["metadata"]["type"],
                "timestamp":  now,
                "source":     "confluence",
                "url":        url,
                "title":      page_title,
                "updated":    page_info.get("updated", ""),
                "author":     page_info.get("author", ""),
            },
        }
        for chunk, emb in zip(raw_chunks, embeddings)
    ]
    chroma_client.add_chunks(chroma_chunks)
    bm25_index.mark_dirty()

    return GatewayConfluenceResponse(
        status="success",
        page_title=page_title,
        page_id=page_id,
        chunks_indexed=len(chroma_chunks),
        processing_time=round(time.time() - start, 2),
    )


@router.post("/gateway/ingest/document", response_model=GatewayDocumentResponse)
async def gateway_ingest_document(
    file: UploadFile = File(...),
    _key: dict = Depends(_require_ingest_permission),
):
    """
    Ingest a single document (PDF or TXT) via the REST gateway.

    Requires: X-API-Key header with 'ingest' permission.
    Runs synchronously — for large files, consider the UI-based ingest instead.
    """
    from pathlib import Path
    from services.parsers.pdf_parser import pdf_parser
    from services.parsers.txt_parser import txt_parser
    from services.chunker import chunker

    start = time.time()
    ext = Path(file.filename).suffix.lower()
    if ext not in (".pdf", ".txt"):
        raise HTTPException(status_code=400, detail="Only PDF and TXT supported via gateway.")

    content = await file.read()
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        parsed = pdf_parser.parse(tmp_path) if ext == ".pdf" else txt_parser.parse(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    text_blocks = []
    for pg in parsed.pages:
        if pg.text.strip():
            text_blocks.append({"text": pg.text, "page": pg.page_number})

    if not text_blocks:
        raise HTTPException(status_code=422, detail="No text content found in document.")

    extracted = {"filename": file.filename, "text_blocks": text_blocks, "tables": [], "images": []}
    chunks = chunker.chunk_document(extracted)
    if not chunks:
        raise HTTPException(status_code=422, detail="Document produced no chunks.")

    embed_texts = [
        f"[Document: {c.filename} | Page: {c.page} | Type: {c.chunk_type}]\n{c.content}"
        for c in chunks
    ]
    embeddings = await embedder.embed_chunks(embed_texts)

    now = datetime.now(timezone.utc).isoformat()
    chroma_chunks = [
        {
            "embedding": emb,
            "document":  chunk.content,
            "metadata": {
                "filename":   chunk.filename,
                "page":       chunk.page,
                "chunk_type": chunk.chunk_type,
                "timestamp":  now,
                "source":     "document",
            },
        }
        for chunk, emb in zip(chunks, embeddings)
    ]
    chroma_client.add_chunks(chroma_chunks)
    bm25_index.mark_dirty()

    return GatewayDocumentResponse(
        status="success",
        filename=file.filename,
        chunks_indexed=len(chroma_chunks),
        processing_time=round(time.time() - start, 2),
    )


@router.get("/gateway/health")
async def gateway_health(_key: dict = Depends(_require_key)):
    """
    Health check for the gateway — confirms API key is valid and services are up.

    Requires: X-API-Key header (any permission).
    """
    from config import get_config
    config = get_config()
    stats = chroma_client.get_stats()

    return {
        "status":    "healthy",
        "key_name":  _key.get("name"),
        "models": {
            "primary":   config["primary_model"],
            "vision":    config["vision_model"],
            "embedding": config["embedding_model"],
        },
        "vector_db": {
            "status":       stats.get("status"),
            "total_chunks": stats.get("total_chunks", 0),
        },
    }
