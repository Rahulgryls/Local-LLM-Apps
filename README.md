# LAKO — Local AI Knowledge Orchestrator

**Version:** V1
**Build:** 14 sessions / 4–5 weeks
**Target:** Internal bank AI knowledge platform (Rabobank)
**Developer:** Vibe coding — Claude Code + OpenClaw
**Last updated:** Session 2 complete — 2026-03-28

> **Core principle:** Everything runs locally. No cloud calls. No external API keys. No data leaves the bank's infrastructure — satisfying GDPR, Dutch banking secrecy law, and DNB regulatory requirements.

---

## What LAKO Does (Plain English)

LAKO is a private, internal search engine powered by AI. Instead of typing keywords into SharePoint and getting nothing useful, a bank employee types a natural language question — *"What is our policy on third-party vendor risk in cloud contracts?"* — and LAKO finds the answer by searching through all the bank's internal documents that have been loaded into it.

Everything runs on a server inside the bank. No question, no document, and no answer ever leaves the building.

**LAKO does five things:**
1. **Ingests documents** — you upload PDFs, Word files, Excel sheets, PowerPoint decks, and text files. LAKO reads them, breaks them into searchable chunks, and stores them locally.
2. **Ingests Confluence pages** — you paste a Confluence URL and LAKO fetches and stores that page's content.
3. **Understands images and diagrams** — for PDFs with flowcharts or process diagrams, LAKO uses a local vision AI model to describe what the image shows, so diagrams become searchable text.
4. **Answers questions via RAG** — RAG (Retrieval-Augmented Generation) means: find the most relevant document chunks first, then ask the AI to answer the question *using only those chunks*. This prevents hallucination and grounds every answer in real documents.
5. **Shows its sources** — every answer shows which document, which page, and which section it came from.

---

## What LAKO Is NOT (V1)

- Not a desktop app — browser only
- Not a chat history system — stateless, one question at a time
- Not a cloud service — 100% local via Ollama
- Not a multi-user login system — internal network access assumed

---

## Technology Stack — What Each Layer Does

| Layer | Technology | Plain English Explanation |
|---|---|---|
| Backend | Python FastAPI | The server that runs all the logic. Receives requests from the browser, processes documents, queries the AI models, returns answers. FastAPI is async — it can handle multiple requests at once without blocking. |
| Frontend | React + Vite | The browser interface. React is a JavaScript framework for building interactive UIs. Vite is the tool that compiles and serves the React app during development. |
| Styling | TailwindCSS | Utility-based CSS framework. Styles are applied by adding class names directly in the HTML — no separate CSS files needed. Gives LAKO its dark blue bank-appropriate look. |
| State Management | Zustand | A small library that keeps track of the app's data in the browser — which models are available, ingestion progress, settings values. Think of it as the frontend's memory between page navigations. |
| LLM Runtime | Ollama | The local AI model runner. Ollama downloads and serves AI models on your machine. LAKO talks to Ollama via its REST API at port 11434. Without Ollama, there is no AI. |
| Primary LLM | qwen3.5:9b | The main language model used for answering questions. Qwen3.5 is made by Alibaba, trained on 119 languages including Dutch, with a 256K token context window. Chosen over llama3.1:8b specifically because Dutch language quality is critical for Rabobank. |
| Vision Model | llava:13b | A multimodal model that can look at images. LAKO extracts images from PDFs and sends each one to llava, which describes what it sees. The description is then stored as text and becomes searchable. |
| Embeddings | nomic-embed-text | Converts text into numerical vectors (lists of numbers). Two pieces of text that mean similar things will produce similar vectors. This is how ChromaDB can find relevant document chunks from a question — by comparing vector similarity. |
| Vector DB | ChromaDB | A local database that stores document chunks as vectors. When you ask a question, LAKO converts your question to a vector and ChromaDB finds the stored chunks with the closest vectors. No Docker required — runs as a Python library. |
| PDF Parsing | PyMuPDF (fitz) | Python library for reading PDFs. Extracts text page by page, and also extracts embedded images for vision processing. |
| OCR Fallback | Tesseract | If a PDF is a scanned image rather than a text PDF, Tesseract runs optical character recognition to extract the text. This is the fallback when PyMuPDF finds no text. |
| Excel Parsing | openpyxl + pandas | openpyxl reads .xlsx files. pandas converts spreadsheet data into structured text that can be chunked and embedded. |
| Word Parsing | python-docx | Reads .docx files — extracts paragraphs, headings, and table content. |
| PPT Parsing | python-pptx | Reads .pptx files — extracts slide text and speaker notes. |
| i18n | react-i18next | Internationalisation framework. All UI text is stored in translation files (en.json and nl.json). A toggle in the header switches the entire UI between English and Dutch. |
| Config | config.json | A single JSON file that stores all model names, paths, and settings. Nothing is hardcoded in the Python or JavaScript code. Changing a model is a one-line edit in this file. |

