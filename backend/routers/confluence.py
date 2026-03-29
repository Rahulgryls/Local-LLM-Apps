"""
LAKO — Confluence Ingestion Router
POST /api/ingest/confluence — Fetch, parse, embed, and index a Confluence page.
Session 9: Full implementation.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.confluence_client import confluence_client
from services.embedder import embedder
from services.chroma_client import chroma_client
from services.bm25_index import bm25_index

router = APIRouter()
logger = logging.getLogger(__name__)


class ConfluenceIngestRequest(BaseModel):
    url: str
    api_token: Optional[str] = None
    mock: bool = False   # Force mock mode — useful for local testing without Confluence access


class ConfluenceIngestResponse(BaseModel):
    status: str              # success | failed
    page_id: str
    page_title: str
    chunks_indexed: int
    processing_time: float
    error: Optional[str] = None


@router.post("/ingest/confluence", response_model=ConfluenceIngestResponse)
async def ingest_confluence(request: ConfluenceIngestRequest):
    """
    Fetch a single Confluence page and ingest it into the knowledge base.

    Pipeline:
      1. Validate URL and extract page ID
      2. Fetch page via Confluence REST API (or mock)
      3. Parse HTML into structured chunks
      4. Embed chunks with nomic-embed-text
      5. Store in ChromaDB with source metadata
      6. Mark BM25 index dirty so next query triggers rebuild
    """
    start = time.time()
    url = request.url.strip()

    # ── Step 1: Validate URL and extract page ID ─────────────────────────────
    if not url.startswith(("http://", "https://")):
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid URL. Must start with http:// or https://"},
        )

    try:
        page_id = confluence_client.extract_page_id(url)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    # ── Step 2: Fetch page ───────────────────────────────────────────────────
    try:
        if request.mock:
            page_info, raw_chunks = confluence_client.generate_mock_data(url, page_id)
        else:
            page_info = await confluence_client.fetch_page(url, request.api_token)
            raw_chunks = confluence_client.parse_page_content(page_info["content"])
    except PermissionError as e:
        return JSONResponse(status_code=401, content={"error": str(e)})
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except ConnectionError as e:
        msg = str(e)
        status = 429 if "rate limit" in msg.lower() else 500
        return JSONResponse(status_code=status, content={"error": msg})
    except Exception as e:
        logger.exception("Unexpected error fetching Confluence page")
        return JSONResponse(status_code=500, content={"error": f"Unexpected error: {e}"})

    if not raw_chunks:
        return JSONResponse(
            status_code=422,
            content={"error": "No content chunks found. The page may be empty."},
        )

    # ── Step 3: Embed chunks ─────────────────────────────────────────────────
    page_title = page_info["title"]
    embed_texts = [
        f"[Confluence: {page_title} | Section: {c['metadata']['type']}]\n{c['text']}"
        for c in raw_chunks
    ]

    try:
        embeddings = await embedder.embed_chunks(embed_texts)
    except Exception as e:
        logger.exception("Embedding failed for Confluence page")
        return JSONResponse(status_code=500, content={"error": f"Embedding failed: {e}"})

    # ── Step 4: Store in ChromaDB ────────────────────────────────────────────
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

    try:
        chroma_client.add_chunks(chroma_chunks)
    except Exception as e:
        logger.exception("ChromaDB storage failed for Confluence page")
        return JSONResponse(status_code=500, content={"error": f"Storage failed: {e}"})

    bm25_index.mark_dirty()

    processing_time = round(time.time() - start, 2)
    logger.info(
        f"Confluence ingested: '{page_title}' — {len(chroma_chunks)} chunks in {processing_time}s"
    )

    return ConfluenceIngestResponse(
        status="success",
        page_id=page_id,
        page_title=page_title,
        chunks_indexed=len(chroma_chunks),
        processing_time=processing_time,
    )
