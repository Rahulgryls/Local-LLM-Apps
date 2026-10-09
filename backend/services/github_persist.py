"""
LAKO — GitHub-backed persistence ("GitHub as a virtual disk")

Render's free tier has an ephemeral filesystem. This module keeps the whole
storage directory (documents, Qdrant, SQLite, API-key hashes) durable by
snapshotting it to a PRIVATE GitHub repo and restoring it on boot.

  restore()  — called by scripts/restore_snapshot.py before the server starts
  save()     — snapshot -> split into parts -> single orphan commit, force-pushed
  run_autosave() — background loop in main.py's lifespan: pushes once storage
                   has changed AND then stayed quiet for QUIET_SECONDS

Why a snapshot and not committing files live: Qdrant/SQLite files change
constantly and are only consistent when idle; SQLite files are copied with the
sqlite3 backup API. GitHub rejects files > 100 MB, so the tarball is split.
History is deliberately not kept (orphan commit each time) so the repo does not
grow without bound.

Env: GITHUB_TOKEN, GITHUB_DATA_REPO ("owner/repo"), GITHUB_DATA_BRANCH (main),
     LAKO_STORAGE_DIR, GITHUB_ALLOW_PUBLIC (1 = skip the private-repo check),
     GITHUB_DATA_REMOTE_URL (test override), LAKO_SNAPSHOT_PART_MB (50).
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

QUIET_SECONDS = 30
POLL_SECONDS = 15
MAX_SNAPSHOT_MB = 900          # stay well under GitHub's ~1 GB repo guidance
_EXCLUDE_DIRS = {"uploads", "uploads_v3", "uploads_mcp"}   # transient; originals live in documents/
_EXCLUDE_SUFFIXES = (".lock", ".tmp", "-wal", "-shm", "-journal")
_SQLITE_SUFFIXES = (".db", ".sqlite", ".sqlite3")
_save_lock = asyncio.Lock()


def _storage_dir() -> Path:
    return Path(os.environ.get("LAKO_STORAGE_DIR", "/var/data/storage"))


def enabled() -> bool:
    return bool(os.environ.get("GITHUB_DATA_REMOTE_URL") or
                (os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_DATA_REPO")))


def _remote() -> str:
    if os.environ.get("GITHUB_DATA_REMOTE_URL"):
        return os.environ["GITHUB_DATA_REMOTE_URL"]
    return f"https://x-access-token:{os.environ['GITHUB_TOKEN']}@github.com/{os.environ['GITHUB_DATA_REPO']}.git"


def _scrub(text: str) -> str:
    tok = os.environ.get("GITHUB_TOKEN")
    return text.replace(tok, "***") if tok else text


def _git(args: list, cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(
        ["git", "-c", "credential.helper=", "-c", "core.askpass=true", *args],
        cwd=cwd, capture_output=True, text=True, timeout=600,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if check and r.returncode != 0:
        raise RuntimeError(_scrub(f"git {args[0]} failed: {r.stderr.strip()}"))
    return r


def assert_private() -> None:
    """Refuse to sync bank documents to a public repo."""
    if os.environ.get("GITHUB_DATA_REMOTE_URL") or os.environ.get("GITHUB_ALLOW_PUBLIC") == "1":
        return
    import httpx
    r = httpx.get(
        f"https://api.github.com/repos/{os.environ['GITHUB_DATA_REPO']}",
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json"},
        timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Cannot read data repo (HTTP {r.status_code}) — check GITHUB_TOKEN / GITHUB_DATA_REPO.")
    if not r.json().get("private"):
        raise RuntimeError("GITHUB_DATA_REPO is PUBLIC — refusing to sync documents. Make it private.")


def _included(rel: Path) -> bool:
    if rel.parts and rel.parts[0] in _EXCLUDE_DIRS:
        return False
    return not rel.name.endswith(_EXCLUDE_SUFFIXES)


def _files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink() and _included(p.relative_to(root)):
            yield p


def fingerprint(root: Path) -> str:
    """Change detector. api_keys.json is hashed by identity only: validate_key()
    rewrites last_used on every request and must not trigger a push."""
    h = hashlib.sha256()
    for p in _files(root):
        rel = p.relative_to(root).as_posix()
        if rel == "api_keys.json":
            try:
                keys = json.loads(p.read_text()).get("keys", [])
                h.update(json.dumps([(k.get("id"), k.get("is_active")) for k in keys]).encode())
            except Exception:
                pass
            continue
        st = p.stat()
        h.update(f"{rel}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()


def _stage(root: Path, stage: Path) -> None:
    for p in _files(root):
        dest = stage / p.relative_to(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if p.name.endswith(_SQLITE_SUFFIXES):
            try:
                src = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
                dst = sqlite3.connect(dest)
                with dst:
                    src.backup(dst)
                src.close(); dst.close()
                continue
            except sqlite3.Error:
                logger.warning("sqlite backup failed for %s — copying raw", p)
        shutil.copy2(p, dest)


def save() -> dict:
    """Blocking: snapshot storage and force-push it as a single orphan commit."""
    root = _storage_dir()
    if not root.exists():
        return {"pushed": False, "reason": "no storage dir"}
    assert_private()
    part_bytes = int(float(os.environ.get("LAKO_SNAPSHOT_PART_MB", "50")) * 1024 * 1024)
    branch = os.environ.get("GITHUB_DATA_BRANCH", "main")

    with tempfile.TemporaryDirectory(prefix="lako-snap-") as tmp:
        tmp = Path(tmp)
        stage, repo = tmp / "stage", tmp / "repo"
        stage.mkdir(); repo.mkdir()
        _stage(root, stage)
        tarball = tmp / "snapshot.tar.gz"
        with tarfile.open(tarball, "w:gz") as tf:
            tf.add(stage, arcname=".")
        size = tarball.stat().st_size
        if size > MAX_SNAPSHOT_MB * 1024 * 1024:
            raise RuntimeError(f"Snapshot is {size // 2**20} MB (> {MAX_SNAPSHOT_MB} MB) — not pushing.")

        _git(["init", "-q", "-b", branch], repo)
        _git(["config", "user.name", "lako-persist"], repo)
        _git(["config", "user.email", "lako-persist@users.noreply.github.com"], repo)
        n = 0
        with open(tarball, "rb") as f:
            while chunk := f.read(part_bytes):
                (repo / f"snapshot.part{n:04d}").write_bytes(chunk)
                n += 1
        (repo / "MANIFEST.json").write_text(json.dumps(
            {"parts": n, "bytes": size, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
        _git(["add", "-A"], repo)
        _git(["commit", "-q", "-m", "LAKO storage snapshot"], repo)
        _git(["push", "-q", "--force", _remote(), f"HEAD:refs/heads/{branch}"], repo)
    logger.info("snapshot pushed: %d part(s), %d bytes", n, size)
    return {"pushed": True, "parts": n, "bytes": size}


def restore() -> dict:
    """Blocking: pull the latest snapshot into the storage dir (no-op if none)."""
    root = _storage_dir()
    assert_private()
    branch = os.environ.get("GITHUB_DATA_BRANCH", "main")
    with tempfile.TemporaryDirectory(prefix="lako-restore-") as tmp:
        tmp = Path(tmp)
        r = _git(["clone", "-q", "--depth", "1", "--branch", branch, _remote(), str(tmp / "repo")], tmp, check=False)
        repo = tmp / "repo"
        if r.returncode != 0 or not (repo / "MANIFEST.json").exists():
            logger.info("no snapshot to restore (%s)", _scrub(r.stderr.strip()[:200]))
            return {"restored": False}
        manifest = json.loads((repo / "MANIFEST.json").read_text())
        tarball = tmp / "snapshot.tar.gz"
        with open(tarball, "wb") as out:
            for i in range(manifest["parts"]):
                out.write((repo / f"snapshot.part{i:04d}").read_bytes())
        if tarball.stat().st_size != manifest["bytes"]:
            raise RuntimeError("Snapshot corrupt: size mismatch — refusing to restore.")
        root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tarball, "r:gz") as tf:
            tf.extractall(root, filter="data")
    logger.info("snapshot restored into %s", root)
    return {"restored": True, **manifest}


async def run_autosave() -> None:
    """Push whenever storage changed and has been quiet for QUIET_SECONDS."""
    root = _storage_dir()
    last_pushed = fingerprint(root) if root.exists() else ""   # state just restored = already durable
    pending, since = None, 0.0
    while True:
        await asyncio.sleep(POLL_SECONDS)
        try:
            fp = fingerprint(root)
            if fp == last_pushed:
                pending = None
                continue
            if fp != pending:
                pending, since = fp, time.monotonic()
                continue
            if time.monotonic() - since >= QUIET_SECONDS:
                async with _save_lock:
                    await asyncio.to_thread(save)
                last_pushed, pending = fp, None
        except asyncio.CancelledError:
            raise
        except Exception as exc:   # never kill the app over a failed backup; retry next cycle
            logger.error("autosave failed: %s", _scrub(str(exc)))


async def flush() -> None:
    """Final push on shutdown (Render sends SIGTERM before sleeping/redeploying)."""
    try:
        async with _save_lock:
            await asyncio.wait_for(asyncio.to_thread(save), timeout=25)
    except Exception as exc:
        logger.error("shutdown flush failed: %s", _scrub(str(exc)))
