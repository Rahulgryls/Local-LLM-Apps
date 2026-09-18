"""
LAKO — Models & Config Router
GET  /api/models  — Live Ollama model list + role assignments + health
GET  /api/config  — Read current config.json
POST /api/config  — Write updated fields to config.json
Session 3: Fully implemented.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from config import get_config, save_config
from services.auth_deps import require_permission
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
    summarization_model:  Optional[str]   = None
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

@router.get("/models/chat")
async def list_chat_models():
    """
    Returns all Ollama models appropriate for chat/query use.
    Only excludes the configured embedding model (not suitable for chat).
    Used by the Chat page model selector.
    """
    config = get_config()
    default_model = config["primary_model"]
    embedding_model = config["embedding_model"]

    reachable = await ollama_client.health_check()
    if not reachable:
        return {"models": [default_model], "default": default_model}

    raw_models = await ollama_client.list_models()

    # Only exclude the embedding model — all other downloaded models are chat-capable
    chat_models = [
        m
        for m in raw_models
        if m["name"] != embedding_model
        and not m["name"].startswith(embedding_model + ":")
    ]

    # Sort: default model first, rest alphabetically
    non_default = sorted(
        [m for m in chat_models if m["name"] != default_model],
        key=lambda m: m["name"],
    )
    default_entry = next((m for m in chat_models if m["name"] == default_model), None)

    if default_entry:
        ordered = [default_entry] + non_default
    else:
        # Primary model not yet pulled — inject a placeholder entry
        ordered = [{"name": default_model, "size": "not pulled"}] + non_default

    return {"models": ordered, "default": default_model}


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


@router.post("/config", dependencies=[Depends(require_permission("admin"))])
async def update_config(request: ConfigUpdateRequest):
    """
    Save updated config fields to config.json and reload.
    Only fields that are present in the request body are updated.

    Requires an "admin"-permission X-API-Key — this can rewrite stored
    credentials (Confluence token, API keys) and model/infra settings.
    """
    # Build update dict — exclude fields not sent (None means not provided)
    updates = {k: v for k, v in request.model_dump().items() if v is not None}

    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided to update.")

    updated = save_config(updates)
    return {"status": "saved", "config": updated}
