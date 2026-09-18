"""
LAKO — Auth Middleware Unit Tests

Tests main.py's blanket API-key middleware plus the "admin"-tier permission
gate on the genuinely destructive endpoints, against the real FastAPI app
(no mocking of the middleware/dependency logic itself — only the API key
store is pointed at a temporary file so the test doesn't touch the real
storage/api_keys.json).

Uses FastAPI's TestClient WITHOUT the `with` context-manager form
deliberately — that skips triggering main.py's lifespan (Ollama warm-up,
BM25 rebuild, MCP session manager), which would make this test slow and
dependent on Ollama actually running. The middleware and per-route
dependencies are plain ASGI middleware/dependencies, not lifespan state, so
they're fully exercised either way.

Run from backend/:
    python -m pytest tests/test_auth_middleware.py -v

Coverage:
  - No key / invalid key on a blanket-gated /api/* path -> 401
  - Valid "query"-only key on an admin-tier endpoint -> 403
  - Valid "admin" key on the same endpoint -> 200 (or the route's own logic)
  - Exempted paths (/api/v2/health, /api/v2/ready, /mcp prefix,
    /api/gateway prefix, root paths) -> reachable with no key at all
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

# ── Make sure the backend src dir is on the path ──────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

import config as config_module


class TestAuthMiddleware(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Point api_key_manager at a throwaway keys file so this test never
        # touches the real storage/api_keys.json.
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._keys_path = str(Path(cls._tmpdir.name) / "test_api_keys.json")

        real_get_config = config_module.get_config

        def _fake_get_config():
            cfg = dict(real_get_config())
            cfg["api_keys_path"] = cls._keys_path
            return cfg

        cls._config_patcher = patch("config.get_config", side_effect=_fake_get_config)
        cls._config_patcher.start()

        # api_key_manager.py imports get_config lazily inside _path(), and
        # routers already did `from config import get_config` at import
        # time in some places — patch the module-level function itself
        # (above) so every call site sees the fake path, regardless of how
        # it was imported.

        import main
        # raise_server_exceptions=False: hitting /mcp/ without the app's
        # lifespan running (we skip it deliberately — see module docstring)
        # raises inside the MCP session manager rather than a clean HTTP
        # response. That's a lifespan-dependency quirk unrelated to what
        # this test file checks (path exemption from the auth middleware),
        # so surface it as a response instead of letting it fail the test.
        cls.client = TestClient(main.app, raise_server_exceptions=False)

        from services.api_key_manager import api_key_manager
        cls.admin_key = api_key_manager.generate_key("test-admin", ["query", "ingest", "admin"])["key"]
        cls.query_key = api_key_manager.generate_key("test-query-only", ["query"])["key"]

    @classmethod
    def tearDownClass(cls):
        cls._config_patcher.stop()
        cls._tmpdir.cleanup()

    def test_missing_key_rejected_on_blanket_gated_path(self):
        r = self.client.get("/api/admin/keys")
        self.assertEqual(r.status_code, 401)

    def test_invalid_key_rejected(self):
        r = self.client.get("/api/admin/keys", headers={"X-API-Key": "lako_not_a_real_key"})
        self.assertEqual(r.status_code, 401)

    def test_valid_key_without_admin_permission_gets_403_on_admin_endpoint(self):
        r = self.client.get("/api/admin/keys", headers={"X-API-Key": self.query_key})
        self.assertEqual(r.status_code, 403)

    def test_valid_admin_key_reaches_admin_endpoint(self):
        r = self.client.get("/api/admin/keys", headers={"X-API-Key": self.admin_key})
        self.assertEqual(r.status_code, 200)

    def test_valid_query_key_reaches_blanket_only_endpoint(self):
        # /api/vector/status has no per-route admin dependency — only the
        # blanket "any valid key" gate applies.
        r = self.client.get("/api/vector/status", headers={"X-API-Key": self.query_key})
        self.assertEqual(r.status_code, 200)

    def test_query_key_rejected_on_destructive_vector_clear(self):
        r = self.client.delete("/api/vector/clear", headers={"X-API-Key": self.query_key})
        self.assertEqual(r.status_code, 403)

    def test_admin_key_allowed_on_destructive_vector_clear(self):
        # Mock the actual clear — this test is about the auth gate (does an
        # admin key reach the handler at all), not about exercising a real
        # destructive ChromaDB wipe against whatever the local dev instance
        # has ingested.
        with patch("routers.vector.chroma_client.clear_collection", return_value=0):
            r = self.client.delete("/api/vector/clear", headers={"X-API-Key": self.admin_key})
        self.assertEqual(r.status_code, 200)

    def test_v2_health_exempt_no_key_needed(self):
        r = self.client.get("/api/v2/health")
        self.assertEqual(r.status_code, 200)

    def test_v2_ready_exempt_no_key_needed(self):
        r = self.client.get("/api/v2/ready")
        self.assertEqual(r.status_code, 200)

    def test_gateway_prefix_exempt_from_blanket_middleware(self):
        # gateway.py enforces its own auth via Depends — no key at all should
        # still fail, but via gateway's own 401, not the blanket middleware
        # (i.e. the middleware doesn't double-gate this path). Either way the
        # net result is a clean 401/422, never a silent pass-through.
        r = self.client.post("/api/gateway/query", json={"question": "test"})
        self.assertIn(r.status_code, (401, 422))

    def test_mcp_prefix_exempt_from_blanket_middleware(self):
        # /mcp/ has its own per-tool-call auth (Context-based) — the blanket
        # middleware must not intercept it. A GET here won't be a valid MCP
        # request, but it must not be rejected with the blanket middleware's
        # specific "Invalid or missing X-API-Key header." body.
        r = self.client.get("/mcp/")
        self.assertNotEqual(r.text, '{"detail":"Invalid or missing X-API-Key header."}')

    def test_root_paths_exempt_no_key_needed(self):
        for path in ("/", "/health"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, f"{path} should be reachable with no key")


if __name__ == "__main__":
    unittest.main()
