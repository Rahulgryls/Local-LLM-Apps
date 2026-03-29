"""
LAKO — API Key Manager
Generates, validates, revokes, and deletes API keys for the REST gateway.

Security model:
  - Plain keys are generated with secrets.token_urlsafe(32) and prefixed "lako_"
  - Only SHA-256 hashes are persisted — the plain key is returned ONCE at
    creation time and is never stored
  - Prefix (first 9 chars) is stored for display so admins can identify keys
    without seeing the full value
  - Revoked keys are kept in storage with is_active=False for audit trail
  - Deleted keys are removed entirely

Storage: storage/api_keys.json (excluded from git via .gitignore)
Session 10: Full implementation.
"""

import hashlib
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from config import get_config

logger = logging.getLogger(__name__)

_EMPTY_STORE = {"keys": []}


class ApiKeyManager:
    """Manages LAKO gateway API keys with hashed storage."""

    # ── Storage helpers ──────────────────────────────────────────────────────

    def _path(self) -> Path:
        return Path(get_config().get("api_keys_path", "/Users/rahul/lako/storage/api_keys.json"))

    def _load(self) -> dict:
        p = self._path()
        if not p.exists():
            return {"keys": []}
        try:
            return json.loads(p.read_text())
        except Exception:
            logger.warning("api_keys.json corrupt — returning empty store")
            return {"keys": []}

    def _save(self, store: dict) -> None:
        p = self._path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(store, indent=2))

    # ── Key operations ───────────────────────────────────────────────────────

    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    def generate_key(self, name: str, permissions: List[str]) -> dict:
        """
        Generate a new API key for a named consumer.

        Returns:
            {"key": "lako_...", "id": str, "prefix": str}

        The "key" field is the ONLY time the plain key is available.
        Only the hash is stored — there is no recovery if lost.
        """
        raw = "lako_" + secrets.token_urlsafe(32)
        prefix = raw[:9]   # "lako_" + 4 chars — enough to identify without revealing
        key_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        store = self._load()
        store["keys"].append({
            "id":          key_id,
            "name":        name,
            "key_hash":    self._hash(raw),
            "prefix":      prefix,
            "created_at":  now,
            "last_used":   None,
            "is_active":   True,
            "permissions": permissions,
        })
        self._save(store)

        logger.info(f"API key generated: '{name}' (id={key_id}, prefix={prefix})")
        return {"key": raw, "id": key_id, "prefix": prefix}

    def validate_key(self, api_key: str) -> Optional[dict]:
        """
        Validate an incoming API key.

        Hashes the provided key and compares against stored hashes.
        Updates last_used on success.

        Returns key metadata dict (no hash) on success, None on failure.
        """
        if not api_key or not api_key.startswith("lako_"):
            return None

        incoming_hash = self._hash(api_key)
        store = self._load()

        for entry in store["keys"]:
            if entry["key_hash"] == incoming_hash and entry["is_active"]:
                # Update last_used
                entry["last_used"] = datetime.now(timezone.utc).isoformat()
                self._save(store)
                # Return metadata without the hash
                return {k: v for k, v in entry.items() if k != "key_hash"}

        return None

    def list_keys(self) -> List[dict]:
        """Return all keys without hashes — safe for API responses."""
        store = self._load()
        return [
            {k: v for k, v in entry.items() if k != "key_hash"}
            for entry in store["keys"]
        ]

    def revoke_key(self, key_id: str) -> bool:
        """
        Deactivate a key by ID. Keeps the record for audit trail.
        Returns True if key was found and revoked.
        """
        store = self._load()
        for entry in store["keys"]:
            if entry["id"] == key_id:
                if not entry["is_active"]:
                    return False  # already revoked
                entry["is_active"] = False
                self._save(store)
                logger.info(f"API key revoked: id={key_id}")
                return True
        return False

    def delete_key(self, key_id: str) -> bool:
        """
        Permanently remove a key by ID.
        Returns True if key was found and deleted.
        """
        store = self._load()
        before = len(store["keys"])
        store["keys"] = [e for e in store["keys"] if e["id"] != key_id]
        if len(store["keys"]) < before:
            self._save(store)
            logger.info(f"API key deleted: id={key_id}")
            return True
        return False

    def check_permission(self, key_data: dict, permission: str) -> bool:
        """Return True if the key has the requested permission."""
        return permission in key_data.get("permissions", [])


# Singleton instance
api_key_manager = ApiKeyManager()