---

## Model Stack — Key Decisions

### Why qwen3.5:9b (not llama3.1:8b)

| Factor | llama3.1:8b | qwen3.5:9b |
|---|---|---|
| Dutch language (NL) | Decent | Excellent — 119 languages |
| RAG context window | 128K tokens | 256K tokens |
| Thinking mode | No | Yes |
| RAM required | ~8.5 GB | ~9.3 GB |

**The deciding factor:** Rabobank documents mix Dutch and English. Qwen3.5 handles this significantly better. The 256K context window also means more document chunks can be injected into a single RAG prompt.

**Vendor note:** Qwen is made by Alibaba (China). Since LAKO runs fully on-premises with zero external calls, no data reaches Alibaba. If Rabobank's vendor approval requires Meta (US) origin, `llama3.3:8b` is a drop-in alternative — one line in config.json.

### Why llava:13b stays as Vision Model

Qwen3.5 technically has vision capability, but the required vision files (mmproj files) do not yet work with Ollama's local serving architecture. llava:13b is Ollama-native, reliable, and well-tested for document diagram description.

### RAM usage on 48 GB MacBook

| Scenario | Models Active | RAM Used |
|---|---|---|
| Chat / RAG query | qwen3.5:9b + nomic | ~9.3 GB |
| Document ingestion | llava:13b + nomic | ~11.0 GB |
| Worst case (all loaded) | all three | ~19.8 GB |

Ollama auto-unloads models after 5 minutes idle. The three models are almost never all in memory simultaneously.

---

## Architecture — How the Parts Connect

```
Browser (React + Vite)
        :5173
          |
          |  HTTP / REST (axios)
          |
  FastAPI Backend
        :8000
          |
    ------+------+----------+
    |            |          |
  Ollama      ChromaDB   File Storage
  :11434      (local)    /storage/uploads
    |
  ■ qwen3.5:9b     — answers questions
  ■ llava:13b      — describes images
  ■ nomic-embed-text — converts text to vectors
```

**Request flow for a RAG question:**
1. User types question in browser → React sends POST to `/api/rag/query`
2. FastAPI receives question → embedder converts it to a vector via nomic-embed-text
3. ChromaDB searches for the top 5 most similar document chunks
4. FastAPI builds a prompt: *"Using these document chunks: [chunks]. Answer this question: [question]"*
5. FastAPI sends the prompt to qwen3.5:9b via Ollama
6. qwen3.5:9b streams the answer token by token back to FastAPI
7. FastAPI streams the answer back to the browser
8. React displays the answer + source citations (filename, page, chunk type)

---

## Project Folder Structure — Every File Explained

