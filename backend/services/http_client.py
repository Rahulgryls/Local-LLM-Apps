"""
LAKO V2 — Shared Ollama HTTP Client

A single persistent httpx.AsyncClient reused across all V2 Ollama API calls.
Connection pooling avoids per-request TCP handshake overhead (~10–20 ms).

Usage:
    from services.http_client import get_ollama_http_client
    client = get_ollama_http_client()
    r = await client.post(url, json=body)

Lifecycle:
    Call close_ollama_http_client() from the FastAPI lifespan shutdown hook.
"""

import httpx

_client: httpx.AsyncClient | None = None


def get_ollama_http_client() -> httpx.AsyncClient:
    """Return the shared AsyncClient, creating it on first call."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=300.0,     # long enough for large LLM responses
                write=30.0,
                pool=5.0,
            ),
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=30.0,
            ),
        )
    return _client


async def close_ollama_http_client() -> None:
    """Close the shared client gracefully. Call from lifespan shutdown."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
