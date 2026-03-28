"""
LAKO — Vector DB Router
GET    /api/vector/status — ChromaDB health check + stats
DELETE /api/vector/clear  — Delete all chunks from collection
Session 4: Fully implemented.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from services.chroma_client import chroma_client

router = APIRouter()


class VectorStatusResponse(BaseModel):
    status: str
    collection: str
    total_chunks: int
    chromadb_path: str


class ClearResponse(BaseModel):
    status: str
    deleted_chunks: int


@router.get("/vector/status", response_model=VectorStatusResponse)
async def vector_status():
    """
    ChromaDB health check and collection statistics.
    Initialises the collection on first call if it does not yet exist.
    """
    stats = chroma_client.get_stats()
    return VectorStatusResponse(
        status=stats["status"],
        collection=stats["collection"],
        total_chunks=stats["total_chunks"],
        chromadb_path=stats["path"],
    )


@router.delete("/vector/clear", response_model=ClearResponse)
async def clear_vector_db():
    """
    Delete all document chunks from the ChromaDB collection.
    The collection is recreated immediately as empty.
    Use with caution — this removes all ingested knowledge.
    """
    deleted = chroma_client.clear_collection()
    return ClearResponse(status="cleared", deleted_chunks=deleted)
