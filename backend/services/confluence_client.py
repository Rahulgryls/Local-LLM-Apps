"""
LAKO — Confluence Client Service
Fetches and parses Confluence pages via the REST API.
Session 9: Full implementation — fetch, parse, chunk.
"""

import base64
import html as html_module
import logging
import re
from typing import AsyncGenerator, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ConfluenceClient:
    """Fetches Confluence pages and parses HTML into text chunks."""

    # ── URL helpers ─────────────────────────────────────────────────────────

    def extract_page_id(self, url: str) -> str:
        """
        Extract the numeric page ID from a Confluence URL.

        Supported formats:
          Atlassian Cloud:
            https://company.atlassian.net/wiki/spaces/KB/pages/123456
            https://company.atlassian.net/wiki/spaces/KB/pages/123456/Page+Title
          Server / Data Centre:
            https://confluence.company.com/pages/viewpage.action?pageId=123456
        """
        # Cloud: /pages/{id}
        m = re.search(r'/pages/(\d+)', url)
        if m:
            return m.group(1)

        # Server/DC: pageId= query param
        m = re.search(r'[?&]pageId=(\d+)', url)
        if m:
            return m.group(1)

        raise ValueError(
            f"Cannot extract page ID from URL: {url}. "
            "Expected format: .../pages/123456 or ...?pageId=123456"
        )

    def _base_url(self, page_url: str) -> str:
        """Extract scheme + host from a Confluence page URL."""
        m = re.match(r'(https?://[^/]+)', page_url)
        if m:
            return m.group(1)
        raise ValueError(f"Cannot extract base URL from: {page_url}")

    # ── Auth helpers ─────────────────────────────────────────────────────────

    def _build_headers(
        self,
        api_token: Optional[str] = None,
        email: Optional[str] = None,
        auth_type: str = "bearer",
    ) -> dict:
        """
        Build HTTP auth headers.
        - auth_type="bearer": Authorization: Bearer <token>  (OAuth 2.0 tokens)
        - auth_type="basic":  Authorization: Basic base64(email:token)  (Classic API tokens)
        """
        headers = {"Accept": "application/json"}
        if not api_token:
            return headers
        if auth_type == "basic" and email:
            creds = base64.b64encode(f"{email}:{api_token}".encode()).decode()
            headers["Authorization"] = f"Basic {creds}"
        else:
            headers["Authorization"] = f"Bearer {api_token}"
        return headers

    # ── Page fetching ────────────────────────────────────────────────────────

    async def fetch_page(
        self,
        page_url: str,
        api_token: Optional[str] = None,
        email: Optional[str] = None,
        auth_type: str = "bearer",
    ) -> dict:
        """
        Fetch a Confluence page via REST API and return parsed metadata.

        Tries Confluence Cloud v2 API first; falls back to v1 (Server/DC).

        Returns:
            { "title", "content" (HTML), "url", "updated", "author" }

        Raises:
            ValueError        — invalid URL
            PermissionError   — 401/403: auth required
            FileNotFoundError — 404: page not found
            ConnectionError   — 429 rate limit or network/server error
        """
        page_id = self.extract_page_id(page_url)
        base = self._base_url(page_url)
        headers = self._build_headers(api_token, email, auth_type)

        async with httpx.AsyncClient(timeout=30) as client:
            # Try Cloud v2 API
            v2_url = f"{base}/wiki/api/v2/pages/{page_id}?body-format=storage"
            resp = await client.get(v2_url, headers=headers)

            # Fall back to v1 API (Server/DC or older Cloud)
            if resp.status_code == 404:
                v1_url = (
                    f"{base}/wiki/rest/api/content/{page_id}"
                    f"?expand=body.storage,version,history"
                )
                resp = await client.get(v1_url, headers=headers)

        self._raise_for_status(resp, page_url)
        return self._normalise_page_response(resp.json(), page_url)

    def _raise_for_status(self, resp: httpx.Response, page_url: str) -> None:
        code = resp.status_code
        if code == 401:
            raise PermissionError(
                "Confluence API requires authentication. Provide an API token."
            )
        if code == 403:
            raise PermissionError(
                "Access denied. Check your API token has read permission on this space."
            )
        if code == 404:
            raise FileNotFoundError(f"Page not found: {page_url}")
        if code == 429:
            raise ConnectionError(
                "Confluence rate limit exceeded. Please wait a moment and retry."
            )
        if not resp.is_success:
            raise ConnectionError(
                f"Confluence API error {code}: {resp.text[:300]}"
            )

    def _normalise_page_response(self, data: dict, page_url: str) -> dict:
        """Normalise v1 and v2 API response shapes to a common dict."""
        body = data.get("body", {})
        if isinstance(body, dict) and "storage" in body:
            # v1 shape
            content_html = body["storage"].get("value", "")
            title = data.get("title", "Unknown")
            updated = (
                data.get("version", {}).get("when")
                or data.get("history", {}).get("lastUpdated", {}).get("when", "")
            )
            author = data.get("version", {}).get("by", {}).get("displayName", "Unknown")
        else:
            # v2 shape
            content_html = (
                body.get("storage", {}).get("value", "")
                if isinstance(body, dict) else ""
            )
            title = data.get("title", "Unknown")
            updated = data.get("version", {}).get("createdAt", "")
            author = data.get("authorId", "Unknown")

        return {
            "title":   html_module.unescape(title),
            "content": content_html,
            "url":     page_url,
            "updated": updated,
            "author":  author,
        }

    # ── Content parsing ──────────────────────────────────────────────────────

    def _materialize_table(self, table_el) -> tuple:
        """
        Build a fully-resolved 2D grid from a <table> element.

        Handles colspan and rowspan by expanding each cell into every grid
        position it physically occupies.  Multi-row header groups (e.g. two
        stacked <tr> rows each containing <th> cells) are merged column-wise
        with " / " so retrieval context stays intact.

        Returns:
            (headers: List[str], data_rows: List[List[str]])
        """
        # Sparse 2D grid: (row_idx, col_idx) → cell text
        grid: dict = {}
        header_row_set: set = set()

        row_idx = 0
        for tr in table_el.find_all("tr"):
            col_idx = 0
            has_th = False

            for cell in tr.find_all(["th", "td"]):
                # Skip positions already claimed by a rowspan from an earlier row
                while (row_idx, col_idx) in grid:
                    col_idx += 1

                text = cell.get_text(separator=" ", strip=True)

                if cell.name == "th":
                    has_th = True

                try:
                    colspan = max(1, int(cell.get("colspan", 1)))
                except (ValueError, TypeError):
                    colspan = 1
                try:
                    rowspan = max(1, int(cell.get("rowspan", 1)))
                except (ValueError, TypeError):
                    rowspan = 1

                # Fill every grid position this cell spans
                for dr in range(rowspan):
                    for dc in range(colspan):
                        grid[(row_idx + dr, col_idx + dc)] = text

                col_idx += colspan

            if has_th:
                header_row_set.add(row_idx)

            row_idx += 1

        if not grid:
            return [], []

        max_row = max(r for r, _ in grid) + 1
        max_col = max(c for _, c in grid) + 1

        # Header rows: prefer explicit <th>; fallback = first row only
        if header_row_set:
            header_rows = sorted(header_row_set)
            first_data_row = max(header_rows) + 1
        else:
            header_rows = [0]
            first_data_row = 1

        # Merge multi-row header text per column, deduplicating rowspan repeats
        headers: list = []
        for c in range(max_col):
            parts = [grid.get((r, c), "").strip() for r in header_rows]
            seen: list = []
            for p in parts:
                if p and p not in seen:
                    seen.append(p)
            headers.append(" / ".join(seen) if seen else f"Column {c + 1}")

        data_rows: list = []
        for r in range(first_data_row, max_row):
            data_rows.append([grid.get((r, c), "") for c in range(max_col)])

        return headers, data_rows

    def parse_page_content(self, content_html: str) -> List[dict]:
        """
        Parse Confluence HTML storage format into text chunks (~500 tokens each).

        Extracts: headings, paragraphs, tables, code blocks, lists.
        Section headings are prepended to every chunk so each chunk is
        self-contained when retrieved in isolation.

        Table strategy (enterprise-grade):
          1. table_summary  — one chunk: row count + column names
          2. table_row      — one chunk per row (or merged rows ≤ TOKEN_LIMIT)
                              formatted as "Header: Value\\nHeader: Value"
          Handles colspan / rowspan via _materialize_table.

        Returns:
            [{"text": str, "metadata": {"type": "heading|paragraph|table_summary|table_row|code|list"}}, ...]
        """
        soup = BeautifulSoup(content_html, "html.parser")

        for tag in soup.find_all(["script", "style", "ac:structured-macro"]):
            tag.decompose()

        chunks: List[dict] = []
        current_heading = ""
        buffer: List[str] = []
        buffer_type = "paragraph"
        TOKEN_LIMIT = 500

        def _tokens(text: str) -> int:
            return len(text.split())

        def _flush(chunk_type: str = None) -> None:
            text = " ".join(buffer).strip()
            if not text:
                return
            full_text = f"{current_heading}\n{text}" if current_heading else text
            chunks.append({"text": full_text, "metadata": {"type": chunk_type or buffer_type}})
            buffer.clear()

        for el in soup.find_all(
            ["h1", "h2", "h3", "h4", "h5", "h6",
             "p", "table", "pre", "code", "ul", "ol"],
            recursive=True,
        ):
            # Skip elements nested inside a table — the table handler covers them
            if el.name not in ("h1","h2","h3","h4","h5","h6","table") \
                    and el.find_parent("table"):
                continue

            tag = el.name

            # ── Headings ─────────────────────────────────────────────────────
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                _flush()
                current_heading = el.get_text(separator=" ", strip=True)
                if _tokens(current_heading) > 2:
                    chunks.append({
                        "text":     current_heading,
                        "metadata": {"type": "heading"},
                    })

            # ── Tables ───────────────────────────────────────────────────────
            elif tag == "table":
                _flush()
                headers, data_rows = self._materialize_table(el)
                if not headers and not data_rows:
                    continue

                # Ensure no blank header labels
                headers = [h if h else f"Column {i + 1}" for i, h in enumerate(headers)]
                context_prefix = f"{current_heading}\n" if current_heading else ""

                # Filter fully-empty rows
                non_empty = [r for r in data_rows if any(c.strip() for c in r)]

                # ── 1. Summary chunk ─────────────────────────────────────────
                # Anchors "what columns does this table have / how many rows?" queries
                if non_empty:
                    col_names = ", ".join(h for h in headers if h)
                    summary = (
                        f"{context_prefix}Table with {len(non_empty)} rows. "
                        f"Columns: {col_names}."
                    ).strip()
                    chunks.append({"text": summary, "metadata": {"type": "table_summary"}})

                # ── 2. Row-level key:value chunks ────────────────────────────
                # Format: "Header: Value\nHeader: Value" per row
                # Sparse values (empty cells) are omitted to keep vectors clean
                # Rows are merged until TOKEN_LIMIT to avoid micro-chunks
                row_texts: list = []
                for row_cells in non_empty:
                    kv = "\n".join(
                        f"{h}: {v}"
                        for h, v in zip(headers, row_cells)
                        if v.strip()
                    )
                    if kv:
                        row_texts.append(kv)

                pending: list = []
                pending_tok = 0
                for row_text in row_texts:
                    row_tok = _tokens(row_text)
                    if pending_tok + row_tok > TOKEN_LIMIT and pending:
                        chunks.append({
                            "text":     (context_prefix + "\n\n".join(pending)).strip(),
                            "metadata": {"type": "table_row"},
                        })
                        pending = []
                        pending_tok = 0
                    pending.append(row_text)
                    pending_tok += row_tok
                if pending:
                    chunks.append({
                        "text":     (context_prefix + "\n\n".join(pending)).strip(),
                        "metadata": {"type": "table_row"},
                    })

            # ── Code blocks ──────────────────────────────────────────────────
            elif tag in ("pre", "code"):
                if el.find_parent("pre"):
                    continue  # avoid double-processing <pre><code>
                code_text = el.get_text(strip=True)
                if code_text:
                    _flush()
                    prefix = f"{current_heading}\n" if current_heading else ""
                    chunks.append({
                        "text":     f"{prefix}{code_text}",
                        "metadata": {"type": "code"},
                    })

            # ── Lists ────────────────────────────────────────────────────────
            elif tag in ("ul", "ol"):
                if el.find_parent(["ul", "ol"]):
                    continue  # skip nested lists
                items = [
                    f"• {li.get_text(separator=' ', strip=True)}"
                    for li in el.find_all("li")
                    if li.get_text(strip=True)
                ]
                if items:
                    buffer.append("\n".join(items))
                    buffer_type = "list"
                    if _tokens(" ".join(buffer)) >= TOKEN_LIMIT:
                        _flush("list")

            # ── Paragraphs ───────────────────────────────────────────────────
            elif tag == "p":
                text = el.get_text(separator=" ", strip=True)
                if not text:
                    continue
                buffer.append(text)
                buffer_type = "paragraph"
                if _tokens(" ".join(buffer)) >= TOKEN_LIMIT:
                    _flush("paragraph")

        _flush()  # flush any remaining buffer

        return [c for c in chunks if c["text"].strip()]

    # ── Recursive crawl ──────────────────────────────────────────────────────

    async def fetch_page_by_id(
        self,
        base_url: str,
        page_id: str,
        api_token: Optional[str] = None,
        email: Optional[str] = None,
        auth_type: str = "bearer",
    ) -> dict:
        """Fetch a single page by numeric page_id using the v1 REST API."""
        headers = self._build_headers(api_token, email, auth_type)
        url = (
            f"{base_url}/wiki/rest/api/content/{page_id}"
            f"?expand=body.storage,version,history"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
        self._raise_for_status(resp, url)
        page_url = f"{base_url}/wiki/spaces/_/pages/{page_id}"
        return self._normalise_page_response(resp.json(), page_url)

    async def _get_child_page_ids(
        self,
        base_url: str,
        page_id: str,
        headers: dict,
        client: httpx.AsyncClient,
    ) -> List[str]:
        """Return all direct child page IDs for *page_id*, handling pagination."""
        ids: List[str] = []
        start = 0
        limit = 50
        while True:
            url = (
                f"{base_url}/wiki/rest/api/content/{page_id}/child/page"
                f"?limit={limit}&start={start}"
            )
            resp = await client.get(url, headers=headers)
            if not resp.is_success:
                break
            data = resp.json()
            results = data.get("results", [])
            ids.extend(r["id"] for r in results)
            if len(results) < limit:
                break
            start += limit
        return ids

    async def collect_all_page_ids(
        self,
        root_url: str,
        api_token: Optional[str] = None,
        email: Optional[str] = None,
        auth_type: str = "bearer",
    ) -> List[str]:
        """
        BFS from root_url and return a list of ALL page IDs
        (root + every descendant) in breadth-first order.

        Raises the same exceptions as fetch_page() on auth/network failures.
        """
        root_id = self.extract_page_id(root_url)
        base    = self._base_url(root_url)
        headers = self._build_headers(api_token, email, auth_type)

        all_ids: List[str] = []
        queue: List[str]   = [root_id]

        async with httpx.AsyncClient(timeout=30) as client:
            while queue:
                current_id = queue.pop(0)
                all_ids.append(current_id)
                children = await self._get_child_page_ids(
                    base, current_id, headers, client
                )
                queue.extend(children)

        return all_ids

    # ── Mock mode ────────────────────────────────────────────────────────────

    def generate_mock_data(
        self, url: str, page_id: str
    ) -> Tuple[dict, List[dict]]:
        """
        Return realistic mock page + chunks for local dev / testing.
        Simulates a Rabobank internal policy page with varied content types.
        """
        page_info = {
            "title":   f"Risk Management Framework — Mock Page ({page_id})",
            "content": "",
            "url":     url,
            "updated": "2025-01-15T09:00:00Z",
            "author":  "mock-admin",
        }
        chunks = [
            {
                "text": (
                    "Risk Management Framework — Overview\n"
                    "The bank's risk management framework consists of three lines of defence: "
                    "operational risk management, risk oversight, and internal audit. Each line "
                    "has defined responsibilities and escalation paths."
                ),
                "metadata": {"type": "paragraph"},
            },
            {
                "text": (
                    "Credit Risk Policy\n"
                    "All credit exposures above EUR 500,000 require approval from the Credit Risk "
                    "Committee. Counterparty limits are reviewed quarterly and adjusted based on "
                    "market conditions and internal stress-test results."
                ),
                "metadata": {"type": "paragraph"},
            },
            {
                "text": (
                    "Key Risk Indicators\n"
                    "Indicator | Threshold | Review Frequency\n"
                    "Non-Performing Loans | < 2% | Monthly\n"
                    "Capital Adequacy Ratio | > 12% | Quarterly\n"
                    "Liquidity Coverage Ratio | > 100% | Daily\n"
                    "Net Stable Funding Ratio | > 100% | Monthly"
                ),
                "metadata": {"type": "table"},
            },
            {
                "text": (
                    "Operational Procedures\n"
                    "• All trades must be logged in the system within 15 minutes of execution.\n"
                    "• Daily reconciliation is mandatory for all trading desks.\n"
                    "• Exceptions require supervisor sign-off and must be reported within 24 hours.\n"
                    "• End-of-day position reports are sent to risk management automatically."
                ),
                "metadata": {"type": "list"},
            },
            {
                "text": (
                    "Compliance Requirements\n"
                    "Under the Basel III framework, the bank must maintain a minimum CET1 ratio "
                    "of 10.5%. Stress testing scenarios are run bi-annually. Results are reported "
                    "to the DNB (Dutch National Bank) and ECB supervisory board."
                ),
                "metadata": {"type": "paragraph"},
            },
            {
                "text": (
                    "Incident Reporting\n"
                    "Operational risk incidents must be logged in the GRC system within 48 hours "
                    "of discovery. Incidents with potential loss > EUR 100,000 trigger an automatic "
                    "escalation to the CRO and must include a root-cause analysis within 5 business days."
                ),
                "metadata": {"type": "paragraph"},
            },
        ]
        return page_info, chunks


# Singleton instance
confluence_client = ConfluenceClient()
