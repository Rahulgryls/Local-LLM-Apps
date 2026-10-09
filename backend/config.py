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

# Deployment overrides (e.g. Render): an env var, when set, wins over config.json
# so a hosted instance needs no committed config edits and no secrets in git.
_ENV_OVERRIDES = {
    "OLLAMA_URL":         "ollama_url",
    "PRIMARY_MODEL":      "primary_model",
    "VISION_MODEL":       "vision_model",
    "EMBEDDING_MODEL":    "embedding_model",
    "SUMMARIZATION_MODEL": "summarization_model",
    "CHROMADB_PATH":      "chromadb_path",
    "API_KEYS_PATH":      "api_keys_path",
    "SEARXNG_URL":        "searxng_url",
    "CONFLUENCE_URL":     "confluence_url",
    "CONFLUENCE_EMAIL":   "confluence_email",
    "CONFLUENCE_TOKEN":   "confluence_token",
}

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
    # qdrant_url removed — Qdrant now runs embedded (no Docker). Data lives in storage/qdrant/
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
    for env_name, key in _ENV_OVERRIDES.items():
        if os.environ.get(env_name):
            config[key] = os.environ[env_name]
    return config


def reload_config() -> dict:
    """Force reload config from disk (clears lru_cache)."""
    get_config.cache_clear()
    return get_config()


_DEFAULT_OLLAMA_RUNTIME: dict = {
    "num_ctx":        20480,
    "num_predict":    1500,
    "repeat_penalty": 1.1,
    "temperature":    0.3,
    "top_p":          0.9,
    "keep_alive":     -1,
    "think":          False,
}

# Keys that belong inside Ollama's "options" object vs. at the request root
_OPTIONS_KEYS   = {"num_ctx", "num_predict", "repeat_penalty", "temperature", "top_p"}
_TOPLEVEL_KEYS  = {"keep_alive", "think"}


def get_ollama_runtime_options() -> dict:
    """
    Return Ollama runtime settings merged from config.json's ``ollama_runtime``
    key, falling back to hardcoded defaults for any missing keys.

    Return shape::

        {
            "options":    {num_ctx, num_predict, repeat_penalty, temperature, top_p},
            "keep_alive": -1,
            "think":      False,
        }

    ``options`` maps directly to Ollama's ``options`` field.
    ``keep_alive`` and ``think`` are top-level Ollama API fields.
    """
    overrides = get_config().get("ollama_runtime", {})
    merged    = {**_DEFAULT_OLLAMA_RUNTIME, **overrides}
    return {
        "options":    {k: merged[k] for k in _OPTIONS_KEYS if k in merged},
        "keep_alive": merged.get("keep_alive", -1),
        "think":      merged.get("think", False),
    }


def save_config(data: dict) -> dict:
    """Merge data into config.json, persist to disk, reload cache."""
    current = dict(get_config())   # copy — don't mutate the cached dict
    current.update(data)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)
    return reload_config()
