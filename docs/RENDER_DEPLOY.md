# Deploying LAKO on Render

One Render web service (Docker) serves the React UI, the `/api/*` backend and the `/mcp/` endpoint.
Config lives in `render.yaml` (Blueprint), same pattern as the Customer Intake host.

## What runs where

| Piece | Where |
|---|---|
| FastAPI + React UI + MCP (`/mcp/`) | Render (this Blueprint) |
| Qdrant (embedded), SQLite, uploads, API keys | Render persistent disk at `/var/data` |
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

## Notes

- `plan: starter` is required: persistent disks are not on the free plan, and the free 512 MB RAM is too small for PyMuPDF/Qdrant/Chroma.
- Env vars override `config/config.json` (`OLLAMA_URL`, `PRIMARY_MODEL`, `VISION_MODEL`, `EMBEDDING_MODEL`, `CHROMADB_PATH`, `API_KEYS_PATH`, `CONFLUENCE_*`, ...). Settings changes saved from the UI write to the container's `config.json` and are lost on redeploy; use env vars for anything permanent.
- `mcp` is pinned `<2` in `requirements.txt`; v2 removed `FastMCP` and breaks `mcp_server.py`.
