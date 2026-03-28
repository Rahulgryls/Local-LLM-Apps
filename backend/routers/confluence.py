"""
LAKO — Confluence Router
POST /api/ingest/confluence — Start single Confluence page ingestion
Session 1: Stub — full implementation in Session 9.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ConfluenceIngestRequest(BaseModel):
    url: str        # Full Confluence page URL
    email: str = "" # Override config email if provided
    token: str = "" # Override config token if provided


class ConfluenceIngestResponse(BaseModel):
    job_id: str
    page_title: str
    status: str
    message: str


@router.post("/ingest/confluence")
async def ingest_confluence(request: ConfluenceIngestRequest):
    """
    Fetch a single Confluence page by URL and ingest its content.
    STUB — Confluence client wired in Session 9.
    """
    # TODO (Session 9): call confluence_client.fetch_page(url) → ingest pipeline
    return ConfluenceIngestResponse(
        job_id="stub-job-id",
        page_title="Unknown (STUB)",
        status="pending",
        message=f"[STUB] Confluence ingestion for {request.url} wired in Session 9.",
    )
