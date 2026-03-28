# LAKO — Master Changelog
*Running log of all sessions — upload to NotebookLM after each session*

---

## Session 1 — 2026-03-27
**Tool:** OpenClaw (performed by Claude / Cowork)
**Status:** ✅ Complete

### What Was Built
- Full project folder structure matching Section 5 of reference doc
- `backend/main.py` — FastAPI app with CORS, lifespan, all 6 routers registered
- `backend/config.py` — `get_config()` with lru_cache, defaults, reload function
- All 6 router stubs: chat, rag, ingest, confluence, models, vector
- All 7 service stubs: ollama_client, chroma_client, embedder, chunker, rag_engine, vision_service, confluence_client
- All 5 parser stubs: pdf_parser, txt_parser, excel_parser, word_parser, ppt_parser
- `backend/requirements.txt` — all Python dependencies from Section 10
- `config/config.json` — exact template from Section 8, primary_model updated to qwen3.5:9b
- `frontend/package.json` — all npm deps from Section 10
- Frontend skeleton: main.jsx, App.jsx, Sidebar, Header, ProgressBar, SourceCitations, all 6 pages
- Zustand store: appStore.js
- i18n: en.json + nl.json (English and Dutch translations)
- `start_backend.sh`, `start_frontend.sh`, `verify_session1.sh`
- `storage/chromadb/` and `storage/uploads/` with .gitkeep
- `.gitignore`, `README.md`
- `docs/session_01/`: session_explainer.md, technical_reference.md, debugging_guide.md

### Key Decisions
- Model updated: `primary_model` set to `qwen3.5:9b` (replaces original `llama3.1:8b`) per Section 9 model update notes
- All services use `NotImplementedError` stubs with explicit session numbers (Sessions 3–12) indicating when each will be implemented
- Config loaded with `lru_cache` — call `reload_config()` to force disk re-read
- Frontend proxy `/api → :8000` configured in vite.config.js — no CORS issues during development
- Tailwind dark theme (`bg-gray-950`) matches bank-appropriate aesthetic

### Files Changed
- 43 files created
- 0 files modified
- 0 files deleted

### Git Hash
*(run `git add . && git commit -m 'Session 1 complete'` to record hash here)*

---

## Sessions 2–14
*(To be filled in as each session completes)*

---

*Total sessions planned: 14 | Completed: 1 | Remaining: 13*
