"""
LAKO — Local AI Knowledge Orchestrator
Backend Entry Point — FastAPI Application
Session 1: Environment setup & skeleton
Session 12: Model pre-warming on startup, enhanced /health endpoint.
"""

import base64
import logging
import os
import secrets
import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from contextlib import AsyncExitStack, asynccontextmanager

from config import get_config
from routers import chat, rag, ingest, confluence, models, vector, gateway, admin, dashboard
from routers import ingest_v2, health_v2, rag_v2
from routers import ingest_v3, confluence_v3
from services.api_key_manager import api_key_manager
import mcp_server

logger = logging.getLogger(__name__)

# Tracks whether the primary model responded to the warm-up ping
_model_ready: dict = {"ready": False, "model": ""}
_startup_time: float = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    from services.model_warmer import warm_models, get_status
    from services.http_client import close_ollama_http_client

    async with AsyncExitStack() as stack:
        # MCP's StreamableHTTPSessionManager must be entered exactly once, for
        # the life of the process — this is that one place. Without it, MCP
        # tool calls fail because the session manager was never started.
        await stack.enter_async_context(mcp_server.mcp.session_manager.run())

        config  = get_config()
        primary = config["primary_model"]
        embed   = config["embedding_model"]

        print(f"[LAKO] Starting up...")
        print(f"[LAKO] Primary LLM  : {primary}")
        print(f"[LAKO] Vision Model : {config['vision_model']}")
        print(f"[LAKO] Embeddings   : {embed}")
        print(f"[LAKO] Ollama URL   : {config['ollama_url']}")
        print(f"[LAKO] ChromaDB     : {config['chromadb_path']}")

        # ── V2 model pre-warming (LLM + embedder via shared HTTP client) ──────
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
        # ── BM25 hybrid-search index ──────────────────────────────────────────
        if config.get("hybrid_search_enabled", True):
            try:
                from retrieval.bm25_index import rebuild_bm25_index
                await rebuild_bm25_index()
            except Exception as _bm25_exc:
                print(f"[LAKO] BM25 index build failed (non-fatal): {_bm25_exc}")

        autosave = None
        from services import github_persist
        if github_persist.enabled():
            import asyncio
            autosave = asyncio.create_task(github_persist.run_autosave())
            print("[LAKO] GitHub persistence: autosave on")

        print("[LAKO] Backend ready — http://localhost:8000")
        print("[LAKO] MCP server    — http://localhost:8000/mcp/")

        yield

        print("[LAKO] Shutting down...")
        if autosave:
            autosave.cancel()
            await github_persist.flush()
        await close_ollama_http_client()


app = FastAPI(
    title="LAKO — Local AI Knowledge Orchestrator",
    description="Fully on-premises AI knowledge platform for internal bank use.",
    version="1.0.0",
    lifespan=lifespan,
)

# ── Blanket API-key gate ─────────────────────────────────────────────────────
# Every other router (chat/rag/ingest/confluence/models/vector/admin/dashboard/
# v2/v3) was built with zero authentication, on the assumption LAKO only ever
# runs local-only. That assumption breaks the moment anything (a tunnel, a
# reverse proxy) forwards traffic from outside this machine. This middleware
# requires ANY valid, active API key (services/api_key_manager.py, unchanged)
# for every /api/* request except the paths below — everything else (root
# status, health, Postman collection, /mcp, /api/gateway/*) already handles
# its own access story and is left alone. Individual routers still layer a
# stricter "admin"-permission check on top for genuinely destructive
# endpoints (see services/auth_deps.py) — this middleware only proves *some*
# valid key was presented, not that it has the right permission tier.
_EXEMPT_PREFIXES = ("/mcp", "/api/gateway")
_EXEMPT_PATHS = {"/api/v2/health", "/api/v2/ready"}


@app.middleware("http")
async def _require_any_api_key(request: Request, call_next):
    path = request.url.path
    if (
        not path.startswith("/api/")
        or path in _EXEMPT_PATHS
        or any(path.startswith(p) for p in _EXEMPT_PREFIXES)
    ):
        return await call_next(request)

    api_key = request.headers.get("x-api-key")
    if not api_key_manager.validate_key(api_key):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing X-API-Key header."},
        )
    return await call_next(request)


