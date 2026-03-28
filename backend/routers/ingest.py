"""
LAKO — Ingestion Router
POST /api/ingest/docs   — Upload files for ingestion
GET  /api/ingest/status — Poll ingestion progress %
Session 1: Stub — full implementation in Sessions 5–7.
"""

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List
import uuid

router = APIRouter()

# In-memory job tracker (replaced by proper state in Session 5)
_jobs: dict = {}


class IngestStatusResponse(BaseModel):
    job_id: str
    status: str          # pending / processing / complete / error
    progress: int        # 0–100 percent
    message: str


@router.post("/ingest/docs")
async def ingest_docs(files: List[UploadFile] = File(...)):
    """
    Accept one or more files for ingestion.
    Supported: .pdf, .txt, .xlsx, .docx, .pptx
    Returns a job_id to poll /api/ingest/status.
    STUB — pipeline wired in Sessions 5–7.
    """
    job_id = str(uuid.uuid4())
    filenames = [f.filename for f in files]

    # TODO (Session 5): save files to /storage/uploads/, start background ingestion task
    _jobs[job_id] = {"status": "pending", "progress": 0, "files": filenames}

    return JSONResponse({
        "job_id": job_id,
        "accepted_files": filenames,
        "message": "[STUB] Files received. Ingestion pipeline wired in Session 5.",
    })


@router.get("/ingest/status")
async def ingest_status(job_id: str):
    """
    Poll ingestion progress.
    Returns progress percentage (0–100).
    STUB — returns mock data until Session 5.
    """
    if job_id not in _jobs:
        return JSONResponse(status_code=404, content={"error": "Job not found."})

    job = _jobs[job_id]
    return IngestStatusResponse(
        job_id=job_id,
        status=job["status"],
        progress=job["progress"],
        message="[STUB] Progress polling wired in Session 11.",
    )