```
lako/
├── backend/                        ← All Python server code
│   ├── main.py                     ← FastAPI app entry point. Registers all routers,
│   │                                 configures CORS, runs startup/shutdown logging.
│   │                                 Start command: uvicorn main:app --reload
│   │
│   ├── config.py                   ← Config loader. Reads config/config.json from disk.
│   │                                 Uses lru_cache so the file is only read once.
│   │                                 Never hardcodes model names — always reads from config.
│   │
│   ├── requirements.txt            ← All Python library dependencies. Install with:
│   │                                 pip install -r requirements.txt
│   │
│   ├── .venv/                      ← Python virtual environment (created Session 2).
│   │                                 Isolates LAKO's Python packages from the system.
│   │                                 Activate with: source .venv/bin/activate
│   │
│   ├── routers/                    ← API route handlers. Each file = one group of endpoints.
│   │   │                             Think of these as Pega service activities — they receive
│   │   │                             a request, process it, return a response.
│   │   │
│   │   ├── chat.py                 ← POST /api/chat
│   │   │                             Direct LLM query. Takes a prompt, sends to Ollama,
│   │   │                             returns the answer. No document search involved.
│   │   │                             STUB until Session 8.
│   │   │
│   │   ├── rag.py                  ← POST /api/rag/query
│   │   │                             RAG query. Takes a question, searches ChromaDB,
│   │   │                             injects relevant chunks, asks qwen3.5:9b, returns
│   │   │                             answer + source citations.
│   │   │                             STUB until Session 8.
│   │   │
│   │   ├── ingest.py               ← POST /api/ingest/docs — upload files
│   │   │                             GET  /api/ingest/status — poll progress (job_id)
│   │   │                             Accepts file uploads, creates a job_id, returns it
│   │   │                             so the frontend can poll for progress.
│   │   │                             STUB until Sessions 5–7.
│   │   │
│   │   ├── confluence.py           ← POST /api/ingest/confluence
│   │   │                             Takes a Confluence page URL, fetches the page content,
│   │   │                             runs it through the ingestion pipeline.
│   │   │                             STUB until Session 9.
│   │   │
│   │   ├── models.py               ← GET /api/models
│   │   │                             Returns all Ollama models installed on this machine,
│   │   │                             plus which model is assigned to each role (primary/
│   │   │                             vision/embedding). Used to populate dropdowns in UI.
│   │   │                             STUB until Session 3.
│   │   │
│   │   └── vector.py               ← GET /api/vector/status
│   │                                 Returns ChromaDB health, total chunk count, collection
│   │                                 info. Used by Dashboard page.
│   │                                 STUB until Session 4.
│   │
│   └── services/                   ← Business logic. Routers call services.
│       │                             Think of services as Pega utility rules or data
│       │                             transforms — they do the actual work.
│       │
│       ├── ollama_client.py        ← Wrapper for Ollama API calls. Handles chat, streaming,
│       │                             model listing, and embedding requests.
│       │                             STUB until Session 3.
│       │
│       ├── chroma_client.py        ← Wrapper for ChromaDB. Creates collections, stores
│       │                             chunks with metadata, performs similarity searches.
│       │                             STUB until Session 4.
│       │
│       ├── embedder.py             ← Converts text to vectors by calling nomic-embed-text
│       │                             via Ollama. Used during ingestion and RAG queries.
│       │                             STUB until Session 4.
│       │
│       ├── chunker.py              ← Splits large text into 300–600 token chunks with
│       │                             50–100 token overlap. Overlap ensures a sentence at
│       │                             the edge of one chunk is also in the next chunk.
│       │                             STUB until Session 4.
│       │
│       ├── rag_engine.py           ← Orchestrates the full RAG pipeline: embed question →
│       │                             search ChromaDB → build prompt → call qwen3.5:9b →
│       │                             return answer + sources.
│       │                             STUB until Session 8.
│       │
│       ├── vision_service.py       ← Sends extracted images to llava:13b and gets back
│       │                             a text description. Called during PDF ingestion when
│       │                             an embedded diagram or image is found.
│       │                             STUB until Session 7.
│       │
│       ├── confluence_client.py    ← Fetches a Confluence page by URL using the Confluence
│       │                             REST API. Parses the HTML body using BeautifulSoup.
│       │                             STUB until Session 9.
│       │
│       └── parsers/                ← One file per document format.
│           ├── pdf_parser.py       ← PyMuPDF text extraction + image extraction per page.
│           │                         Falls back to Tesseract OCR for scanned pages.
│           │                         STUB until Session 5.
│           ├── txt_parser.py       ← Plain text reader. STUB until Session 5.
│           ├── excel_parser.py     ← openpyxl + pandas. Sheet name + cell data → text.
│           │                         STUB until Session 6.
│           ├── word_parser.py      ← python-docx. Paragraphs + headings + tables → text.
│           │                         STUB until Session 6.
│           └── ppt_parser.py       ← python-pptx. Slide text + speaker notes → text.
│                                     STUB until Session 6.
│
├── frontend/                       ← All React browser interface code
│   ├── index.html                  ← The single HTML page. React mounts into <div id="root">.
│   │
│   ├── vite.config.js              ← Vite build tool configuration.
│   │                                 Sets dev server port to 5173.
│   │                                 Proxies /api/* requests to http://localhost:8000
│   │                                 so the browser never sees cross-origin issues
│   │                                 during development.
│   │
│   ├── tailwind.config.js          ← TailwindCSS configuration.
│   │                                 Defines custom LAKO brand colours:
│   │                                 lako-blue, lako-blue-light, lako-accent.
│   │                                 Scans all .jsx files to generate only used CSS.
│   │
│   ├── postcss.config.js           ← PostCSS configuration.
│   │                                 Tells Vite to run TailwindCSS and Autoprefixer on
│   │                                 CSS during the build. Required for Tailwind v3.
│   │
│   ├── package.json                ← Frontend dependencies and build scripts.
│   │                                 NOTE: @tailwindcss/vite and @shadcn/ui were removed
│   │                                 — they are Tailwind v4 packages incompatible with
│   │                                 the Tailwind v3 + PostCSS setup used here.
│   │
│   └── src/
│       ├── main.jsx                ← React entry point. Wraps the app with BrowserRouter
│       │                             (enables URL-based navigation) and initialises i18n.
│       │
│       ├── App.jsx                 ← Root layout component. Always visible wrapper.
│       │                             Left: <Sidebar /> with nav links
│       │                             Top: <Header /> with page title + language toggle
│       │                             Middle: <Routes> — swaps page content based on URL
│       │
│       ├── index.css               ← Global styles. Applies Tailwind base styles.
│       │                             Sets dark background, custom scrollbar colours.
│       │
│       ├── pages/                  ← One file per page. Swapped in by React Router.
│       │   │                         Think of each page as a Pega section — it fills
│       │   │                         the main content area when its nav link is clicked.
│       │   │
│       │   ├── Dashboard.jsx       ← /dashboard route.
│       │   │                         Shows model health status (green/red per role),
│       │   │                         ChromaDB stats (chunk count, status), Refresh button.
│       │   │                         STUB — health pings wired in Session 11.
│       │   │
│       │   ├── Chat.jsx            ← /chat route.
│       │   │                         Main question-answering interface.
│       │   │                         RAG toggle (on = search documents, off = direct LLM),
│       │   │                         text input, streaming answer display, source citations.
│       │   │                         STUB — Ollama calls wired in Session 8.
│       │   │
│       │   ├── DocumentIngestion.jsx ← /ingest/docs route.
│       │   │                           File upload UI with drag-and-drop zone.
│       │   │                           Accepts PDF, DOCX, XLSX, PPTX, TXT.
│       │   │                           Shows progress bar during ingestion.
│       │   │                           STUB — upload pipeline wired in Session 5.
│       │   │
│       │   ├── ConfluenceIngestion.jsx ← /ingest/confluence route.
│       │   │                             URL input form. Paste a Confluence page URL,
│       │   │                             click Ingest. STUB until Session 9.
│       │   │
│       │   ├── VectorDB.jsx        ← /vector route.
│       │   │                         Shows ChromaDB stats: status, total chunks,
│       │   │                         collection count, storage path. Refresh button.
│       │   │                         STUB — ChromaDB wired in Session 4.
│       │   │
│       │   └── Settings.jsx        ← /settings route.
│       │                             Form with all configurable fields:
│       │                             Model names per role, Ollama URL, ChromaDB path,
│       │                             Confluence URL/email/token, Top-K, threshold.
│       │                             Save writes back to config.json via backend.
│       │                             STUB — persistence wired in Session 3.
│       │
│       ├── components/             ← Reusable UI pieces used across multiple pages.
│       │   │
│       │   ├── Sidebar.jsx         ← Left navigation panel. Always visible.
│       │   │                         Uses NavLink from react-router-dom — automatically
│       │   │                         highlights the active page in blue.
│       │   │                         Nav items: Dashboard, Chat, Documents, Confluence,
│       │   │                         Vector DB, Settings.
│       │   │                         Labels come from i18n translation files (EN/NL).
│       │   │
│       │   ├── Header.jsx          ← Top bar. Always visible.
│       │   │                         Shows current page title on the left.
│       │   │                         Language toggle button (EN ↔ NL) on the right.
│       │   │                         Reads current URL path to determine page title.
│       │   │
│       │   ├── ProgressBar.jsx     ← Reusable progress bar component.
│       │   │                         Used on Document Ingestion page during file processing.
│       │   │                         Takes a progress value (0–100) and a label string.
│       │   │
│       │   └── SourceCitations.jsx ← Expandable source panel shown under each RAG answer.
│       │                             Displays: filename, page number, chunk type, score.
│       │                             Collapsed by default — click to expand.
│       │                             Wired in Session 8 when RAG returns real sources.
│       │
│       ├── store/
│       │   └── appStore.js         ← Zustand global state store.
│       │                             Holds: available models list, selected models per role,
│       │                             model health status, vector DB stats, ingestion job
│       │                             progress, and settings mirror.
│       │                             Think of this as LAKO's in-browser clipboard — all
│       │                             pages can read and write to it without passing props.
│       │
│       └── i18n/
│           ├── i18n.js             ← i18next initialisation. Loads en.json and nl.json.
│           │                         Sets English as default. React-i18next hooks then
│           │                         let any component call t('nav.dashboard') to get
│           │                         the right translation for the current language.
│           ├── en.json             ← All English UI strings.
│           └── nl.json             ← All Dutch UI strings.
│
├── storage/
│   ├── chromadb/                   ← ChromaDB persists its vector data here.
│   │                                 This folder grows as you ingest documents.
│   │                                 Back this up if you want to preserve your knowledge base.
│   └── uploads/                    ← Uploaded files are saved here before ingestion.
│                                     After ingestion, files remain here as an archive.
│
├── config/
│   └── config.json                 ← THE single source of truth for all settings.
│                                     Never hardcoded anywhere in Python or JavaScript.
│                                     See Configuration section below for all fields.
│
├── docs/
│   ├── Master_Changelog.md         ← Running log of every session: what was built,
│   │                                 decisions made, git hash, date.
│   │                                 Upload to NotebookLM after every session.
│   └── session_01/                 ← Session 1 documentation (3 files per session):
│       ├── session_explainer.md    ← Plain English: what was built and why
│       ├── technical_reference.md  ← Files changed, functions, data flow
│       └── debugging_guide.md      ← Errors encountered + hypothetical future errors
│
├── start_backend.sh                ← Convenience script to activate venv and start uvicorn
├── start_frontend.sh               ← Convenience script to run npm run dev
└── verify_session1.sh              ← Checks all Session 1 requirements pass
```

