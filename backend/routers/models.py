"""
LAKO — Models Router
GET /api/models — List all available Ollama models
Session 1: Stub — Ollama integration in Session 3.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List

router = APIRouter()


class ModelInfo(BaseModel):
    name: str
    size: str = ""
    modified: str = ""


class ModelsResponse(BaseModel):
    models: List[ModelInfo]
    primary_model: str
    vision_model: str
    embedding_model: str


@router.get("/models")
async def list_models():
    """
    List all Ollama models installed on this machine.
    Auto-populates frontend dropdowns — no hardcoded model names.
    STUB — live Ollama query wired in Session 3.
    """
    # TODO (Session 3): call ollama_client.list_models() → GET /api/tags
    return ModelsResponse(
        models=[
            ModelInfo(name="qwen3.5:9b", size="~8.8 GB"),
            ModelInfo(name="llava:13b",  size="~10.5 GB"),
            ModelInfo(name="nomic-embed-text", size="~0.5 GB"),
        ],
        primary_model="qwen3.5:9b",
        vision_model="llava:13b",
        embedding_model="nomic-embed-text",
    )
