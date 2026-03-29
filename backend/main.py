"""
LAKO — Local AI Knowledge Orchestrator
Backend Entry Point — FastAPI Application
Session 1: Environment setup & skeleton
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from config import get_config
from routers import chat, rag, ingest, confluence, models, vector, gateway, admin, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    config = get_config()
    print(f"[LAKO] Starting up...")
    print(f"[LAKO] Primary LLM  : {config['primary_model']}")
    print(f"[LAKO] Vision Model : {config['vision_model']}")
    print(f"[LAKO] Embeddings   : {config['embedding_model']}")
    print(f"[LAKO] Ollama URL   : {config['ollama_url']}")
    print(f"[LAKO] ChromaDB     : {config['chromadb_path']}")
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
    return {"status": "healthy"}
