"""
LAKO — Shared Query-Processing Helpers

Query rewriting, multi-topic detection/decomposition, and multi-query search
merging. Shared by both the streaming SSE pipeline (routers/rag_v2.py) and the
non-streaming answer service (retrieval/answer_service.py, used by the MCP
server) so the LLM-rewrite prompts only need tuning in one place.
"""

import asyncio
import re
from typing import Optional

import structlog

from retrieval.models import Message, SearchResult
from retrieval.searcher import search_pages

logger = structlog.get_logger(__name__)


# ── Sessional context ────────────────────────────────────────────────────────

async def contextualize_query(query: str, history: list[Message]) -> str:
    """
    Rewrite a follow-up question into a standalone search query using recent
    conversation turns, so retrieval isn't blind to references like "that" or
    "the other one" from earlier in the chat. The rewritten query is used only
    for embedding/search — the LLM's final answer still targets the user's
    original wording (passed separately as conversation history).
    Falls back to the original query on any LLM error or malformed output.
    """
    from services.ollama_client import ollama_client

    convo = "\n".join(f"{m.role}: {m.content}" for m in history)
    prompt = (
        f"Conversation so far:\n{convo}\n\n"
        f"Follow-up question: {query}\n\n"
        "Rewrite the follow-up question as a standalone question that can be "
        "understood without the conversation above. Resolve pronouns and "
        "implicit references (e.g. \"that\", \"the other one\") using the "
        "conversation. Output ONLY the rewritten question, nothing else."
    )
    system = (
        "You rewrite follow-up questions into standalone search questions. "
        "Output only the rewritten question, nothing else."
    )
    try:
        rewritten = (await ollama_client.chat(prompt, system=system)).strip().strip('"')
        if rewritten and len(rewritten) < 500:
            logger.info("query_contextualized", original=query[:80], rewritten=rewritten[:80])
            return rewritten
    except Exception as exc:
        logger.warning("contextualize_failed", error=str(exc))
    return query


# ── Multi-topic query helpers ──────────────────────────────────────────────────

def is_multi_topic(query: str) -> bool:
    """
    Detect if a query spans multiple independent topics.
    Triggers decomposition when there are multiple explicit questions, or when
    the query is long with 3+ 'and' connectors (compound topic coverage).
    """
    if query.count("?") >= 2:
        return True
    if len(query) > 100 and len(re.findall(r"\band\b", query, re.IGNORECASE)) >= 3:
        return True
    return False


async def decompose_query(query: str) -> list[str]:
    """
    Use the LLM to split a complex multi-topic query into 2–4 focused sub-queries.
    Each sub-query targets a single topic so its embedding is tight and precise.
    Falls back to [query] on LLM error or malformed output.
    """
    from services.ollama_client import ollama_client

    prompt = (
        "Split this question into 2-4 focused sub-queries, one per line.\n"
        "Each sub-query must target exactly one topic from the original question.\n"
        "Output ONLY the sub-queries — no numbering, no bullets, no explanation.\n\n"
        f"Question: {query}"
    )
    system = (
        "You are a search query decomposition assistant. "
        "Output only the sub-queries, one per line, nothing else."
    )
    try:
        response = await ollama_client.chat(prompt, system=system)
        lines = [l.strip() for l in response.strip().splitlines() if l.strip()]
        cleaned = []
        for line in lines:
            line = re.sub(r"^[\d]+[.)]\s*", "", line)
            line = re.sub(r"^[-*•]\s*", "", line).strip()
            if len(line) > 10:
                cleaned.append(line)
        if 2 <= len(cleaned) <= 6:
            logger.info("query_decomposed", subs=[s[:60] for s in cleaned])
            return cleaned
    except Exception as exc:
        logger.warning("query_decompose_failed", error=str(exc))
    return [query]


async def multi_topic_search(
    sub_queries:     list[str],
    sub_vectors:     list,
    top_k:           int,
    score_threshold: float,
    doc_id_filter:   Optional[str],
) -> list[SearchResult]:
    """
    Search independently per sub-query, merge results by best score per page.
    Uses top_k * 2 per sub-query for wide candidate coverage before the merge.
    The score_threshold is applied after merging so borderline-relevant pages
    from minority sub-topics aren't dropped before combination.
    """
    per_sq: list[list[SearchResult]] = await asyncio.gather(*[
        search_pages(
            query           = sq,
            top_k           = top_k * 2,
            score_threshold = 0.0,          # threshold applied after merge
            doc_id_filter   = doc_id_filter,
            query_vector    = sv,
        )
        for sq, sv in zip(sub_queries, sub_vectors)
    ])

    # Merge: keep best score per (doc_id, page_num) across all sub-query results
    best: dict[tuple, SearchResult] = {}
    for results in per_sq:
        for sr in results:
            key = (sr.doc_id, sr.page_num)
            if key not in best or sr.score > best[key].score:
                best[key] = sr

    return sorted(
        [sr for sr in best.values() if sr.score >= score_threshold],
        key=lambda x: x.score,
        reverse=True,
    )