---

## Configuration Reference — config/config.json

Every setting LAKO uses comes from this one file. Edit it and restart the backend.

```json
{
  "ollama_url":           "http://localhost:11434",
  "primary_model":        "qwen3.5:9b",
  "vision_model":         "llava:13b",
  "embedding_model":      "nomic-embed-text",
  "chromadb_path":        "/lako/storage/chromadb",
  "confluence_url":       "https://yourbank.atlassian.net",
  "confluence_email":     "",
  "confluence_token":     "",
  "top_k":                5,
  "similarity_threshold": 0.7,
  "api_key":              ""
}
```

| Field | What It Does |
|---|---|
| `ollama_url` | Where Ollama is running. Default is localhost. On a server, change to the server's IP. |
| `primary_model` | The LLM that answers questions. Change to `qwen3:14b` or `qwen3:32b` on a server with more RAM. |
| `vision_model` | The model used to describe images extracted from PDFs. |
| `embedding_model` | The model that converts text to vectors. Must match what was used during ingestion. |
| `chromadb_path` | Where ChromaDB stores its files on disk. |
| `confluence_url` | Your Confluence base URL. |
| `confluence_email` | Your Confluence login email (used for API auth). |
| `confluence_token` | Your Confluence API token (generated in Confluence account settings). |
| `top_k` | How many document chunks to retrieve per RAG query. 5 is a good default. |
| `similarity_threshold` | Minimum relevance score (0–1) for a chunk to be included. 0.7 filters low-relevance results. |
| `api_key` | Optional API key for LAKO's REST gateway. Leave empty to disable auth. |

