"""
LAKO — Admin Router
API key management endpoints for internal administrators.

All endpoints require an "admin"-permission X-API-Key — minting/listing/
revoking/deleting keys is the one action that must never be reachable
without already holding a trusted key (otherwise it's a full auth-bypass:
anyone could just call POST /admin/keys first to self-issue access to
everything else). See services/auth_deps.py.

Session 10: Full implementation.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.api_key_manager import api_key_manager
from services.auth_deps import require_permission

router = APIRouter(dependencies=[Depends(require_permission("admin"))])
logger = logging.getLogger(__name__)


# ── Request / Response models ────────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    name: str
    permissions: List[str] = ["query"]   # "query" | "ingest" | "admin"


class CreateKeyResponse(BaseModel):
    key: str          # ⚠️ Shown ONCE — never stored, cannot be recovered
    id: str
    prefix: str
    warning: str = "Save this key immediately. It will never be shown again."


class KeyMetadata(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: str
    last_used: Optional[str] = None
    is_active: bool
    permissions: List[str]


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/admin/keys", response_model=CreateKeyResponse)
async def create_key(request: CreateKeyRequest):
    """
    Generate a new API key.

    The full key is returned ONCE in the response and is never stored.
    If lost, the key must be deleted and a new one generated.

    Permissions:
      "query"  — allows POST /api/gateway/query, and read-only /api/* access
      "ingest" — allows POST /api/gateway/ingest/*, and ingest-type /api/* access
      "admin"  — key management (this router), config writes, destructive
                 operations (vector DB clear, V2/V3 reindex/clear, document delete)
    """
    valid_perms = {"query", "ingest", "admin"}
    invalid = set(request.permissions) - valid_perms
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown permission(s): {invalid}. Valid: {valid_perms}",
        )
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Key name cannot be empty.")

    result = api_key_manager.generate_key(
        name=request.name.strip(),
        permissions=request.permissions,
    )
    return CreateKeyResponse(**result)


@router.get("/admin/keys", response_model=List[KeyMetadata])
async def list_keys():
    """List all API keys (no hashes, no full key values)."""
    return api_key_manager.list_keys()


@router.delete("/admin/keys/{key_id}")
async def delete_key(key_id: str):
    """
    Permanently delete an API key by ID.
    The key can no longer be used after deletion.
    """
    deleted = api_key_manager.delete_key(key_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Key '{key_id}' not found.")
    return {"deleted": True, "id": key_id}


@router.patch("/admin/keys/{key_id}/revoke")
async def revoke_key(key_id: str):
    """
    Revoke an API key — marks it inactive but keeps the record for audit.
    A revoked key cannot be used; it can only be deleted.
    """
    revoked = api_key_manager.revoke_key(key_id)
    if not revoked:
        raise HTTPException(
            status_code=404,
            detail=f"Key '{key_id}' not found or already revoked.",
        )
    return {"revoked": True, "id": key_id}
