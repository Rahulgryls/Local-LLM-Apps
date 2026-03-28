"""
LAKO — Vector DB Router
GET /api/vector/status — ChromaDB health check + stats
Session 1: Stub — ChromaDB wired in Session 4.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class VectorStatusResponse(BaseModel):
    status: str
    collection_count: int
    total_chunks: int
    chromadb_path: str
    message: str


@router.get("/vector/status")
async def vector_status():
    """
    ChromaDB health check and statistics.
    Returns chunk count and collection info.
    STUB — ChromaDB client wired in Session 4.
    """
    # TODO (Session 4): call chroma_client.get_stats()
    return VectorStatusResponse(
        status="stub",
        collection_count=0,
        total_chunks=0,
        chromadb_path="/lako/storage/chromadb",
        message="[STUB] ChromaDB wired in Session 4.",
    )
