"""
LAKO — Local AI Knowledge Orchestrator
Backend Entry Point — FastAPI Application
Session 1: Environment setup & skeleton
Session 12: Model pre-warming on startup, enhanced /health endpoint.
"""

import logging
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from config import get_config
from routers import chat, rag, ingest, confluence, models, vector, gateway, admin, dashboard
from routers import ingest_v2, health_v2, rag_v2

logger = logging.getLogger(__name__)

# Tracks whether the primary model responded to the warm-up ping
_model_ready: dict = {"ready": False, "model": ""}
_startup_time: float = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    from services.model_warmer import warm_models, get_status
    from services.http_client import close_ollama_http_client

    config  = get_config()
    primary = config["primary_model"]
    embed   = config["embedding_model"]

    print(f"[LAKO] Starting up...")
    print(f"[LAKO] Primary LLM  : {primary}")
    print(f"[LAKO] Vision Model : {config['vision_model']}")
    print(f"[LAKO] Embeddings   : {embed}")
    print(f"[LAKO] Ollama URL   : {config['ollama_url']}")
    print(f"[LAKO] ChromaDB     : {config['chromadb_path']}")

    # ── V2 model pre-warming (LLM + embedder via shared HTTP client) ──────────
    print(f"[LAKO] Warming models: {primary} + {embed} ...")
    await warm_models(
        primary_model   = primary,
        embedding_model = embed,
        ollama_url      = config["ollama_url"],
    )

    # Keep legacy _model_ready dict in sync for the /health endpoint
    status = get_status()
    _model_ready["ready"] = status["llm"]
    _model_ready["model"] = status["model_name"] or primary
    print(
        f"[LAKO] LLM ready     : {status['llm']} ✓"
        if status["llm"] else
        f"[LAKO] LLM warm-up failed — run: ollama pull {primary}"
    )
    print(
        f"[LAKO] Embedder ready: {status['embedder']} ✓"
        if status["embedder"] else
        f"[LAKO] Embedder warm-up failed — run: ollama pull {embed}"
    )
    print("[LAKO] Backend ready — http://localhost:8000")

    yield

    print("[LAKO] Shutting down...")
    await close_ollama_http_client()


app = FastAPI(
    title="LAKO — Local AI Knowledge Orchestrator",
    description="Fully on-premises AI knowledge platform for internal bank use.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow React dev server on port 5173
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(chat.router,       prefix="/api", tags=["Chat"])
app.include_router(rag.router,        prefix="/api", tags=["RAG"])
app.include_router(ingest.router,     prefix="/api", tags=["Ingestion"])
app.include_router(confluence.router, prefix="/api", tags=["Confluence"])
app.include_router(models.router,     prefix="/api", tags=["Models"])
app.include_router(vector.router,     prefix="/api", tags=["Vector DB"])
app.include_router(gateway.router,    prefix="/api", tags=["Gateway"])
app.include_router(admin.router,      prefix="/api", tags=["Admin"])
app.include_router(dashboard.router,  prefix="/api", tags=["Dashboard"])
app.include_router(ingest_v2.router,  prefix="/api", tags=["V2 Ingestion"])
app.include_router(health_v2.router,  prefix="/api", tags=["V2 Health"])
app.include_router(rag_v2.router,     prefix="/api", tags=["V2 RAG"])


@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "service": "LAKO Backend", "version": "1.0.0"}


@app.get("/postman", tags=["Health"])
async def download_postman_collection():
    """
    Download the LAKO Postman collection JSON.
    Open this URL in a browser or hit it in Postman to get the file.

    GET http://localhost:8000/postman
    """
    collection_path = Path(__file__).parent.parent / "LAKO_Postman_Collection.json"
    if not collection_path.exists():
        raise HTTPException(status_code=404, detail="Postman collection file not found.")
    return FileResponse(
        path=str(collection_path),
        media_type="application/json",
        filename="LAKO_Postman_Collection.json",
        headers={"Content-Disposition": "attachment; filename=LAKO_Postman_Collection.json"},
    )


@app.get("/health", tags=["Health"])
async def health():
    """
    Extended health check — returns full system status.
    """
    config = get_config()
    from services.chroma_client import chroma_client
    from services.rag_engine import _query_cache

    # ChromaDB chunk count
    try:
        stats = chroma_client.get_stats()
        chromadb_chunks = stats.get("total_chunks", 0)
    except Exception:
        chromadb_chunks = 0

    # Ollama version
    ollama_version = "unknown"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{config['ollama_url']}/api/version")
            if r.status_code == 200:
                ollama_version = r.json().get("version", "unknown")
    except Exception:
        pass

    return {
        "status":          "healthy",
        "model_ready":     _model_ready["ready"],
        "model":           _model_ready["model"] or config["primary_model"],
        "ollama_version":  ollama_version,
        "chromadb_chunks": chromadb_chunks,
        "embedding_model": config["embedding_model"],
        "uptime_seconds":  int(time.time() - _startup_time),
        "cache_size":      len(_query_cache),
    }
