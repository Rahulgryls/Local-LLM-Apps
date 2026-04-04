"""
LAKO V2 — Query Cache

LRU cache for the 50 most-recent unique query responses.
  - Key:   normalized query string (lowercase, stripped, punctuation removed)
  - Value: {"response": str, "sources": list}
  - TTL:   1 hour (documents may be re-ingested, making answers stale)
  - Skip:  queries that carry a doc_id filter (too specific to reuse)
  - Invalidation: clear() — called whenever any document is re-ingested
"""

import asyncio
import re
import time
from collections import OrderedDict
from typing import Optional

_CACHE_MAX   = 50
_TTL         = 3600.0          # seconds

_cache: OrderedDict = OrderedDict()   # key → {"ts": float, "value": dict}
_lock         = asyncio.Lock()

# ── Stats counters ─────────────────────────────────────────────────────────────
_hits   = 0
_misses = 0


def _normalize(query: str) -> str:
    """Lowercase, strip, collapse whitespace, remove punctuation."""
    q = query.lower().strip()
    q = re.sub(r"[^\w\s]", "", q)
    q = re.sub(r"\s+", " ", q)
    return q


# ── Public API ─────────────────────────────────────────────────────────────────

async def get(query: str) -> Optional[dict]:
    """Return cached {"response": str, "sources": list} or None on miss/expiry."""
    global _hits, _misses
    key = _normalize(query)
    async with _lock:
        entry = _cache.get(key)
        if entry is not None:
            if time.monotonic() - entry["ts"] < _TTL:
                _cache.move_to_end(key)
                _hits += 1
                return entry["value"]
            del _cache[key]     # expired — treat as miss
        _misses += 1
        return None


async def put(query: str, value: dict) -> None:
    """Store a query response. Evicts LRU entry when over capacity."""
    key = _normalize(query)
    async with _lock:
        if key in _cache:
            _cache.move_to_end(key)
        elif len(_cache) >= _CACHE_MAX:
            _cache.popitem(last=False)      # evict least-recently-used
        _cache[key] = {"ts": time.monotonic(), "value": value}


async def clear() -> None:
    """Invalidate the entire cache. Call after any document re-ingest."""
    global _hits, _misses
    async with _lock:
        _cache.clear()


def stats() -> dict:
    """Return hit/miss counters and current occupancy (no lock needed for reads)."""
    total = _hits + _misses
    return {
        "size":     len(_cache),
        "max_size": _CACHE_MAX,
        "hits":     _hits,
        "misses":   _misses,
        "hit_rate": round(_hits / total, 3) if total else 0.0,
    }
