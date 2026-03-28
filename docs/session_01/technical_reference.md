# LAKO Session 1 — Technical Reference
**Audience:** Future Claude Code sessions
**Date:** 2026-03-27
**Session:** 1 of 14

---

## Files Created This Session

### Backend

| File | Purpose |
|------|---------|
| `backend/main.py` | FastAPI app with CORS, lifespan, all routers registered |
| `backend/config.py` | `get_config()` with `lru_cache`, `reload_config()`, defaults |
| `backend/routers/__init__.py` | Package marker |
| `backend/routers/chat.py` | `POST /api/chat` — stub |
| `backend/routers/rag.py` | `POST /api/rag/query` — stub |
| `backend/routers/ingest.py` | `POST /api/ingest/docs`, `GET /api/ingest/status` — stub |
| `backend/routers/confluence.py` | `POST /api/ingest/confluence` — stub |
| `backend/routers/models.py` | `GET /api/models` — stub returns hardcoded placeholder |
| `backend/routers/vector.py` | `GET /api/vector/status` — stub |
| `backend/services/__init__.py` | Package marker |
| `backend/services/ollama_client.py` | `OllamaClient` class — all methods `NotImplementedError` |
| `backend/services/chroma_client.py` | `ChromaClient` class — all methods `NotImplementedError` |
| `backend/services/embedder.py` | `Embedder` class — all methods `NotImplementedError` |
| `backend/services/chunker.py` | `Chunker` class + `Chunk` dataclass — all methods `NotImplementedError` |
| `backend/services/rag_engine.py` | `RAGEngine` class — `query()` method `NotImplementedError` |
| `backend/services/vision_service.py` | `VisionService` class — all methods `NotImplementedError` |
| `backend/services/confluence_client.py` | `ConfluenceClient` class — all methods `NotImplementedError` |
| `backend/services/parsers/__init__.py` | Package marker |
| `backend/services/parsers/pdf_parser.py` | `PDFParser` + `ParsedDocument` + `ParsedPage` dataclasses |
| `backend/services/parsers/txt_parser.py` | `TxtParser` |
| `backend/services/parsers/excel_parser.py` | `ExcelParser` |
| `backend/services/parsers/word_parser.py` | `WordParser` |
| `backend/services/parsers/ppt_parser.py` | `PPTParser` |
| `backend/requirements.txt` | All Python dependencies per Section 10 |

### Config

| File | Purpose |
|------|---------|
| `config/config.json` | Exact template from Section 8, `primary_model: qwen3.5:9b` |

### Frontend

| File | Purpose |
|------|---------|
| `frontend/index.html` | HTML entry point |
| `frontend/vite.config.js` | Vite + React plugin, proxy `/api` → `:8000` |
| `frontend/tailwind.config.js` | Tailwind content paths, LAKO brand colors |
| `frontend/postcss.config.js` | PostCSS with Tailwind + autoprefixer |
| `frontend/package.json` | All npm deps per Section 10 |
| `frontend/src/main.jsx` | ReactDOM root, BrowserRouter, i18n init |
| `frontend/src/index.css` | Tailwind directives, dark theme base |
| `frontend/src/App.jsx` | Routes: Dashboard, Chat, DocumentIngestion, ConfluenceIngestion, VectorDB, Settings |
| `frontend/src/components/Sidebar.jsx` | NavLink-based sidebar with Lucide icons |
| `frontend/src/components/Header.jsx` | Language toggle (i18n), page title |
| `frontend/src/components/ProgressBar.jsx` | Animated progress bar component |
| `frontend/src/components/SourceCitations.jsx` | Expandable source citations component |
| `frontend/src/pages/Dashboard.jsx` | Model health cards, vector stats, refresh button |
| `frontend/src/pages/Chat.jsx` | RAG toggle, answer area, streaming input |
| `frontend/src/pages/DocumentIngestion.jsx` | File drop zone, file list, ingest button |
| `frontend/src/pages/ConfluenceIngestion.jsx` | URL input, ingest button |
| `frontend/src/pages/VectorDB.jsx` | ChromaDB stats grid |
| `frontend/src/pages/Settings.jsx` | All config fields, save button |
| `frontend/src/store/appStore.js` | Zustand store: models, vector stats, ingestion, settings |
| `frontend/src/i18n/i18n.js` | i18next init, EN default, NL fallback |
| `frontend/src/i18n/en.json` | English translations |
| `frontend/src/i18n/nl.json` | Dutch translations |

### Scripts & Storage

| File | Purpose |
|------|---------|
| `start_backend.sh` | Activates venv, installs deps, starts uvicorn |
| `start_frontend.sh` | Installs npm deps, starts Vite dev server |
| `verify_session1.sh` | Checks Python, Node, Git, Ollama, models, folder structure |
| `storage/chromadb/.gitkeep` | Placeholder to track empty dir in git |
| `storage/uploads/.gitkeep` | Placeholder to track empty dir in git |
| `.gitignore` | Excludes venv, node_modules, storage data, credentials |
| `README.md` | Full project overview and quick start |

---

## API Endpoints (All Stubbed)

```
GET  /                      → health check
GET  /health                → {"status": "healthy"}
POST /api/chat              → [STUB] direct LLM
POST /api/rag/query         → [STUB] RAG query
POST /api/ingest/docs       → [STUB] file ingestion
GET  /api/ingest/status     → [STUB] progress poll
POST /api/ingest/confluence → [STUB] Confluence page
GET  /api/models            → [STUB] model list
GET  /api/vector/status     → [STUB] ChromaDB stats
```

---

## Data Flow (Full V1 — for reference)

```
User Query
   ↓ React Chat UI
   ↓ POST /api/rag/query
   ↓ RAGEngine.query()
   ↓ Embedder.embed_query()  →  OllamaClient.embed()  →  nomic-embed-text
   ↓ ChromaClient.similarity_search()  →  ChromaDB (local)
   ↓ top_k chunks + filter by similarity_threshold
   ↓ build augmented prompt
   ↓ OllamaClient.chat()  →  qwen3.5:9b
   ↓ answer + source citations
   ↓ React renders answer + SourceCitations component
```

---

## Config Keys

```json
{
  "ollama_url":           "http://localhost:11434",
  "primary_model":        "qwen3.5:9b",
  "vision_model":         "llava:13b",
  "embedding_model":      "nomic-embed-text",
  "chromadb_path":        "/lako/storage/chromadb",
  "confluence_url":       "",
  "confluence_email":     "",
  "confluence_token":     "",
  "top_k":                5,
  "similarity_threshold": 0.7,
  "api_key":              ""
}
```

---

## Session Implementation Map

| Component | Implemented In |
|-----------|---------------|
| Ollama live model list | Session 3 |
| ChromaDB setup | Session 4 |
| Embedder | Session 4 |
| Chunker | Session 4–5 |
| PDF + TXT ingestion | Session 5 |
| Excel/Word/PPT parsers | Session 6 |
| Vision pipeline | Session 7 |
| RAG engine + Chat streaming | Session 8 |
| Confluence ingestion | Session 9 |
| REST API key auth | Session 10 |
| Dashboard polling | Session 11 |
| i18n NL translations full | Session 12 |
