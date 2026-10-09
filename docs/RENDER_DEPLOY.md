# Deploying LAKO on Render

One Render web service (Docker) serves the React UI, the `/api/*` backend and the `/mcp/` endpoint.
Config lives in `render.yaml` (Blueprint), same pattern as the Customer Intake host.

## What runs where

| Piece | Where |
|---|---|
| FastAPI + React UI + MCP (`/mcp/`) | Render (this Blueprint) |
| Qdrant (embedded), SQLite, documents, API-key hashes | Render's ephemeral disk, **backed up to a private GitHub repo** (see below) |
| **Ollama (LLM + embeddings)** | **Not on Render** — it has no GPUs. Keep it on your Mac and expose it (e.g. Cloudflare Tunnel), then set `OLLAMA_URL`. Without a reachable Ollama the UI loads but queries and ingestion fail. |

## Deploy

1. Render dashboard -> **New -> Blueprint** -> pick this repo -> branch.
2. Fill the prompted env vars (they are `sync: false`, never committed):

   | Var | Value |
   |---|---|
   | `OLLAMA_URL` | Public URL of your Ollama, e.g. `https://ollama-xyz.trycloudflare.com` |
   | `LAKO_BASIC_AUTH_USERS` | Browser login, `user:password` (comma-separate for several) |
   | `LAKO_UI_API_KEY` | `python -c "import secrets; print('lako_' + secrets.token_urlsafe(32))"` |
   | `LAKO_MCP_ALLOWED_HOSTS` | Your hostname, no scheme, e.g. `lako.onrender.com` |
   | `CONFLUENCE_*` | Optional |

3. Open `https://<service>.onrender.com`, log in with the Basic-auth credentials.

## How access works

- **Browser:** HTTP Basic auth -> the server attaches `LAKO_UI_API_KEY` to `/api/*` (replaces the Vite dev proxy).
  If `LAKO_BASIC_AUTH_USERS` is unset the UI/API are not Basic-gated, but `/api/*` still requires a valid `X-API-Key`.
- **Pega / API clients:** `https://<service>.onrender.com/mcp/` (trailing slash) with `X-API-Key`.
  Mint a `query`-tier key from the UI's Settings or `POST /api/admin/keys`.

## GitHub as the disk (free plan)

Render's free disk is wiped on every restart/sleep. `services/github_persist.py` makes GitHub the durable copy:

1. Create a **separate private repo** (e.g. `lako-data`). The app refuses to sync to a public repo.
2. Create a fine-grained PAT with **Contents: read & write on that repo only**.
3. Set `GITHUB_TOKEN` and `GITHUB_DATA_REPO` (`owner/repo`) in Render.

Behaviour: on boot the latest snapshot is restored; while running, storage is pushed ~30 s after the last change; a final push happens on shutdown (SIGTERM).
Snapshots are split into 50 MB parts (GitHub's file limit is 100 MB) and force-pushed as one commit, so there is **no history/rollback** and the repo stays small. Hard cap: 900 MB. Upload temp dirs are excluded; original files live in `documents/`.

Limits to know: a crash/OOM between a change and the next push loses that change (up to ~30 s); free services sleep after 15 min idle, so the first request after sleep waits for restore + boot; free RAM is 512 MB, which may be tight for PyMuPDF/Qdrant — if the instance is OOM-killed, move to `starter`.

## Notes

- Env vars override `config/config.json` (`OLLAMA_URL`, `PRIMARY_MODEL`, `VISION_MODEL`, `EMBEDDING_MODEL`, `CHROMADB_PATH`, `API_KEYS_PATH`, `CONFLUENCE_*`, ...). Settings changes saved from the UI write to the container's `config.json` and are lost on redeploy; use env vars for anything permanent.
- `mcp` is pinned `<2` in `requirements.txt`; v2 removed `FastMCP` and breaks `mcp_server.py`.