---

## API Endpoints — What Each One Does

All endpoints are prefixed with `/api`. The FastAPI Swagger UI at `http://localhost:8000/docs` lets you test them interactively.

| Method | Endpoint | Status | What It Does |
|---|---|---|---|
| GET | `/` | LIVE | Health check. Returns `{"status":"ok"}`. |
| GET | `/health` | LIVE | Returns `{"status":"healthy"}`. |
| POST | `/api/chat` | STUB | Send a prompt directly to the primary LLM. No document search. Returns the LLM's answer. |
| POST | `/api/rag/query` | STUB | Send a question. LAKO searches documents, injects results, returns answer + sources. |
| POST | `/api/ingest/docs` | STUB | Upload one or more files. Returns a job_id. Then poll /api/ingest/status with that job_id. |
| GET | `/api/ingest/status` | STUB | Poll ingestion progress. Pass `?job_id=...`. Returns progress 0–100. |
| POST | `/api/ingest/confluence` | STUB | Pass a Confluence page URL. LAKO fetches and ingests it. |
| GET | `/api/models` | STUB | Returns all installed Ollama models + which model is assigned to each role. |
| GET | `/api/vector/status` | STUB | Returns ChromaDB health, total chunks stored, and storage path. |

**LIVE** = working now. **STUB** = returns placeholder data, real logic added in a later session.

