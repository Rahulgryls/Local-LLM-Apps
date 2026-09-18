"""
LAKO — Post-ingest Quality Probe

Runs after embedding is complete. Checks whether the document's own
identifying terms are retrievable from the chunks just stored in Qdrant.

A document that cannot retrieve its own filename stem at cosine > 0.5
likely had a silent extraction failure (e.g. garbled rotation text).

Public API:
  probe_ingest_quality(doc_id, filename) -> 'clean' | 'mixed' | 'suspect'
"""

import re
from pathlib import Path
from typing import Optional

import structlog

from db.chunk_store import get_chunks_for_doc
from ingestion.embedder_v2 import _get_qdrant
from services.ollama_client import ollama_client

COLLECTION_NAME = "lako_documents"

logger = structlog.get_logger(__name__)


async def probe_ingest_quality(doc_id: str, filename: str) -> str:
    """
    Returns 'clean' | 'mixed' | 'suspect'.

    Runs cheap retrieval probes against the chunks of this doc only,
    using a doc_id filter on Qdrant search. If the doc cannot retrieve
    its own filename stem or its own first-page heading at score > 0.5,
    the extraction probably failed silently.

    Args:
        doc_id:   UUID of the document just indexed.
        filename: Original filename (e.g. "WB-Audit-Report-2022.pdf").

    Returns:
        'clean'   — all probes hit (score > 0.5)
        'mixed'   — some probes hit, some missed
        'suspect' — no probes hit
    """
    from qdrant_client.http.models import FieldCondition, Filter, MatchValue

    # Probe 1: filename stem (normalise dashes/underscores to spaces)
    stem = re.sub(r"[-_]+", " ", Path(filename).stem)
    probes = [stem]

    # Probe 2 + 3: first non-empty text chunks from chunk_store
    # Note: chunk_store rows do not carry raw text (lives in Qdrant payload),
    # so block_type filtering is used and text field is left empty — these
    # probes are skipped gracefully when text is unavailable.
    try:
        chunks = await get_chunks_for_doc(doc_id)
        text_chunks = [c for c in chunks[:20] if c.get("block_type") == "text"]
        for h in text_chunks[:2]:
            first_line = (h.get("text") or "").split("\n", 1)[0].strip()
            if 8 <= len(first_line) <= 120:
                probes.append(first_line)
    except Exception as exc:
        logger.warning(
            "quality_probe_chunk_fetch_failed", doc_id=doc_id, error=str(exc)
        )

    qdrant = await _get_qdrant()
    hits = 0

    for probe_text in probes:
        try:
            vec = await ollama_client.embed(probe_text)
            results = await qdrant.query_points(
                collection_name=COLLECTION_NAME,
                query=vec,
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="doc_id",
                            match=MatchValue(value=doc_id),
                        )
                    ]
                ),
                limit=3,
                score_threshold=0.5,
                with_payload=False,
            )
            if results.points:
                hits += 1
        except Exception as exc:
            logger.warning(
                "quality_probe_search_failed",
                doc_id=doc_id,
                probe=probe_text[:50],
                error=str(exc),
            )

    if hits == len(probes):
        return "clean"
    if hits == 0:
        return "suspect"
    return "mixed"
