"""
LAKO — Hosted-UI gate tests (main.py `_ui_gate`)

The gate is configured from env vars read at import time, so each scenario
runs in a fresh interpreter against the real app (no lifespan, same as
test_auth_middleware.py).

Run from backend/:
    python -m pytest tests/test_ui_gate.py -v
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).parent.parent

_SCRIPT = r"""
import base64, json, sys
sys.path.insert(0, ".")
from fastapi.testclient import TestClient
from services.api_key_manager import api_key_manager
import main

ui_key = api_key_manager.generate_key("t", ["query", "ingest", "admin"])["key"]
main._UI_API_KEY = ui_key
good = {"Authorization": "Basic " + base64.b64encode(b"bob:pw").decode()}
bad  = {"Authorization": "Basic " + base64.b64encode(b"bob:nope").decode()}
c = TestClient(main.app)
out = {
  "no_creds_ui":      c.get("/docs").status_code,
  "bad_creds_api":    c.get("/api/cache/stats", headers=bad).status_code,
  "www_auth":         c.get("/docs").headers.get("www-authenticate"),
  "good_creds_docs":  c.get("/docs", headers=good).status_code,
  "good_creds_api":   c.get("/api/dashboard/stats", headers=good).status_code,
  "health_open":      c.get("/health").status_code in (200, 500),
  "v2_health_open":   c.get("/api/v2/health").status_code,
  "own_key_no_basic": c.get("/api/dashboard/stats", headers={"X-API-Key": ui_key}).status_code,
  "bogus_key":        c.get("/api/dashboard/stats", headers={"X-API-Key": "lako_bogus"}).status_code,
}
print("RESULT" + json.dumps(out))
"""


def _run(env_extra: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        env = {
            **os.environ,
            "API_KEYS_PATH": str(Path(tmp) / "api_keys.json"),
            "LAKO_STORAGE_DIR": tmp,
            **env_extra,
        }
        r = subprocess.run(
            [sys.executable, "-c", _SCRIPT], cwd=BACKEND, env=env,
            capture_output=True, text=True, timeout=120,
        )
    line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT")), None)
    assert line, f"no result\nstdout={r.stdout}\nstderr={r.stderr[-2000:]}"
    return json.loads(line[6:])


def test_gate_enforces_basic_auth_and_injects_key():
    out = _run({"LAKO_BASIC_AUTH_USERS": "bob:pw"})
    assert out["no_creds_ui"] == 401
    assert out["www_auth"] == 'Basic realm="LAKO"'
    assert out["bad_creds_api"] == 401
    assert out["good_creds_docs"] == 200
    assert out["good_creds_api"] == 200          # UI key injected after Basic auth
    assert out["v2_health_open"] == 200
    assert out["own_key_no_basic"] == 200        # API clients bypass Basic auth
    assert out["bogus_key"] == 401               # ...but still need a valid key
