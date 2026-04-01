"""
LAKO — Local AI Knowledge Orchestrator
Backend Entry Point — FastAPI Application
Session 1: Environment setup & skeleton
Session 12: Model pre-warming on startup, enhanced /health endpoint.
"""

import logging
import time

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from config import get_config
from routers import chat, rag, ingest, confluence, models, vector, gateway, admin, dashboard

logger = logging.getLogger(__name__)

# Tracks whether the primary model responded to the warm-up ping
_model_ready: dict = {"ready": False, "model": ""}
_startup_time: float = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    from services.ollama_client import ollama_client

    config = get_config()
    primary = config["primary_model"]

    print(f"[LAKO] Starting up...")
    print(f"[LAKO] Primary LLM  : {primary}")
    print(f"[LAKO] Vision Model : {config['vision_model']}")
    print(f"[LAKO] Embeddings   : {config['embedding_model']}")
    print(f"[LAKO] Ollama URL   : {config['ollama_url']}")
    print(f"[LAKO] ChromaDB     : {config['chromadb_path']}")

    # ── Model pre-warming ────────────────────────────────────────────────────
    # Sends a trivial prompt so Ollama loads the model into memory before the
    # first real user query. Failure is non-fatal (model may not be pulled yet).
    print(f"[LAKO] Warming up model: {primary} ...")
    try:
        await ollama_client.chat("Hello", model=primary)
        _model_ready["ready"] = True
        _model_ready["model"] = primary
        print(f"[LAKO] Model ready    : {primary} ✓")
    except Exception as exc:
        _model_ready["ready"] = False
        _model_ready["model"] = primary
        print(f"[LAKO] Model warm-up failed: {exc}")
        print(f"[LAKO] Run: ollama pull {primary}")

    print("[LAKO] Backend ready — http://localhost:8000")
    yield
    print("[LAKO] Shutting down...")


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


@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "service": "LAKO Backend", "version": "1.0.0"}


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
