"""
LAKO — Configuration Loader
Reads config/config.json from the project root.
All model names and paths are sourced from here — never hardcoded.
"""

import json
import os
from pathlib import Path
from functools import lru_cache

# Resolve config path relative to project root (two levels up from backend/)
CONFIG_PATH = Path(__file__).parent.parent / "config" / "config.json"

_DEFAULT_CONFIG = {
    "ollama_url": "http://localhost:11434",
    "primary_model": "qwen3.5:35b-a3b-coding-nvfp4",
    "vision_model": "qwen3.5:35b-a3b-coding-nvfp4",
    "embedding_model": "nomic-embed-text",
    # Small/fast model used exclusively for table summarisation at ingest time.
    # Falls back to primary_model if left empty or not pulled.
    "summarization_model": "",
    "chromadb_path": "/lako/storage/chromadb",
    "confluence_url": "https://yourbank.atlassian.net",
    "confluence_email": "",
    "confluence_token": "",
    "top_k": 5,
    "similarity_threshold": 0.7,
    "api_key": "",
    "qdrant_url":  "http://localhost:6333",
    "searxng_url": "http://localhost:8080",
}


@lru_cache(maxsize=1)
def get_config() -> dict:
    """Load and return configuration. Cached after first read."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        # Merge with defaults so missing keys never cause KeyErrors
        config = {**_DEFAULT_CONFIG, **loaded}
    else:
        print(f"[LAKO] WARNING: config.json not found at {CONFIG_PATH}. Using defaults.")
        config = _DEFAULT_CONFIG.copy()
    return config


def reload_config() -> dict:
    """Force reload config from disk (clears lru_cache)."""
    get_config.cache_clear()
    return get_config()


def save_config(data: dict) -> dict:
    """Merge data into config.json, persist to disk, reload cache."""
    current = dict(get_config())   # copy — don't mutate the cached dict
    current.update(data)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)
    return reload_config()