---

## Service Ports

| Service | URL | Notes |
|---|---|---|
| React Frontend | http://localhost:5173 | Vite dev server |
| FastAPI Backend | http://localhost:8000 | uvicorn |
| FastAPI Swagger | http://localhost:8000/docs | Interactive API docs — test all endpoints here |
| Ollama | http://localhost:11434 | Model server — must be running for AI to work |

---

## How to Start LAKO

### Prerequisites (one-time manual setup)

```bash
# 1. Install Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Install Python, Node.js, Git
brew install python@3.11 node@20 git

# 3. Install Ollama — download from https://ollama.com/download then:
ollama pull qwen3.5:9b         # Primary LLM — ~9 GB download
ollama pull llava:13b          # Vision model — ~10 GB download
ollama pull nomic-embed-text   # Embeddings — ~0.5 GB download
```

### Start backend

```bash
cd ~/lako/backend
source .venv/bin/activate
uvicorn main:app --reload --port 8000
```

Or use the convenience script:
```bash
./start_backend.sh
```

### Start frontend

```bash
cd ~/lako/frontend
npm run dev
```

Or use the convenience script:
```bash
./start_frontend.sh
```

### Open the app

```
http://localhost:5173
```

---

## Build Session Log

| Session | Tool | Status | What Was Built |
|---|---|---|---|
| 1 | OpenClaw | COMPLETE | Full project folder created. All Python stub files, all React stub files, all config files, storage directories, documentation framework, git-ready structure. |
| 2 | Claude Code | COMPLETE | Backend made fully runnable — Python venv created (`backend/.venv`), all dependencies installed via pip, uvicorn starts and serves at :8000, `GET /` returns `{"status":"ok"}`. Frontend made fully runnable — npm install, Vite dev server confirmed at :5173. CORS verified. Package.json cleaned up (removed incompatible `@tailwindcss/vite` v4 package and invalid `@shadcn/ui` package). All 6 sidebar routes render their page stubs without errors. |
| 3 | Claude Code | PENDING | Ollama integration, live model detection, model role assignment, Settings page save/load |
| 4 | Claude Code | PENDING | ChromaDB setup, embedder service, chunker service, config.json wiring |
| 5 | Claude Code | PENDING | PDF + TXT ingestion pipeline, file upload endpoint, Tesseract OCR fallback |
| 6 | Claude Code | PENDING | Excel, Word, PowerPoint parsers plugged into ingestion pipeline |
| 7 | Claude Code | PENDING | Vision pipeline: image extraction from PDFs + llava:13b description service |
| 8 | Claude Code | PENDING | RAG engine, Chat interface with streaming, source citations display |
| 9 | Claude Code | PENDING | Confluence single page ingestion: URL parsing, REST client, auth |
| 10 | Claude Code | PENDING | REST API gateway, API key auth, all external endpoints tested |
| 11 | Claude Code | PENDING | Dashboard health pings, polling progress UI, ingestion status screen |
| 12 | Claude Code | PENDING | i18n EN + NL, language toggle, Dutch translation files |
| 13 | OpenClaw | PENDING | Full integration testing, auto bug fixing, cross-module wiring |
| 14 | OpenClaw | PENDING | Edge case resolution, final cleanup, README update |

---

## Session 2 — Technical Decisions Made

