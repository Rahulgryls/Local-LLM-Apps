"""
LAKO V2 — Embedding Cache

LRU cache: query text → embedding vector.
  - 200 entries, no TTL (same text always produces the same nomic-embed-text vector)
  - Saves ~50 ms per repeated or near-identical query by skipping the Ollama embed call
"""

import asyncio
from collections import OrderedDict
from typing import List, Optional

_CACHE_MAX = 200
_cache: OrderedDict = OrderedDict()   # text → List[float]
_lock  = asyncio.Lock()


async def get(text: str) -> Optional[List[float]]:
    """Return cached vector or None."""
    async with _lock:
        if text in _cache:
            _cache.move_to_end(text)
            return list(_cache[text])   # return a copy so callers can't mutate cache
        return None


async def put(text: str, vector: List[float]) -> None:
    """Store a text → vector mapping. Evicts LRU entry when over capacity."""
    async with _lock:
        if text in _cache:
            _cache.move_to_end(text)
        else:
            if len(_cache) >= _CACHE_MAX:
                _cache.popitem(last=False)
            _cache[text] = vector
