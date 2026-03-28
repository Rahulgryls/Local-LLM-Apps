"""
LAKO — RAG Router
POST /api/rag/query
RAG query — returns answer + source metadata.
Session 8: Fully implemented.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List

from services.rag_engine import rag_engine

router = APIRouter()


class RAGRequest(BaseModel):
    query: str
    model: Optional[str] = None  # Override primary model
    top_k: Optional[int] = None  # Override config top_k
    use_rag: bool = True


class SourceChunk(BaseModel):
    filename: str
    page: int
    chunk_type: str  # text / table / image-caption
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
    Returns answer with source citations (filename, page, chunk_type, score, content).
    """
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
    )
