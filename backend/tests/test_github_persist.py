"""
LAKO — GitHub persistence round-trip (services/github_persist.py)

Uses a local bare git repo as the "remote" (GITHUB_DATA_REMOTE_URL) so the
real git/tar/split/sqlite-backup code path runs without network.

Run from backend/:  python -m pytest tests/test_github_persist.py -v
"""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from services import github_persist as gp


@pytest.fixture
def env(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    store = tmp_path / "storage"
    store.mkdir()
    monkeypatch.setenv("GITHUB_DATA_REMOTE_URL", str(remote))
    monkeypatch.setenv("LAKO_STORAGE_DIR", str(store))
    monkeypatch.setenv("LAKO_SNAPSHOT_PART_MB", "0.001")   # ~1 KB parts -> forces splitting
    return tmp_path, remote, store


def test_roundtrip_restores_everything_and_skips_transient(env, monkeypatch):
    tmp, remote, store = env
    (store / "documents" / "d1").mkdir(parents=True)
    (store / "documents" / "d1" / "original.pdf").write_bytes(os.urandom(5000))
    (store / "uploads_v3").mkdir()
    (store / "uploads_v3" / "temp.bin").write_bytes(b"transient")
    (store / "qdrant").mkdir()
    (store / "qdrant" / ".lock").write_text("x")
    db = sqlite3.connect(store / "lako.db")
    db.execute("create table t(x)"); db.execute("insert into t values ('hello')"); db.commit(); db.close()

    out = gp.save()
    assert out["pushed"] and out["parts"] > 1

    fresh = tmp / "fresh"
    monkeypatch.setenv("LAKO_STORAGE_DIR", str(fresh))
    assert gp.restore()["restored"]
    assert (fresh / "documents/d1/original.pdf").read_bytes() == (store / "documents/d1/original.pdf").read_bytes()
    assert sqlite3.connect(fresh / "lako.db").execute("select x from t").fetchone() == ("hello",)
    assert not (fresh / "uploads_v3").exists()
    assert not (fresh / "qdrant/.lock").exists()


def test_restore_with_empty_remote_is_noop(env):
    assert gp.restore() == {"restored": False}


def test_fingerprint_ignores_last_used_but_sees_new_keys_and_files(tmp_path):
    import json
    (tmp_path / "api_keys.json").write_text(json.dumps({"keys": [{"id": "a", "is_active": True, "last_used": None}]}))
    f1 = gp.fingerprint(tmp_path)
    (tmp_path / "api_keys.json").write_text(json.dumps({"keys": [{"id": "a", "is_active": True, "last_used": "now"}]}))
    assert gp.fingerprint(tmp_path) == f1                  # per-request noise
    (tmp_path / "api_keys.json").write_text(json.dumps({"keys": [{"id": "a", "is_active": False, "last_used": "now"}]}))
    assert gp.fingerprint(tmp_path) != f1                  # revoke is a real change
    f2 = gp.fingerprint(tmp_path)
    (tmp_path / "new.txt").write_text("doc")
    assert gp.fingerprint(tmp_path) != f2


def test_public_repo_is_refused(monkeypatch):
    class R:
        status_code = 200
        def json(self): return {"private": False}
    monkeypatch.delenv("GITHUB_DATA_REMOTE_URL", raising=False)
    monkeypatch.delenv("GITHUB_ALLOW_PUBLIC", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "t"); monkeypatch.setenv("GITHUB_DATA_REPO", "o/r")
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    with pytest.raises(RuntimeError, match="PUBLIC"):
        gp.assert_private()
