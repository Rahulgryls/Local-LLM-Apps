"""
LAKO V2 — Model Pre-Warmer

Sends minimal requests to Ollama on application startup to load both
qwen3.5:35b-a3b-coding-nvfp4 (LLM) and nomic-embed-text (embedder) into
GPU memory before the first real user query arrives.

Without pre-warming the first query can take 15–30 s on model load.
After pre-warming it takes < 2 s.

State is stored in a module-level dict so the /api/v2/ready endpoint
can check readiness without importing from main.py.
"""

import time

import structlog

logger = structlog.get_logger(__name__)

_ready: dict = {
    "llm":             False,
    "embedder":        False,
    "model_name":      "",
    "embedding_model": "",
    "warmed_at":       None,
}


async def warm_models(
    primary_model:   str,
    embedding_model: str,
    ollama_url:      str,
) -> None:
    """
    Fire a 1-token generation + 1-text embedding request to pre-load both models.

    Non-fatal: logs warnings if Ollama is unreachable (e.g. model not pulled yet).
    """
    from services.http_client import get_ollama_http_client

    client = get_ollama_http_client()

    # ── Warm LLM ──────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    try:
        r = await client.post(
            f"{ollama_url}/api/generate",
            json={
                "model":   primary_model,
                "prompt":  "Hi",
                "stream":  False,
                "options": {"num_predict": 1},
            },
        )
        r.raise_for_status()
        _ready["llm"]        = True
        _ready["model_name"] = primary_model
        logger.info(
            "model_warmed",
            model=primary_model,
            ms=round((time.perf_counter() - t0) * 1000),
        )
    except Exception as exc:
        logger.warning("model_warm_failed", model=primary_model, error=str(exc))

    # ── Warm embedder ──────────────────────────────────────────────────────────
    t1 = time.perf_counter()
    try:
        r = await client.post(
            f"{ollama_url}/api/embed",
            json={"model": embedding_model, "input": "warmup"},
        )
        r.raise_for_status()
        _ready["embedder"]        = True
        _ready["embedding_model"] = embedding_model
        logger.info(
            "embedder_warmed",
            model=embedding_model,
            ms=round((time.perf_counter() - t1) * 1000),
        )
    except Exception as exc:
        logger.warning("embedder_warm_failed", model=embedding_model, error=str(exc))

    _ready["warmed_at"] = time.time()


def is_ready() -> bool:
    """True only when both LLM and embedder responded successfully."""
    return _ready["llm"] and _ready["embedder"]


def get_status() -> dict:
    return dict(_ready)
