"""
LAKO V2 — Retrieval Pipeline Pydantic Models

Shared across searcher, context_fetcher, budget_manager, prompt_builder.
"""

from typing import Optional
from pydantic import BaseModel


class SearchResult(BaseModel):
    """One Qdrant hit — the lightweight summary index entry."""
    doc_id:       str
    page_num:     int
    filename:     str
    source_type:  str
    score:        float
    summary_text: str
    headers:      str    # stored as " | " joined string in Qdrant payload
    has_tables:   bool


class PageContent(BaseModel):
    """
    One raw page fetched from SQLite, annotated with retrieval metadata.

    is_direct_match — True if this page was returned by Qdrant directly.
                      False if it was fetched as a ±N buffer neighbour.
    score           — Similarity score of the search result that caused
                      this page to be included.  Used by budget_manager
                      to decide which pages to trim first.
    """
    doc_id:          str
    filename:        str
    page_num:        int
    raw_text:        str
    is_direct_match: bool
    score:           float


class AssembledContext(BaseModel):
    """
    The full context payload ready for the prompt builder.

    pages        — All pages (direct matches + buffers), sorted by
                   (doc_id, page_num) for coherent reading order.
    total_tokens — Rough token estimate: sum(len(p.raw_text)) // 4
    sources      — Unique (doc_id, filename) pairs, for the SSE final event.
    """
    pages:        list[PageContent]
    total_tokens: int
    sources:      list[dict]     # [{doc_id, filename, page_num, score}]


class WebResult(BaseModel):
    """One SearXNG web search result."""
    title:   str
    url:     str
    snippet: str


class QueryRequest(BaseModel):
    query:       str
    language:    str  = "en"    # "en" | "nl"
    rag_enabled: bool = True
    doc_id:      Optional[str] = None     # filter to a specific document


class QueryResponse(BaseModel):
    """Used only for non-streaming (test) responses."""
    answer:   str
    sources:  list[dict] = []
    language: str
    rag_used: bool
