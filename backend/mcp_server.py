"""
LAKO — MCP Server

Exposes LAKO's ingest and query capabilities as MCP tools for external callers
with their own AI agent (e.g. a Pega case-management app), over Streamable
HTTP. Mounted at /mcp in main.py — reachable at /mcp/ (trailing slash;
bare /mcp 307-redirects there, which not every HTTP client follows for
a POST, so give integrators the /mcp/ URL directly).

Auth: reuses services.api_key_manager exactly as routers/gateway.py does for
the REST gateway — same X-API-Key header, same "query"/"ingest" permission
strings. FastMCP auto-injects a Context parameter into any tool that declares
one; ctx.request_context.request is the real Starlette request for that one
tool call, so the header is read per-call with no custom middleware needed.

Session context: query_documents persists conversation turns server-side in
db/session_store.py, keyed by whatever session_id string the caller passes
(e.g. a Pega Case ID). This is separate from the browser Chat UI's history,
which stays inline/stateless as it does today — this store exists only for
callers that can't hold their own conversation state across calls.

Ingestion: ingest_document does NOT block until indexing finishes — ingest_file()
runs the full V3 pipeline (parsing, per-page classification, vision-model calls
for image pages, chunking, embedding) which can take minutes for large/scanned
documents, well past most agent frameworks' tool-call timeouts. It mirrors the
async job/poll pattern routers/ingest_v3.py already uses for exactly this reason,
via its own in-process _mcp_jobs dict (kept separate from ingest_v3.py's _jobs
so the two routers' private state isn't coupled together).
"""

import asyncio
import base64
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import structlog
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from db.chunk_store import init_chunk_db
from db.session_store import (
    append_message,
    get_recent_messages,
    init_session_db,
    touch_session,
)
from ingestion.service import ingest_file, source_type_from_filename
from retrieval.answer_service import generate_answer
from retrieval.models import Message
from services.api_key_manager import api_key_manager

logger = structlog.get_logger(__name__)

# FastMCP's DNS-rebinding protection only allows localhost/127.0.0.1 Host
# headers by default — correct for a purely local server, but it rejects
# every request arriving via a tunnel or reverse proxy (the Host header is
# the tunnel's hostname, not "localhost"). Extra hostnames — e.g. a
# Cloudflare Tunnel or ngrok domain fronting this server for Pega — are
# added via LAKO_MCP_ALLOWED_HOSTS (comma-separated, no scheme/port), so a
# new tunnel hostname is a restart-with-env-var away, not a code change.
_extra_hosts = [
    h.strip() for h in os.environ.get("LAKO_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()
]
_transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"] + [f"{h}:*" for h in _extra_hosts] + _extra_hosts,
    allowed_origins=["http://127.0.0.1:*", "http://localhost:*"] + [f"https://{h}" for h in _extra_hosts],
)

# Mounted at /mcp in main.py — streamable_http_path must be "/" here, since
# FastMCP's own default ("/mcp") would otherwise make the reachable path
# /mcp/mcp once mounted. Real endpoint after mounting: /mcp/ (see main.py).
mcp = FastMCP(
    name="lako",
    instructions=(
        "Query and ingest documents in LAKO, an on-premises document Q&A "
        "system. query_documents supports multi-turn follow-ups within the "
        "same session_id. ingest_document accepts PDF, DOCX, PPTX, XLSX, "
        "and HTML files."
    ),
    streamable_http_path="/",
    transport_security=_transport_security,
)

# Built exactly once, here, at import time: StreamableHTTPSessionManager.run()
# (which backs this) is a one-shot context manager that raises if entered
# twice, and mcp.session_manager isn't even accessible until this is called.
# main.py imports `app` (to mount) and `mcp` (to enter session_manager.run()
# in its lifespan) from this module — never calls streamable_http_app() again.
app = mcp.streamable_http_app()

_UPLOAD_DIR = Path(__file__).parent.parent / "storage" / "uploads_mcp"
_SUPPORTED_EXT = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"}

# In-process ingestion job tracker for MCP-initiated ingests. Independent from
# routers/ingest_v3.py's own _jobs dict — same pattern, not shared state.
_mcp_jobs: dict[str, dict] = {}


# ── Auth ─────────────────────────────────────────────────────────────────────

def _authorize(ctx: Context, permission: str) -> dict:
    """
    Validate X-API-Key from the underlying HTTP request for this tool call,
    then check it carries `permission`. Raises ValueError on failure — that
    surfaces as a normal MCP tool-call error, the correct failure channel for
    a JSON-RPC protocol (vs. an HTTP status code the caller's agent loop has
    no mid-protocol way to interpret).
    """
    request = ctx.request_context.request
    api_key = request.headers.get("x-api-key") if request else None
    key_data = api_key_manager.validate_key(api_key)
    if not key_data:
        raise ValueError("Invalid or missing X-API-Key header.")
    if not api_key_manager.check_permission(key_data, permission):
        raise ValueError(f"API key does not have '{permission}' permission.")
    return key_data


# ── Ingestion background task ─────────────────────────────────────────────────

