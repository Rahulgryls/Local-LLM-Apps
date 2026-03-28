# LAKO Session 1 — Session Explainer
**Audience:** Non-programmer (you)
**Date:** 2026-03-27
**Session:** 1 of 14 — Environment Setup & Project Skeleton

---

## What We Did Today (Plain English)

Think of building LAKO like constructing a new bank office. Before any staff can work there, you need the building's shell: the rooms must exist, the wiring must be roughed in, the doors must be labelled — even if the furniture isn't in yet.

That's exactly what Session 1 did. We built the empty shell of LAKO:

**The rooms (folders):** Every folder in the project now exists in exactly the right place — backend code in one area, frontend code in another, document storage in another. The structure matches the architectural blueprint (Section 5 of the reference document) precisely.

**The door labels (stub files):** Every Python service and API endpoint now has a file with the right name, the right function signatures, and clear comments saying which future session will fill it in. This means when Claude Code starts Session 2, it knows exactly where to put things — no guessing.

**The plumbing (config):** The `config.json` file is in place with the correct model names — `qwen3.5:9b` as the primary LLM (updated from the original `llama3.1:8b`), `llava:13b` for vision, and `nomic-embed-text` for embeddings. Every piece of code reads model names from this file — nothing is hardcoded.

**The startup switches (shell scripts):** Three scripts exist at the project root:
- `start_backend.sh` — starts the FastAPI server
- `start_frontend.sh` — starts the React web interface
- `verify_session1.sh` — checks that everything you installed manually is working

---

## What LAKO Looks Like Right Now

If you started the backend and opened the Swagger UI (`http://localhost:8000/docs`), you would see all 7 API endpoints listed and documented. None of them return real data yet — they return `[STUB]` placeholder messages — but they all exist and respond correctly.

If you started the frontend (`http://localhost:5173`), you would see a dark-themed web app with a sidebar showing all 6 navigation pages: Dashboard, Chat, Documents, Confluence, Vector DB, Settings. All pages render. The language toggle (EN/NL) is in the header. Nothing connects to the backend yet — that starts in Session 2.

---

## Pega Analogy

In Pega terms, Session 1 is like creating a new application shell in App Studio: you define the application name, the ruleset stack, the class hierarchy — but you haven't built any flows or forms yet. The scaffolding is all there; the rules come in future sessions.

---

## What Could Go Wrong (and How to Spot It)

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `verify_session1.sh` says Python not found | Homebrew install incomplete | Re-run `brew install python@3.11` |
| Ollama models missing | `ollama pull` didn't finish | Re-run `ollama pull qwen3.5:9b` |
| Backend crashes on `uvicorn` start | Python dependency missing | Run `pip install -r requirements.txt` inside `backend/` |
| Frontend shows blank page | Node modules not installed | Run `npm install` inside `frontend/` |
| `config.json` not found warning | Running backend from wrong directory | Always run from inside `backend/` folder |

---

## Next Session (Session 2 — Claude Code)

Claude Code will build the real FastAPI skeleton with working routes and the complete React UI shell with sidebar navigation and routing between all pages.
