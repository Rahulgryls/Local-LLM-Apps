"""
LAKO V2 — SearXNG Web Searcher

Calls the local SearXNG instance (localhost:8080) and returns structured
web results.  Used when rag_enabled=False in the query endpoint.

Graceful degradation: if SearXNG is unreachable or returns an error,
an empty list is returned so the router can surface a friendly message.
"""

import logging
from urllib.parse import urlencode

import httpx
import structlog

from config import get_config
from retrieval.models import WebResult

logger = structlog.get_logger(__name__)

_TIMEOUT = 10.0    # seconds — web search should be fast


def _searxng_url() -> str:
    return get_config().get("searxng_url", "http://localhost:8080")


async def web_search(query: str, num_results: int = 5) -> list[WebResult]:
    """
    Query SearXNG and return up to *num_results* structured results.

    Returns an empty list (never raises) so callers can handle
    the no-results case gracefully.
    """
    params = {
        "q":       query,
        "format":  "json",
        "engines": "google,duckduckgo",
    }
    url = f"{_searxng_url()}/search?{urlencode(params)}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except httpx.ConnectError:
        logger.warning("searxng_unreachable", url=_searxng_url())
        return []
    except httpx.TimeoutException:
        logger.warning("searxng_timeout", query=query[:80])
        return []
    except Exception as exc:
        logger.error("searxng_error", error=str(exc))
        return []

    raw_results = data.get("results", [])
    results: list[WebResult] = []

    for item in raw_results[:num_results]:
        title   = item.get("title",   "").strip()
        url_str = item.get("url",     "").strip()
        snippet = item.get("content", item.get("snippet", "")).strip()
        if title and url_str:
            results.append(WebResult(title=title, url=url_str, snippet=snippet))

    logger.info("web_search_done", query=query[:80], results=len(results))
    return results