### Python virtual environment in backend/.venv
Python virtual environments isolate a project's packages from the rest of the system. This means LAKO's dependencies (FastAPI, ChromaDB, PyMuPDF, etc.) are installed only inside `backend/.venv` and cannot conflict with other Python projects on the same machine. The venv is created once and reused every time the backend starts.

### Removed @tailwindcss/vite from package.json
The project uses **Tailwind CSS v3**, which integrates with Vite via PostCSS (the `postcss.config.js` file). The package `@tailwindcss/vite` is a Tailwind CSS **v4** plugin — a completely different integration path that is incompatible with v3. Leaving it in `package.json` would cause `npm install` to pull in a conflicting package. It was removed. The Vite config does not reference it, and Tailwind works correctly through PostCSS.

### Removed @shadcn/ui from package.json
`@shadcn/ui` is not a valid npm package name. shadcn/ui is a component collection where each component is added individually to the project's source code — it does not ship as a single installable package. No pages reference shadcn components, so this was removed cleanly.

### Added "type": "module" to package.json
Node.js was printing a warning that `postcss.config.js` was being parsed as CommonJS when it contains ES module syntax (`export default`). Adding `"type": "module"` tells Node.js to treat all `.js` files in the frontend as ES modules by default, eliminating the warning and aligning with how Vite expects the project to be configured.

### CORS configuration
CORS (Cross-Origin Resource Sharing) is a browser security rule that blocks JavaScript on one domain from calling an API on a different domain. Since the React frontend runs at port 5173 and the FastAPI backend runs at port 8000, they are technically different origins. The backend's `main.py` includes `CORSMiddleware` that explicitly allows requests from `http://localhost:5173` — verified to return the correct `Access-Control-Allow-Origin` header.

---

## What "STUB" Means

Throughout the codebase, functions and API endpoints are marked `# STUB` or `[STUB]`. This means:

- The function exists and is wired up (FastAPI registers it, React calls it)
- It returns fake/placeholder data so the UI does not break
- The real logic will be added in the session noted in the comment

**Example:** `GET /api/models` currently returns a hardcoded list of three models. In Session 3, this will be replaced with a live call to Ollama that returns whatever models are actually installed on the machine.

This stub-first approach means the entire UI is navigable and testable at all times, even before any real AI logic is built.

---

## Explicitly Out of V1 Scope

These features are intentionally deferred to keep V1 achievable:

| Feature | Reason |
|---|---|
| Confluence recursive child crawling | Single page is sufficient for V1 |
| Confluence page attachments | Complexity of attachment types |
| SharePoint integration | OAuth2 complexity |
| Excel chart image extraction | Data is extracted; visual chart skipped |
| Qwen3-VL vision model | No Ollama local support yet |
| German + French UI | EN + NL sufficient for Rabobank V1 |
| WebSockets progress | Polling (every 3s) is sufficient |
| Chat history | Stateless by design |
| User login / roles / auth | Internal network assumed |
| Desktop installer | Browser-based is more enterprise-appropriate |

---

## V2 Roadmap

| Feature | Complexity |
|---|---|
| Qwen3-VL vision (when Ollama supports it) | Low |
| PaddleOCR (better than Tesseract) | Low |
| German + French UI | Low |
| SSE instead of polling | Low |
| Confluence recursive crawl | Medium |
| SharePoint integration | Medium |
| User login / roles | Medium |
| Upgrade to Qdrant or Milvus (larger scale) | Medium |
| Desktop installer | Very High |

---

## NotebookLM Setup

LAKO's documentation is designed to be uploaded to NotebookLM to create a private AI knowledge base about the codebase itself.

**Initial setup:**
1. Go to notebooklm.google.com
2. Create a notebook called: **LAKO Knowledge Base**
3. Upload this README.md as the first source
4. Upload `LAKO_V1_Reference_Updated.pdf` as the second source

**After each session:**
- Upload the 3 new session documents from `docs/session_XX/`
- Replace `docs/Master_Changelog.md` with the updated version

**What this gives you:** The ability to ask NotebookLM questions like *"Which file handles PDF parsing?"* or *"What does the chunker do?"* and get accurate answers with citations from your own documentation.

---

*Prepared for vibe coding — Claude Code + OpenClaw*
*Sessions 1–2 complete — 2026-03-28*