async def _run_mcp_ingestion(job_id: str, file_path: str, filename: str, source_type: str) -> None:
    _mcp_jobs[job_id] = {
        "filename":        filename,
        "status":          "processing",
        "phase":           "parsing",
        "doc_id":          None,
        "chunks_indexed":  0,
        "pages_processed": 0,
        "total_pages":     None,
        "error":           None,
    }

    def _on_progress(doc_id: str, phase: str, current: int, total: int) -> None:
        entry = _mcp_jobs.get(job_id)
        if entry:
            entry["doc_id"] = doc_id
            entry["phase"]  = phase
            if phase == "parsing":
                entry["pages_processed"] = current
                entry["total_pages"]     = total
            elif phase == "embedding":
                entry["chunks_indexed"]  = current

    try:
        result = await ingest_file(
            file_path         = file_path,
            filename          = filename,
            source_type       = source_type,
            progress_callback = _on_progress,
        )
        _mcp_jobs[job_id].update(
            doc_id          = result["doc_id"],
            status          = result["status"],
            phase           = "complete",
            chunks_indexed  = result["chunks"],
            pages_processed = result["pages"],
        )
        logger.info("mcp_ingest_complete", job_id=job_id, doc_id=result["doc_id"])

        try:
            from config import get_config as _get_cfg
            if _get_cfg().get("hybrid_search_enabled", True):
                from retrieval.bm25_index import rebuild_bm25_index
                await rebuild_bm25_index()
        except Exception as bm25_exc:
            logger.warning("mcp_ingest_bm25_rebuild_failed", error=str(bm25_exc))

    except Exception as exc:
        _mcp_jobs[job_id].update(status="failed", phase="failed", error=str(exc))
        logger.error("mcp_ingest_failed", job_id=job_id, error=str(exc))

    finally:
        try:
            os.unlink(file_path)
        except Exception:
            pass


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
async def query_documents(
    query:       str,
    session_id:  str,
    ctx:         Context,
    language:    str = "en",
    doc_id:      Optional[str] = None,
    rag_enabled: bool = True,
) -> dict:
    """
    Ask a question against LAKO's ingested documents (or the web, if
    rag_enabled=False). Pass the same session_id on follow-up questions
    (e.g. a Pega Case ID) so pronoun/reference-heavy follow-ups — "which
    awards did it win?" — resolve correctly against prior turns.
    """
    _authorize(ctx, "query")

    await init_session_db()
    await touch_session(session_id)

    history_rows = await get_recent_messages(session_id, limit=6)
    history = [Message(role=r["role"], content=r["content"]) for r in history_rows]

    result = await generate_answer(
        query       = query,
        language    = language,
        rag_enabled = rag_enabled,
        doc_id      = doc_id,
        history     = history,
    )

    await append_message(session_id, "user", query)
    await append_message(session_id, "assistant", result["answer"])

    return {
        "answer":     result["answer"],
        "sources":    result["sources"],
        "session_id": session_id,
    }


@mcp.tool()
async def ingest_document(filename: str, content_base64: str, ctx: Context) -> dict:
    """
    Ingest a document (PDF, DOCX, PPTX, XLSX, or HTML) so it becomes
    queryable via query_documents. Returns immediately with a job_id — the
    document is not indexed by the time this call returns, since parsing and
    embedding a large or scanned file can take minutes. Poll
    get_ingest_status(job_id) until status is "indexed" or "failed".
    """
    _authorize(ctx, "ingest")

    suffix = Path(filename).suffix.lower()
    if suffix not in _SUPPORTED_EXT:
        raise ValueError(f"Unsupported file type {suffix!r}. Accepted: {sorted(_SUPPORTED_EXT)}")

    try:
        source_type = source_type_from_filename(filename)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    try:
        content = base64.b64decode(content_base64)
    except Exception as exc:
        raise ValueError(f"content_base64 is not valid base64: {exc}") from exc

    await init_chunk_db()

    job_id = str(uuid.uuid4())
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    staged_path = _UPLOAD_DIR / f"mcp_{job_id}{suffix}"
    staged_path.write_bytes(content)

    logger.info("mcp_ingest_queued", job_id=job_id, filename=filename, bytes=len(content))

    asyncio.create_task(
        _run_mcp_ingestion(job_id, str(staged_path), filename, source_type)
    )

    return {"job_id": job_id, "status": "processing"}


@mcp.tool()
async def get_ingest_status(job_id: str, ctx: Context) -> dict:
    """Poll the status of a job started by ingest_document."""
    request = ctx.request_context.request
    api_key = request.headers.get("x-api-key") if request else None
    key_data = api_key_manager.validate_key(api_key)
    if not key_data:
        raise ValueError("Invalid or missing X-API-Key header.")
    if not (
        api_key_manager.check_permission(key_data, "query")
        or api_key_manager.check_permission(key_data, "ingest")
    ):
        raise ValueError("API key does not have 'query' or 'ingest' permission.")

    entry = _mcp_jobs.get(job_id)
    if entry is None:
        raise ValueError(f"No such job_id: {job_id!r}")
    return {"job_id": job_id, **entry}
