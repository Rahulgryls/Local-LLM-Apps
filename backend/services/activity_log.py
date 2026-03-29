"""
LAKO — Activity Log Service
Persists ingestion events to storage/activity_log.json.
Keeps last 50 entries. Used by the Dashboard recent-activity endpoint.
Session 11: Created.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from config import get_config

logger = logging.getLogger(__name__)

ACTIVITY_LOG_PATH = Path("/Users/rahul/lako/storage/activity_log.json")
MAX_ENTRIES = 50


class ActivityLog:
    """Append-only activity log stored on disk."""

    def _load(self) -> List[dict]:
        if not ACTIVITY_LOG_PATH.exists():
            return []
        try:
            data = json.loads(ACTIVITY_LOG_PATH.read_text())
            return data if isinstance(data, list) else []
        except Exception:
            logger.warning("activity_log.json unreadable — starting fresh")
            return []

    def _save(self, entries: List[dict]) -> None:
        ACTIVITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ACTIVITY_LOG_PATH.write_text(json.dumps(entries, indent=2))

    def append(
        self,
        *,
        event_type: str,          # "pdf" | "confluence"
        title: str,
        chunks_indexed: int,
        status: str,              # "success" | "failed"
        error: Optional[str] = None,
    ) -> None:
        """Append a new ingestion event and trim to MAX_ENTRIES."""
        entry = {
            "id": str(uuid.uuid4()),
            "type": event_type,
            "title": title,
            "chunks_indexed": chunks_indexed,
            "status": status,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        entries = self._load()
        entries.append(entry)
        # Keep only the last MAX_ENTRIES
        if len(entries) > MAX_ENTRIES:
            entries = entries[-MAX_ENTRIES:]
        self._save(entries)

    def recent(self, limit: int = 10) -> List[dict]:
        """Return the most recent `limit` entries, newest first."""
        entries = self._load()
        return list(reversed(entries[-limit:]))


# Singleton
activity_log = ActivityLog()
