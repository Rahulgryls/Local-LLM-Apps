"""
LAKO — Models & Config Router
GET  /api/models  — Live Ollama model list + role assignments + health
GET  /api/config  — Read current config.json
POST /api/config  — Write updated fields to config.json
Session 3: Fully implemented.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from config import get_config, save_config
from services.ollama_client import ollama_client

router = APIRouter()


# ── Response / Request models ─────────────────────────────────────────────────

class ModelInfo(BaseModel):
    name: str
    size: str = ""
    modified: str = ""


class ModelsResponse(BaseModel):
    models: List[ModelInfo]          # All installed Ollama models
    primary_model: str               # Assigned role — from config
    vision_model: str
    embedding_model: str
    ollama_reachable: bool           # True if Ollama server responded
    model_health: dict               # {"primary_model": bool, "vision_model": bool, "embedding_model": bool}


class ConfigUpdateRequest(BaseModel):
    primary_model:        Optional[str]   = None
    vision_model:         Optional[str]   = None
    embedding_model:      Optional[str]   = None
    ollama_url:           Optional[str]   = None
    chromadb_path:        Optional[str]   = None
    confluence_url:       Optional[str]   = None
    confluence_email:     Optional[str]   = None
    confluence_token:     Optional[str]   = None
    top_k:                Optional[int]   = None
    similarity_threshold: Optional[float] = None
    api_key:              Optional[str]   = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _model_installed(config_name: str, installed_names: List[str]) -> bool:
    """
    Check if a config model name matches any installed Ollama model.
    Handles the :latest suffix — e.g. "nomic-embed-text" matches "nomic-embed-text:latest".
    """
    for name in installed_names:
        if name == config_name or name.startswith(config_name + ":"):
            return True
    return False


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/models", response_model=ModelsResponse)
async def list_models():
    """
    Returns all Ollama models installed on this machine plus role assignments
    from config.json and a health flag per role.
    """
    config = get_config()

    # Try to reach Ollama
    reachable = await ollama_client.health_check()
    if not reachable:
        return ModelsResponse(
            models=[],
            primary_model=config["primary_model"],
            vision_model=config["vision_model"],
            embedding_model=config["embedding_model"],
            ollama_reachable=False,
            model_health={
                "primary_model": False,
                "vision_model": False,
                "embedding_model": False,
            },
        )

    raw_models = await ollama_client.list_models()
    installed_names = [m["name"] for m in raw_models]

    model_health = {
        "primary_model":   _model_installed(config["primary_model"],   installed_names),
        "vision_model":    _model_installed(config["vision_model"],    installed_names),
        "embedding_model": _model_installed(config["embedding_model"], installed_names),
    }

    return ModelsResponse(
        models=[ModelInfo(**m) for m in raw_models],
        primary_model=config["primary_model"],
        vision_model=config["vision_model"],
        embedding_model=config["embedding_model"],
        ollama_reachable=True,
        model_health=model_health,
    )


@router.get("/config")
async def read_config():
    """Return the current config.json contents."""
    return get_config()


@router.post("/config")
async def update_config(request: ConfigUpdateRequest):
    """
    Save updated config fields to config.json and reload.
    Only fields that are present in the request body are updated.
    """
    # Build update dict — exclude fields not sent (None means not provided)
    updates = {k: v for k, v in request.model_dump().items() if v is not None}

    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update.")

    updated = save_config(updates)
    return {"status": "saved", "config": updated}
