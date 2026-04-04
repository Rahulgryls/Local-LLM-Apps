"""
LAKO — File Registry Service
Tracks SHA-256 hashes of ingested files.
Used to detect re-uploads of identical files (skip) and changed files (replace).
Session 19: Fully implemented.

Registry stored at storage/file_registry.json:
  { "filename.pdf": "sha256hex", ... }

Concurrency: all operations use a threading lock — safe for FastAPI background tasks.
"""

import hashlib
import json
import logging
import threading
from pathlib import Path

from config import get_config

_REGISTRY_FILENAME = "file_registry.json"
_lock = threading.Lock()


def _registry_path() -> Path:
    """Resolve registry path relative to chromadb_path's parent (storage/)."""
    chromadb_path = Path(get_config()["chromadb_path"])
    storage_dir = chromadb_path.parent
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir / _REGISTRY_FILENAME


class FileRegistry:
    """
    Manages per-filename SHA-256 hashes for deduplication.

    Usage:
      registry.compute_hash(bytes)   → sha256 hex string
      registry.get_hash(filename)    → stored hash or None
      registry.set_hash(filename, h) → persist new hash
      registry.delete(filename)      → remove entry
    """

    def compute_hash(self, content: bytes) -> str:
        """Compute SHA-256 hex digest of raw file bytes."""
        return hashlib.sha256(content).hexdigest()

    def get_hash(self, filename: str) -> str | None:
        """Return stored hash for filename, or None if not registered."""
        with _lock:
            data = self._load()
            return data.get(filename)

    def set_hash(self, filename: str, file_hash: str) -> None:
        """Persist hash for filename."""
        with _lock:
            data = self._load()
            data[filename] = file_hash
            self._save(data)

    def delete(self, filename: str) -> None:
        """Remove filename entry from registry (called on explicit delete)."""
        with _lock:
            data = self._load()
            if filename in data:
                del data[filename]
                self._save(data)
                logging.info(f"[file-registry] removed entry for '{filename}'")

    def all_filenames(self) -> list:
        """Return all registered filenames."""
        with _lock:
            return list(self._load().keys())

    # ── Private ───────────────────────────────────────────────────────────────

    def _load(self) -> dict:
        path = _registry_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logging.warning(f"[file-registry] failed to read registry: {exc}")
            return {}

    def _save(self, data: dict) -> None:
        path = _registry_path()
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logging.warning(f"[file-registry] failed to write registry: {exc}")


# Singleton instance
file_registry = FileRegistry()
