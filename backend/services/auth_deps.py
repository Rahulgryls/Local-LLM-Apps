"""
LAKO — Shared API-Key Auth Dependencies

FastAPI dependency factories for X-API-Key validation, extracted from
routers/gateway.py (which originally defined these inline) so every router
that needs a stricter per-endpoint permission check — not just the blanket
"any valid key" middleware in main.py — can reuse the same logic instead of
re-implementing it.

Usage:
    from services.auth_deps import require_key, require_permission

    @router.get("/foo", dependencies=[Depends(require_key)])
    ...

    @router.delete("/bar", dependencies=[Depends(require_permission("admin"))])
    ...
"""

from fastapi import Header, HTTPException

from services.api_key_manager import api_key_manager


async def require_key(x_api_key: str = Header(..., alias="X-API-Key")) -> dict:
    """Validate X-API-Key. Raises 401 if missing, invalid, or revoked."""
    key_data = api_key_manager.validate_key(x_api_key)
    if not key_data:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
    return key_data


def require_permission(permission: str):
    """
    Dependency factory — returns a dependency that validates X-API-Key AND
    checks it carries `permission` (e.g. "query", "ingest", "admin").
    Raises 401 if the key itself is missing/invalid, 403 if it lacks the
    required permission.
    """

    async def _dependency(x_api_key: str = Header(..., alias="X-API-Key")) -> dict:
        key_data = api_key_manager.validate_key(x_api_key)
        if not key_data:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
        if not api_key_manager.check_permission(key_data, permission):
            raise HTTPException(
                status_code=403,
                detail=f"This key does not have '{permission}' permission.",
            )
        return key_data

    return _dependency
