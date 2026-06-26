"""
LAKO — In-Memory BM25 Keyword Index

Provides fast keyword/proper-noun search alongside vector search.
Acts as a third "collection" for RRF fusion in searcher.py.

Corpus sources:
  • lako_v2.db  → page_summaries table  (doc_id, page_num, summary_text)
  • Qdrant       → lako_documents V3 collection  (doc_id, page_num, text payload)

Each corpus entry is keyed by (doc_id, page_num, source_collection) so RRF
can merge with the Qdrant vector hits without duplication.

Public API:
  rebuild_bm25_index()            — (re)build the index from live data sources
  bm25_search(query, top_k)       — keyword search; returns list of BM25Hit
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class BM25Hit:
    doc_id:           str
    page_num:         int
    source_collection: str   # "lako_page_summaries" | "lako_documents"
    text:             str    # raw text used for hydration
    bm25_score:       float
    rank:             int    # 1-based rank within BM25 results


# ── Module-level index state ───────────────────────────────────────────────────

_index       = None    # rank_bm25.BM25Okapi instance
_corpus_keys: list[tuple[str, int, str]] = []   # [(doc_id, page_num, collection), ...]
_corpus_texts: list[str] = []                   # raw text for each entry (for hydration)
_lock        = asyncio.Lock()


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + lowercase tokeniser matching BM25Okapi expectations."""
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


# ── Index builder ──────────────────────────────────────────────────────────────

async def rebuild_bm25_index() -> int:
    """
    Load all text from SQLite V2 page_summaries + Qdrant V3 lako_documents,
    build a fresh BM25Okapi index, and swap it into the module globals.

    Returns the total number of documents indexed.
    Called from: main.py lifespan, ingest_v2, ingest_v3, confluence_v3.
    """
    global _index, _corpus_keys, _corpus_texts

    keys:  list[tuple[str, int, str]] = []
    texts: list[str]                  = []

    # ── Load V2 page_summaries from SQLite ────────────────────────────────────
    try:
        import aiosqlite
        from pathlib import Path
        db_path = Path(__file__).parent.parent.parent / "storage" / "lako_v2.db"
        if db_path.exists():
            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                # Index raw page text instead of LLM summaries.
                # Summaries are 2-3 sentences and frequently drop named entities
                # (place names, policy titles, district names) that are the most
                # important terms for keyword retrieval. Raw text preserves them.
                async with db.execute(
                    "SELECT doc_id, page_num, raw_text FROM pages"
                ) as cursor:
                    async for row in cursor:
                        if row["raw_text"]:
                            keys.append((row["doc_id"], row["page_num"], "lako_pages_raw"))
                            texts.append(row["raw_text"])
        logger.info("bm25_v2_loaded", count=sum(1 for _, _, c in keys if c == "lako_pages_raw"))
    except Exception as exc:
        logger.warning("bm25_v2_load_failed", error=str(exc))

    # ── Load V3 chunks from Qdrant payload ────────────────────────────────────
    try:
        from ingestion.embedder_v2 import _get_qdrant
        V3_COLLECTION = "lako_documents"

        client = await _get_qdrant()
        existing = {c.name for c in (await client.get_collections()).collections}

        if V3_COLLECTION in existing:
            # Scroll through all points — no query vector needed, we want payload only
            offset = None
            while True:
                results, offset = await client.scroll(
                    collection_name = V3_COLLECTION,
                    limit           = 500,
                    offset          = offset,
                    with_payload    = True,
                    with_vectors    = False,
                )
                for point in results:
                    p    = point.payload or {}
                    text = p.get("text") or p.get("summary_text", "")
                    if text:
                        keys.append((
                            p.get("doc_id", ""),
                            p.get("page_num", p.get("page", 0)),
                            V3_COLLECTION,
                        ))
                        texts.append(text)
                if offset is None:
                    break
        v3_count = sum(1 for _, _, c in keys if c == "lako_documents")
        logger.info("bm25_v3_loaded", count=v3_count)
    except Exception as exc:
        logger.warning("bm25_v3_load_failed", error=str(exc))

    if not texts:
        logger.warning("bm25_index_empty", reason="no documents found in either source")
        async with _lock:
            _index        = None
            _corpus_keys  = []
            _corpus_texts = []
        return 0

    # ── Build BM25 index ──────────────────────────────────────────────────────
    try:
        from rank_bm25 import BM25Okapi
        tokenized = [_tokenize(t) for t in texts]
        new_index = BM25Okapi(tokenized)
        async with _lock:
            _index        = new_index
            _corpus_keys  = keys
            _corpus_texts = texts
        total = len(texts)
        logger.info("bm25_index_built", total_documents=total)
        print(f"[LAKO] BM25 index loaded with {total} documents")
        return total
    except Exception as exc:
        logger.error("bm25_index_build_failed", error=str(exc))
        return 0


# ── Search ─────────────────────────────────────────────────────────────────────

async def bm25_search(query: str, top_k: int = 40) -> list[BM25Hit]:
    """
    Score *query* against the BM25 index.
    Returns up to *top_k* hits sorted by BM25 score descending.

    Returns empty list if the index has not been built or is empty.
    """
    async with _lock:
        if _index is None or not _corpus_keys:
            return []
        index  = _index
        keys   = list(_corpus_keys)
        texts  = list(_corpus_texts)

    tokens = _tokenize(query)
    if not tokens:
        return []

    scores: list[float] = index.get_scores(tokens).tolist()

    # Pair each entry with its score and sort descending
    ranked = sorted(
        enumerate(scores),
        key=lambda x: x[1],
        reverse=True,
    )[:top_k]

    hits: list[BM25Hit] = []
    for rank_0, (idx, score) in enumerate(ranked):
        if score <= 0.0:
            # BM25 returns 0.0 for no-match; skip to keep result list clean
            break
        doc_id, page_num, collection = keys[idx]
        hits.append(BM25Hit(
            doc_id            = doc_id,
            page_num          = page_num,
            source_collection = collection,
            text              = texts[idx],
            bm25_score        = score,
            rank              = rank_0 + 1,   # 1-based
        ))

    return hits
