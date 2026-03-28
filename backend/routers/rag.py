"""
LAKO — RAG Router
POST /api/rag/query
RAG query — returns answer + source metadata.
Session 1: Stub — full implementation in Session 8.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List

router = APIRouter()


class RAGRequest(BaseModel):
    query: str
    model: Optional[str] = None  # Override primary model
    top_k: Optional[int] = None  # Override config top_k
    use_rag: bool = True


class SourceChunk(BaseModel):
    filename: str
    page: int
    chunk_type: str  # text / table / diagram / image-caption
    score: float
    content: str


class RAGResponse(BaseModel):
    answer: str
    sources: List[SourceChunk] = []
    model: str
    rag_used: bool


@router.post("/rag/query")
async def rag_query(request: RAGRequest):
    """
    RAG query: embed question → search ChromaDB → inject chunks → ask LLM.
    Returns answer with source citations.
    STUB — wired to RAG engine in Session 8.
    """
    # TODO (Session 8): call rag_engine.query()
    return RAGResponse(
        answer="[STUB] RAG endpoint is not yet implemented. Session 8 will wire this to the RAG engine.",
        sources=[],
        model=request.model or "qwen3.5:9b",
        rag_used=request.use_rag,
    )
