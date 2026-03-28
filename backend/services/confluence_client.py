"""
LAKO — Confluence Client Service
Fetches a single Confluence page by URL using the Confluence REST API v2.
Session 1: Stub — wired in Session 9.
"""

import httpx
from typing import Optional
from config import get_config


class ConfluenceClient:
    """Fetches single Confluence pages for ingestion."""

    def __init__(self):
        config = get_config()
        self.base_url = config.get("confluence_url", "")
        self.email = config.get("confluence_email", "")
        self.token = config.get("confluence_token", "")

    def _get_auth(self, email: Optional[str] = None, token: Optional[str] = None):
        """Return HTTP Basic Auth tuple using config or override credentials."""
        return (email or self.email, token or self.token)

    async def fetch_page(
        self,
        url: str,
        email: Optional[str] = None,
        token: Optional[str] = None,
    ) -> dict:
        """
        Fetch a Confluence page by URL.
        Extracts: title, body (HTML → plain text), page_id.
        Returns dict: {title, content, url, page_id}
        TODO (Session 9): implement URL parsing + REST API call.
        """
        raise NotImplementedError("ConfluenceClient.fetch_page() — Session 9")

    def _parse_page_id(self, url: str) -> str:
        """
        Extract Confluence page ID from URL.
        Handles formats: /pages/{id}/... and ?pageId={id}
        TODO (Session 9): implement.
        """
        raise NotImplementedError("ConfluenceClient._parse_page_id() — Session 9")

    def _html_to_text(self, html: str) -> str:
        """
        Convert Confluence HTML body to clean plain text using BeautifulSoup.
        TODO (Session 9): implement with beautifulsoup4.
        """
        raise NotImplementedError("ConfluenceClient._html_to_text() — Session 9")


# Singleton instance
confluence_client = ConfluenceClient()
