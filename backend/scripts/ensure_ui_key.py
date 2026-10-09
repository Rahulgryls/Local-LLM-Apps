"""
LAKO — Register the hosted UI's API key (idempotent)

On a hosted deploy there is no Vite proxy to attach an API key, so main.py's
UI gate attaches LAKO_UI_API_KEY to Basic-authenticated browser requests. The
key store only keeps hashes, so the pre-chosen key from the environment has
to be registered once; this runs at every container start and is a no-op if
the key is already present.

Generate a value with:  python -c "import secrets; print('lako_' + secrets.token_urlsafe(32))"
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import os

from services.api_key_manager import api_key_manager


def main() -> None:
    key = os.environ.get("LAKO_UI_API_KEY", "")
    if not key:
        print("[LAKO] LAKO_UI_API_KEY not set — skipping UI key registration.")
        return
    if not key.startswith("lako_") or len(key) < 30:
        sys.exit("[LAKO] LAKO_UI_API_KEY must start with 'lako_' and be at least 30 chars.")

    key_hash = api_key_manager._hash(key)
    store = api_key_manager._load()
    for entry in store["keys"]:
        if entry["key_hash"] == key_hash:
            if not entry["is_active"]:
                sys.exit("[LAKO] LAKO_UI_API_KEY matches a revoked key — set a new value.")
            print("[LAKO] UI API key already registered.")
            return

    store["keys"].append({
        "id":          str(uuid.uuid4()),
        "name":        "hosted-ui",
        "key_hash":    key_hash,
        "prefix":      key[:9],
        "created_at":  datetime.now(timezone.utc).isoformat(),
        "last_used":   None,
        "is_active":   True,
        "permissions": ["query", "ingest", "admin"],
    })
    api_key_manager._save(store)
    print("[LAKO] UI API key registered.")


if __name__ == "__main__":
    main()