# ── Hosted-UI gate (Render) ──────────────────────────────────────────────────
# In dev, Vite's proxy attaches the API key so the browser never holds one. A
# hosted build has no Vite proxy, so this plays the same role: when
# LAKO_BASIC_AUTH_USERS ("user:pass,user2:pass2") is set, everything except
# the exempt machine-to-machine paths requires HTTP Basic auth, and a
# Basic-authenticated browser request to /api/* gets LAKO_UI_API_KEY attached
# server-side. Unset => no-op, local behaviour is unchanged. Requests that
# already carry their own X-API-Key skip Basic auth and are validated by the
# API-key middleware above as usual.
_BASIC_USERS = [
    u.strip() for u in os.environ.get("LAKO_BASIC_AUTH_USERS", "").split(",") if ":" in u
]
_UI_API_KEY = os.environ.get("LAKO_UI_API_KEY", "")
_GATE_EXEMPT_PREFIXES = ("/mcp", "/api/gateway")
_GATE_EXEMPT_PATHS = {"/api/v2/health", "/api/v2/ready", "/health"}


def _basic_auth_ok(header: str) -> bool:
    if not header.lower().startswith("basic "):
        return False
    try:
        supplied = base64.b64decode(header[6:]).decode()
    except Exception:
        return False
    return any(secrets.compare_digest(supplied, u) for u in _BASIC_USERS)


if _BASIC_USERS:

    @app.middleware("http")
    async def _ui_gate(request: Request, call_next):
        path = request.url.path
        if (
            request.method == "OPTIONS"
            or path in _GATE_EXEMPT_PATHS
            or any(path.startswith(p) for p in _GATE_EXEMPT_PREFIXES)
            or (path.startswith("/api/") and request.headers.get("x-api-key"))
        ):
            return await call_next(request)

        if not _basic_auth_ok(request.headers.get("authorization", "")):
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required."},
                headers={"WWW-Authenticate": 'Basic realm="LAKO"'},
            )
        if path.startswith("/api/") and _UI_API_KEY:
            request.scope["headers"] = [
                (k, v) for k, v in request.scope["headers"] if k != b"authorization"
            ] + [(b"x-api-key", _UI_API_KEY.encode())]
        return await call_next(request)


# CORS — allow React dev server on port 5173. Registered AFTER the auth
# middleware above so it ends up outermost (Starlette applies middleware in
# reverse registration order) and can still handle CORS preflight (OPTIONS)
# requests before they'd hit the auth check.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"]
    + [o.strip() for o in os.environ.get("LAKO_CORS_ORIGINS", "").split(",") if o.strip()],
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
app.include_router(ingest_v3.router,     prefix="/api", tags=["V3 Ingestion"])
app.include_router(confluence_v3.router, prefix="/api", tags=["V3 Confluence"])

# MCP server (Streamable HTTP) — external tool-calling clients (e.g. Pega).
# mcp_server.app already has streamable_http_path="/", so this mount avoids
# the /mcp/mcp double-segment bug. Note the real reachable endpoint is
# /mcp/ WITH a trailing slash — Starlette 307-redirects bare /mcp to /mcp/,
# and not every HTTP client/connector follows a redirect on a POST. Give
# external integrators (e.g. a Pega REST/MCP connector) the /mcp/ URL
# directly rather than relying on redirect-following.
app.mount("/mcp", mcp_server.app)


_FRONTEND_DIST = Path(os.environ.get("LAKO_FRONTEND_DIST", Path(__file__).parent.parent / "frontend" / "dist"))
_SERVE_UI = (_FRONTEND_DIST / "index.html").exists()

if not _SERVE_UI:
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


# ── Built React frontend (hosted deploys) ────────────────────────────────────
# Registered last so every API/health/docs route above wins. Unknown non-API
# paths fall back to index.html for react-router's BrowserRouter.
if _SERVE_UI:

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith(("api/", "mcp")):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (_FRONTEND_DIST / full_path).resolve()
        if full_path and candidate.is_file() and _FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")
