"""
LAKO — Bootstrap the local-frontend API key

One-time setup script. `POST /api/admin/keys` now requires an
"admin"-permission key (see main.py's blanket auth middleware +
routers/admin.py), so the very first key can't be created by calling that
endpoint over HTTP — this script creates it in-process instead, the same
way `api_key_manager` is used ad-hoc elsewhere in this codebase.

Run once from backend/:
    .venv/bin/python scripts/bootstrap_local_key.py

Paste the printed key into frontend/.env.local as:
    LAKO_LOCAL_API_KEY=lako_...

Vite's dev proxy (frontend/vite.config.js) reads that value and attaches it
as X-API-Key to every proxied /api/* request, so the browser frontend keeps
working with zero component changes despite every router now requiring a
key.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.api_key_manager import api_key_manager


def main() -> None:
    result = api_key_manager.generate_key(
        name="local-frontend",
        permissions=["query", "ingest", "admin"],
    )
    print("Local frontend API key created.")
    print(f"  id:     {result['id']}")
    print(f"  prefix: {result['prefix']}")
    print()
    print("Add this to frontend/.env.local (create the file if it doesn't exist):")
    print()
    print(f"LAKO_LOCAL_API_KEY={result['key']}")
    print()
    print("This value is shown once and is not recoverable — re-run this")
    print("script to mint a new key if it's lost (the old one can be revoked")
    print("via DELETE /api/admin/keys/{id} using the new key).")


if __name__ == "__main__":
    main()
