# LAKO — Local AI Knowledge Orchestrator

**Version:** V1
**Build:** 14 sessions / 4–5 weeks
**Target:** Internal bank AI knowledge platform (Rabobank)
**Developer:** Vibe coding — Claude Code + OpenClaw
**Last updated:** Session 13 complete — 2026-04-01

> **Core principle:** Everything runs locally. No cloud calls. No external API keys. No data leaves the bank's infrastructure — satisfying GDPR, Dutch banking secrecy law, and DNB regulatory requirements.

---

## What LAKO Does (Plain English)

LAKO is a private, internal search engine powered by AI. Instead of typing keywords into SharePoint and getting nothing useful, a bank employee types a natural language question — *"What is our policy on third-party vendor risk in cloud contracts?"* — and LAKO finds the answer by searching through all the bank's internal documents that have been loaded into it.

Everything runs on a server inside the bank. No question, no document, and no answer ever leaves the building.

**LAKO does five things:**
1. **Ingests documents** — you upload PDFs, Word files, Excel sheets, PowerPoint decks, and text files. LAKO reads them, breaks them into searchable chunks, and stores them locally.
2. **Ingests Confluence pages** — you paste a Confluence URL and LAKO fetches and stores that page's content.
3. **Understands images and diagrams** — for PDFs with flowcharts or process diagrams, and PowerPoint slides with image-only content, LAKO uses a local vision AI model to describe what the image shows, so diagrams become searchable text. Scanned PDFs with no selectable text are OCR'd by the same vision model for better Dutch-language accuracy.
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
| Primary LLM | qwen3.5:35b-a3b-coding-nvfp4 | The main language model for answering questions and vision tasks. Qwen3.5 is made by Alibaba, trained on 119 languages including Dutch, with a 256K token context window. Runs at ~112 tok/s on M5 Pro via Ollama 0.19 MLX. Handles text, code, and vision in a single model. |
| Vision Model | qwen3.5:35b-a3b-coding-nvfp4 | Same model as primary — used for image description, PPTX slide rendering, and scanned PDF OCR. Single model for all tasks eliminates cold-start model switching. |
| Embeddings | nomic-embed-text | Converts text into numerical vectors (lists of numbers). Two pieces of text that mean similar things will produce similar vectors. This is how ChromaDB can find relevant document chunks from a question — by comparing vector similarity. |
| Vector DB | ChromaDB | A local database that stores document chunks as vectors. When you ask a question, LAKO converts your question to a vector and ChromaDB finds the stored chunks with the closest vectors. No Docker required — runs as a Python library. |
| PDF Parsing | PyMuPDF (fitz) | Python library for reading PDFs. Extracts text page by page, and also extracts embedded images for vision processing. |
| OCR Primary | qwen3.5 vision | Scanned PDF pages (< 50 chars extracted) are rendered as PNG and sent to the vision model with a text-extraction prompt. Significantly better Dutch-language quality than Tesseract. Session 13. |
| OCR Fallback | Tesseract | Fallback if the vision model times out or errors. Still installed — `brew install tesseract`. |
| Excel Parsing | openpyxl + pandas | openpyxl reads .xlsx files. pandas converts spreadsheet data into structured text that can be chunked and embedded. |
| Word Parsing | python-docx | Reads .docx files — extracts paragraphs, headings, and table content. |
| PPT Parsing | python-pptx | Reads .pptx files — extracts slide text and speaker notes. |
| i18n | react-i18next | Internationalisation framework. All UI text is stored in translation files (en.json and nl.json). A toggle in the header switches the entire UI between English and Dutch. |
| Config | config.json | A single JSON file that stores all model names, paths, and settings. Nothing is hardcoded in the Python or JavaScript code. Changing a model is a one-line edit in this file. |

---

## Model Stack — Key Decisions

### Model stack (as of Session 13 — single-model consolidation)

| Factor | Old stack (Session 11) | New stack (Session 13) |
|---|---|---|
| Chat / RAG | qwen3.5:9b | qwen3.5:35b-a3b-coding-nvfp4 |
| Vision | llava:13b | qwen3.5:35b-a3b-coding-nvfp4 (same) |
| Embeddings | nomic-embed-text | nomic-embed-text (unchanged) |
| Speed | ~40 tok/s | ~112 tok/s (Ollama 0.19 MLX on M5 Pro) |
| Dutch quality | Good | Excellent — 119 languages, 256K context |

**Why one model for everything:** Running two large models (qwen3.5:9b + llava:13b) required memory swapping as Ollama unloads one to load the other. `qwen3.5:35b-a3b-coding-nvfp4` is natively multimodal — the same model answers questions, describes images, renders PPTX slides, and OCRs scanned Dutch bank documents. Ollama 0.19 with MLX backend enables full M5 Pro ANE utilisation at 112 tok/s.

**Vendor note:** Qwen is made by Alibaba (China). Since LAKO runs fully on-premises with zero external calls, no data reaches Alibaba. If Rabobank's vendor approval requires Meta (US) origin, `llama3.3:8b` is a drop-in alternative — one line in config.json.

### RAM usage on 48 GB MacBook

| Scenario | Models Active | RAM Used |
|---|---|---|
| Chat / RAG / vision / OCR | qwen3.5:35b + nomic | ~22 GB |
| Embeddings only | nomic-embed-text | ~0.5 GB |

Single-model stack eliminates cold-start swapping. Ollama auto-unloads after 5 minutes idle.

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
  ■ qwen3.5:35b-a3b-coding-nvfp4 — answers questions, describes images, OCRs scanned PDFs
  ■ nomic-embed-text              — converts text to vectors
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
│   │   │                             Direct LLM query. Takes a prompt, sends to Ollama.
│   │   │                             stream=true (default): StreamingResponse(text/plain),
│   │   │                             tokens yielded as they arrive from Ollama.
│   │   │                             stream=false: JSON ChatResponse with full answer.
│   │   │                             LIVE (Session 8).
│   │   │
│   │   ├── rag.py                  ← POST /api/rag/query
│   │   │                             RAG query. Takes a question, searches ChromaDB,
│   │   │                             injects relevant chunks, asks qwen3.5:9b, returns
│   │   │                             answer + source citations (filename, page, score).
│   │   │                             LIVE (Session 8).
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
│   │   │                             LIVE (Session 9). Supports mock=true for local dev.
│   │   │
│   │   ├── models.py               ← GET /api/models — live Ollama model list + role
│   │   │                             assignments + per-role health booleans.
│   │   │                             GET /api/config — returns full config.json.
│   │   │                             POST /api/config — saves any fields to config.json.
│   │   │                             LIVE — fully implemented in Session 3.
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
│       ├── ollama_client.py        ← Wrapper for Ollama API calls.
│       │                             list_models(): calls GET /api/tags, returns name/size/date.
│       │                             health_check(): pings Ollama root, returns bool.
│       │                             embed() + embed_batch(): LIVE (Session 4).
│       │                             describe_image(): LIVE (Session 7) — POST /api/generate
│       │                             with images field, vision_model from config, stream=false.
│       │                             chat(): LIVE (Session 8) — POST /api/generate stream=false,
│       │                             120s timeout, optional system prompt.
│       │                             stream_chat(): LIVE (Session 8) — async generator, yields
│       │                             tokens from Ollama streaming JSON line-by-line.
│       │                             Reads config fresh on every call — respects config changes
│       │                             without backend restart.
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
│       │                             search ChromaDB → threshold filter → _build_prompt()
│       │                             ([CONTEXT] chunks [QUESTION]) → call LLM → return
│       │                             {answer, sources, model, rag_used}.
│       │                             use_rag=false: calls LLM directly (no retrieval).
│       │                             No chunks above threshold → canned not-found message.
│       │                             LIVE (Session 8).
│       │
│       ├── vision_service.py       ← Sends images to vision model (config: vision_model) and
│       │                             gets back a text description. Called during PDF ingestion
│       │                             for embedded images, scanned-page OCR, and PPTX slides.
│       │                             LIVE (Session 7): describe_image_bytes() checks dims
│       │                             via Pillow (min 100×100), base64-encodes, calls ollama.
│       │                             Session 13: stale llava:13b references removed — model
│       │                             always read from config, never hardcoded.
│       │
│       ├── confluence_client.py    ← Fetches a Confluence page by URL using the Confluence
│       │                             REST API (v2 Cloud + v1 Server/DC fallback). Parses HTML
│       │                             into ~500-token chunks via BeautifulSoup. Mock mode.
│       │                             LIVE (Session 9).
│       │
│       └── parsers/                ← One file per document format.
│           ├── pdf_parser.py       ← PyMuPDF text extraction + image extraction per page.
│           │                         Session 5: Fully implemented.
│           │                         Session 13: scanned pages flagged with ocr_mode="vision"
│           │                         and rendered to PNG bytes (_vision_ocr_page). Vision OCR
│           │                         runs async in ingest.py. _ocr_page_tesseract(png_bytes)
│           │                         remains as fallback. ParsedPage gains ocr_mode +
│           │                         ocr_png_bytes fields.
│           ├── txt_parser.py       ← Plain text reader. Session 5: Fully implemented.
│           ├── excel_parser.py     ← openpyxl + pandas. Each sheet → ParsedPage.
│           │                         Pipe-separated table stored in page.tables so the
│           │                         chunker keeps each sheet intact as one chunk.
│           │                         Session 6: Fully implemented.
│           ├── word_parser.py      ← python-docx. Headings (# ## ###) + paragraphs →
│           │                         page.text. Tables → page.tables (pipe-separated).
│           │                         Session 6: Fully implemented.
│           └── ppt_parser.py       ← python-pptx. Each slide → ParsedPage.
│                                     Title (# prefix) + text boxes + speaker notes.
│                                     Session 6: Fully implemented.
│                                     Session 13: _render_slides_to_images() — LibreOffice
│                                     headless primary, Pillow shape-composite fallback.
│                                     Image-only slides now produce chunks via vision pipeline.
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
│       │   │                         4 StatCards (chunks, documents, API keys, Ollama status).
│       │   │                         Knowledge base breakdown (PDF vs Confluence source bar).
│       │   │                         Models panel (primary/vision/embeddings + online status).
│       │   │                         Recent Activity table (last 10 ingestion events).
│       │   │                         Auto-refreshes every 30s. "Updated Xs ago" counter.
│       │   │                         LIVE (Session 11).
│       │   │
│       │   ├── Chat.jsx            ← /chat route.
│       │   │                         Main question-answering interface.
│       │   │                         RAG ON → POST /api/rag/query, full JSON response,
│       │   │                         SourceCitations component shows filename/page/score.
│       │   │                         RAG OFF → POST /api/chat stream=true, ReadableStream
│       │   │                         + TextDecoder, tokens rendered as they arrive.
│       │   │                         Model dropdown from Zustand availableModels.
│       │   │                         Clear button. Enter sends, Shift+Enter newline.
│       │   │                         LIVE (Session 8).
│       │   │
│       │   ├── DocumentIngestion.jsx ← /ingest/docs route.
│       │   │                           File upload UI with drag-and-drop zone.
│       │   │                           Session 5: PDF + TXT fully wired. DOCX/XLSX/PPTX in Session 6.
│       │   │                           Session 7: Eye icon shown next to progress label when
│       │   │                           status message contains "vision" or "image".
│       │   │                           POSTs to /api/ingest/docs, polls /api/ingest/status every 3s.
│       │   │                           Shows live progress bar and chunk count on completion.
│       │   │
│       │   ├── ConfluenceIngestion.jsx ← /ingest/confluence route.
│       │   │                             URL input, optional API token, mock toggle.
│       │   │                             Async polling: POST → job_id → poll every 2s.
│       │   │                             Live progress bar + status message during ingestion.
│       │   │                             Success (page title + chunk count), error + retry.
│       │   │                             LIVE (Session 9 / updated Session 11).
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
│       ├── hooks/                  ← Custom React hooks for data fetching.
│       │   └── useDashboard.js     ← Polls /api/dashboard/stats every 30s.
│       │                             Fetches /api/dashboard/recent-activity on load.
│       │                             Returns: { stats, activity, isLoading, error, refresh, lastUpdated }
│       │
│       ├── components/             ← Reusable UI pieces used across multiple pages.
│       │   │
│       │   ├── StatCard.jsx        ← Reusable stat card with large value, icon, subtitle.
│       │   │                         Props: title, value, subtitle, icon, trend, color.
│       │   │                         Color variants: blue, green, amber, red.
│       │   │                         Used on Dashboard for the 4 top-row KPI cards.
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
│       │                             LIVE (Session 8) — receives sources[] from Chat.jsx.
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
│   ├── uploads/                    ← Uploaded files are saved here before ingestion.
│   │                                 After ingestion, files remain here as an archive.
│   ├── api_keys.json               ← API key hashes (gitignored). Generated by api_key_manager.py.
│   │                                 Contains key_hash (SHA-256), prefix, name, permissions,
│   │                                 is_active, created_at, last_used. Never contains plain keys.
│   └── activity_log.json           ← Ingestion event log. Auto-created on first ingestion.
│                                     Contains last 50 entries: type, title, chunks_indexed,
│                                     status (success/failed), error, timestamp. Used by Dashboard.
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
  "primary_model":        "qwen3.5:35b-a3b-coding-nvfp4",
  "vision_model":         "qwen3.5:35b-a3b-coding-nvfp4",
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
| GET | `/api/models` | LIVE | Returns all installed Ollama models + role assignments from config + per-role health booleans (`model_health`). |
| GET | `/api/config` | LIVE | Returns full contents of config.json. |
| POST | `/api/config` | LIVE | Accepts any config fields as JSON. Saves to config.json, reloads config cache, returns updated config. |
| POST | `/api/chat` | STUB | Send a prompt directly to the primary LLM. No document search. Returns the LLM's answer. |
| POST | `/api/rag/query` | STUB | Send a question. LAKO searches documents, injects results, returns answer + sources. |
| POST | `/api/ingest/docs` | LIVE | Upload PDF, TXT, XLSX, DOCX, or PPTX files. Saves to `/storage/uploads/`, runs full parse → chunk → embed → store pipeline in background. Returns `job_id`. |
| GET | `/api/ingest/status` | LIVE | Poll ingestion progress. Pass `?job_id=...`. Returns `status`, `progress` (0–100), `message`, and `chunk_count` when complete. |
| POST | `/api/ingest/confluence` | LIVE | Pass `url` + optional `api_token`. Returns `job_id` immediately. Runs ingestion in background. Add `mock: true` to test without a real Confluence instance. |
| GET | `/api/ingest/confluence/status` | LIVE | Poll Confluence job progress. Pass `?job_id=...`. Returns `status`, `progress` (0–100), `message`, `chunks_indexed`, `page_title`. |
| GET | `/api/vector/status` | LIVE | Returns ChromaDB health, collection name, total chunks, and storage path. |
| DELETE | `/api/vector/clear` | LIVE | Deletes all chunks from the collection. Returns count of deleted chunks. Collection is recreated empty immediately. |
| GET | `/api/dashboard/stats` | LIVE | Real-time system stats: ChromaDB chunk/document counts (PDF vs Confluence breakdown), Ollama status, API key counts, ingestion summary, uptime. |
| GET | `/api/dashboard/recent-activity` | LIVE | Last 10 ingestion events from `storage/activity_log.json`. Each entry: type, title, chunks_indexed, status, timestamp. |
| POST | `/api/admin/keys` | LIVE | Generate a new API key. Returns `key` (shown once), `id`, `prefix`. |
| GET | `/api/admin/keys` | LIVE | List all API keys (no hashes). |
| DELETE | `/api/admin/keys/{id}` | LIVE | Permanently delete a key. |
| PATCH | `/api/admin/keys/{id}/revoke` | LIVE | Deactivate a key (keeps record for audit). |
| POST | `/api/gateway/query` | LIVE | Authenticated RAG query. Requires `X-API-Key` header. |
| POST | `/api/gateway/ingest/confluence` | LIVE | Authenticated Confluence ingestion (synchronous). |
| POST | `/api/gateway/ingest/document` | LIVE | Authenticated document ingestion (synchronous). |
| GET | `/api/gateway/health` | LIVE | Gateway health check (no auth required). |

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
ollama pull qwen3.5:35b-a3b-coding-nvfp4   # Primary + vision model — ~22 GB
ollama pull nomic-embed-text               # Embeddings — ~0.5 GB download
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
| 3 | Claude Code | COMPLETE | Ollama integration fully wired. `ollama_client.list_models()` calls live `GET /api/tags`. `GET /api/models` returns all installed models + role assignments from config + per-role health booleans. `GET /api/config` returns full config.json. `POST /api/config` saves any fields to config.json and reloads. Settings page loads live model dropdowns and saves via backend. Dashboard model cards show green/red based on whether each configured model is installed in Ollama. Handles `nomic-embed-text` vs `nomic-embed-text:latest` name matching. |
| 4 | Claude Code | COMPLETE | ChromaDB fully wired. `chroma_client`: PersistentClient with cosine similarity, `add_chunks()`, `similarity_search()` (threshold filtering), `get_stats()`, `clear_collection()`. `embedder`: `embed_text()`, `embed_chunks()` (batch), `embed_query()`. `chunker`: sliding-window `chunk_text()` with sentence-boundary breaks, `chunk_table()`, `chunk_image_caption()`, `chunk_document()` routes all content types. `ollama_client.embed()` + `embed_batch()` via `/api/embed`. `GET /api/vector/status` and `DELETE /api/vector/clear` live. VectorDB page shows live stats + clear button with double-confirm. Fixed `chromadb_path` in config.json to actual dev path. |
| 5 | Claude Code | COMPLETE | PDF + TXT ingestion pipeline fully wired. `pdf_parser`: PyMuPDF text + image extraction per page, Tesseract OCR fallback for scanned pages, clear error if Tesseract binary missing. `txt_parser`: UTF-8/latin-1 read, wraps as single ParsedPage. `ingest.py`: `POST /api/ingest/docs` saves files to `/storage/uploads/`, runs parse→chunk→embed→store pipeline in background via FastAPI BackgroundTasks, real progress tracking per file. `GET /api/ingest/status` returns live progress, message, and chunk count. `DocumentIngestion.jsx`: real FormData POST, 3s polling loop, live progress bar, chunk count on success, error display. Tesseract installed via `brew install tesseract`. |
| 6 | Claude Code | COMPLETE | Excel, Word, PowerPoint parsers fully implemented. `excel_parser`: each sheet → ParsedPage with pipe-separated table content in `page.tables`. `word_parser`: paragraphs with `# ## ###` heading markers → `page.text`, tables → `page.tables`. `ppt_parser`: each slide → ParsedPage with title (# prefix) + text boxes + speaker notes; title deduplication via `shape_id` comparison. `ingest.py`: parser routing for all 5 formats, extracted dict now populates both `text_blocks` and `tables` from parsed pages so Excel/Word tables flow through `chunk_table()`. `DocumentIngestion.jsx`: updated `accept` attribute to include XLSX, DOCX, PPTX. |
| 7 | Claude Code | COMPLETE | Vision pipeline: `describe_image()` in ollama_client (POST /api/generate, images field, stream=false). `vision_service`: all three methods wired — bytes/file/base64, Pillow size check (min 100×100). `ingest.py`: PDF pipeline extended — per-page image extraction → size filter → 60s timeout vision call → chunk_image_caption → embed → ChromaDB. Errors/timeouts logged, never fail ingestion. `DocumentIngestion.jsx`: Eye icon on progress label during vision messages. |
| 8 | Claude Code | COMPLETE | RAG engine fully wired: embed → ChromaDB similarity search → threshold filter → `_build_prompt()` ([CONTEXT] + [QUESTION]) → `chat()` → `{answer, sources, model, rag_used}`. `ollama_client.chat()` (stream=false, 120s) and `stream_chat()` (async generator, line-by-line Ollama JSON). `/api/chat`: streaming `StreamingResponse` or JSON. `/api/rag/query`: full RAG pipeline with typed `SourceChunk` response. `Chat.jsx`: RAG toggle, streaming via `ReadableStream`+`TextDecoder`, `SourceCitations` wired, model dropdown from Zustand, Clear button, Enter/Shift+Enter. |
| 9 | Claude Code | COMPLETE | Confluence single page ingestion: URL parsing, REST client, HTML chunking, mock mode, SourceCitations globe icon |
| 10 | Claude Code | COMPLETE | REST API gateway, API key auth: api_key_manager.py, gateway.py, admin.py, Settings.jsx key table + generate modal |
| 11 | Claude Code | COMPLETE | Dashboard + async ingestion progress: activity_log.py, dashboard.py (stats + recent-activity), StatCard.jsx, useDashboard.js, Dashboard.jsx rewrite, ConfluenceIngestion async polling |
| 12 | Claude Code | COMPLETE | i18n EN + NL: react-i18next, en.json + nl.json translation files, LanguageSwitcher.jsx EN/NL pill toggle, all pages + components use useTranslation hook, language persists in localStorage |
| 13 | Claude Code | COMPLETE | Vision upgrade — single model pipeline: vision OCR for scanned PDFs (vision model primary, Tesseract fallback), PPTX slide vision pipeline (image-only slides now produce chunks), stale llava references removed, config.py defaults updated to qwen3.5:35b-a3b-coding-nvfp4 |
| 14 | OpenClaw | PENDING | Edge case resolution, final cleanup |

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

## Session 4 — Technical Decisions Made

### Cosine similarity vs L2 distance in ChromaDB
ChromaDB supports multiple distance metrics. LAKO uses cosine similarity because it measures the *angle* between two vectors — it focuses on meaning, not magnitude. The `similarity_threshold` in config.json (default 0.7) is a cosine similarity value (1 = identical, 0 = unrelated). ChromaDB internally stores cosine *distance* = `1 - similarity`, so the code converts: `similarity = 1 - distance` before applying the threshold filter.

### Ollama /api/embed vs /api/embeddings
Ollama has two embedding endpoints. The older `/api/embeddings` (singular) accepts one text string at a time. The newer `/api/embed` (plural) accepts a single string OR a list of strings, making batch embedding possible in one HTTP call. LAKO uses `/api/embed` with `embed_batch()` so that embedding many chunks during document ingestion is efficient — one round-trip to Ollama instead of one per chunk.

### Sentence-boundary chunking
`chunk_text()` tries to break at natural sentence or paragraph boundaries (in order of preference: `\n\n`, `.\n`, `. `, `? `, `! `, `\n`) rather than cutting at exactly 450 characters. This keeps sentence meaning intact and prevents a chunk from ending mid-sentence, which would confuse the LLM during RAG.

### Tables and images are never split
`chunk_table()` always returns a single chunk regardless of table size. Splitting a table at an arbitrary row would break the relationship between column headers and values. The LLM needs the full table to answer questions like "what is the value in column B for row 3?". Similarly, image captions are always single chunks.

### ChromaDB path: config.json vs bank server
The reference document specifies `/lako/storage/chromadb` as the ChromaDB path (the bank server deployment path). On the dev Mac, the project lives at `/Users/rahul/lako/`, so config.json was updated to `/Users/rahul/lako/storage/chromadb`. On the bank server, change this back to `/lako/storage/chromadb` — it is a one-line change in config.json.

### Self-healing collection reference
The `ChromaClient` singleton caches the collection object. If the collection is deleted externally (e.g., by another process or a test script), the cached reference becomes stale and throws errors. `get_collection()` now validates the reference on every call by checking `count()` — if that throws, it resets and recreates. This costs one extra ChromaDB call per operation but prevents silent failures.

---

## Session 3 — Technical Decisions Made

### OllamaClient reads config on every call (not just at startup)
The original stub stored `self.base_url` once in `__init__`. This meant if the user changed `ollama_url` in Settings and saved it, the running backend would still use the old URL until restarted. The fix: `OllamaClient` now has a `_base_url()` method that calls `get_config()` on every request. Since `get_config()` is cached, this is cheap — and when `POST /api/config` triggers `reload_config()`, the cache clears, and the very next call picks up the new URL automatically.

### Model name matching: "nomic-embed-text" vs "nomic-embed-text:latest"
Ollama stores models with explicit tags. When you pull `nomic-embed-text` without specifying a tag, Ollama saves it as `nomic-embed-text:latest`. But `config.json` stores it as `nomic-embed-text` (no tag). A simple string equality check would show it as "not installed" (red) even though it is installed. The fix: `_model_installed()` in `models.py` checks if the config name matches any installed model either exactly, or as a prefix followed by `:`. This handles all tag variants.

### GET /api/config added alongside POST /api/config
The Settings page needs to load current values on page open, not just save them. `GET /api/config` returns the full `config.json` contents. This means the Settings page always shows what's actually saved on disk, not stale frontend defaults.

### Settings page: model dropdowns instead of text inputs
The three model fields (Primary LLM, Vision Model, Embedding Model) are now `<select>` dropdowns populated from `GET /api/models`. This ensures the user can only select models that are actually installed in Ollama — preventing typos or invalid model names. If Ollama is offline when Settings loads, the current config values are shown as fallback options marked "(not installed)".

### config.json write safety
`save_config()` in `config.py` reads the current config first, merges the new values on top of it, then writes the full merged result back to disk. This means a `POST /api/config` with only `{"top_k": 7}` will not erase all other fields — it will only update `top_k` and leave everything else unchanged.

---

## Session 7 — Technical Decisions Made

### Vision pipeline placement: between parse and chunk (not after)
The vision image processing runs *before* `chunk_document()` is called. This means image captions flow into `extracted["images"]` and are handled uniformly by the existing `chunk_document()` → embed → store pipeline. The alternative — processing images after text chunks and storing them separately — would have required duplicating the embed/store code. Keeping the vision step as "populate `extracted["images"]`" meant zero changes to the chunker, embedder, or ChromaDB storage code.

### 100×100 px minimum image size
PDFs often contain tiny decorative images: logos, line separators, bullet icons, page borders. These are visually meaningless but would burn vision model time and produce useless captions like "this is a small black square." The 100×100 px threshold filters out these artefacts. The check runs via Pillow (`Image.open(io.BytesIO(bytes)).size`) before any Ollama call, so it is fast and adds no network cost.

### 60-second timeout per image with non-fatal error handling
llava:13b is a 13-billion-parameter model — it takes 20–45 seconds per image on a MacBook. If Ollama is under load or the image is unusually complex, it can exceed this. The `asyncio.wait_for(timeout=60.0)` wraps each call. On timeout or any other exception, a `logging.warning()` is emitted and the loop continues to the next image. This ensures a PDF with 20 images does not fail because image 3 timed out — the other 19 images and all text are still ingested successfully.

### vision_model always from config — never hardcoded
`ollama_client._vision_model()` reads `config["vision_model"]` on every call. This means switching from llava:13b to a future llava:34b or BakLLaVA model is a one-line change in config.json — no code change required. The Settings page already exposes this field.

### Eye icon: regex match on live status message
The Eye icon appears when `/vision|image/i.test(statusMessage)` is true — it tests the live message string (not a separate boolean state). This is reliable because all vision-related progress messages in ingest.py are prefixed with `[vision]` or contain the word "image." The regex is case-insensitive as a defensive measure. No additional backend response fields were needed.

---

## Session 11 — Technical Decisions Made

### activity_log.json: disk persistence for dashboard history
Job status in ingest.py is stored in `_jobs` (in-memory dict), which resets on backend restart. The dashboard needs to show ingestion history across restarts. Rather than a database, a simple JSON file appended on each job completion (success or failure) provides this. The file is capped at 50 entries to prevent unbounded growth. The `activity_log.py` singleton uses a read-modify-write pattern — no async locking needed since FastAPI background tasks run in the same process event loop.

### Async job pattern for Confluence ingestion
Confluence ingestion was previously synchronous — the HTTP response waited for the entire pipeline (fetch → parse → embed → store). For large pages with many sections this could take 10–30 seconds. Session 11 converts it to the same pattern used for PDF ingestion since Session 5: POST returns `job_id` in under 1 second, background task updates `_confluence_jobs[job_id]`, frontend polls `/api/ingest/confluence/status` every 2 seconds. This eliminates browser timeout risk and gives users live progress feedback.

### Dashboard source breakdown: scan metadata, not a counter
The PDF vs Confluence chunk count is computed by scanning all document metadata in ChromaDB and checking the `source` field. Older PDF chunks don't have a `source` field — they default to `"pdf"`. This is a deliberate backwards-compatible convention: anything without an explicit `source` is treated as a PDF document. No migration of existing data was required.

### useDashboard polling at 30 seconds, not 3 seconds
The ingestion polling hooks poll every 2–3 seconds because job state changes rapidly during processing. Dashboard stats are aggregate metrics that change only when ingestion completes — polling every 30 seconds is sufficient and avoids unnecessary backend calls. A manual "Refresh" button is provided for on-demand updates.

### "Updated Xs ago" counter: setInterval in React, not from backend
The "last updated X seconds ago" counter increments every second using `setInterval` in React, counting from the last time `fetchAll()` completed. This avoids adding a timestamp field to every backend response. The counter resets to 0 on each successful refresh.

### StatCard color tied to semantic state, not hardcoded
The Ollama StatCard uses `color="green"` when status is healthy and `color="red"` when unreachable. All other cards have fixed colors (blue, green, amber). This is the only dynamic color assignment — it uses the same `color` prop mechanism as all other cards, requiring no conditional CSS classes in the Dashboard component.

---

---

## Session 13 — Technical Decisions Made

### Vision model as primary OCR for scanned PDFs
Tesseract was the original OCR fallback but has poor quality on Dutch bank documents: it struggles with mixed Dutch/English text, formatted policy tables, and scanned headers. Session 13 inverts the priority: `_vision_ocr_page(page)` in `pdf_parser.py` renders the page as PNG (2x zoom via PyMuPDF pixmap) and returns the bytes without calling Tesseract at all. The async `ingest.py` pipeline calls `vision_service.describe_image_bytes()` with a specific extraction prompt ("Extract all text... preserving structure, tables, headings"). If the vision call times out or errors, `_ocr_page_tesseract(png_bytes)` is called as the fallback. Tesseract remains installed and functional — it is just no longer the primary path.

### ParsedPage extended for async two-phase OCR
`pdf_parser.parse()` is a synchronous function (no event loop), but the vision call is async. Rather than making the parser async (which would require changes throughout the stack), `ParsedPage` gains two new fields: `ocr_mode: str` (set to `"vision"` for scanned pages) and `ocr_png_bytes: Optional[bytes]` (the rendered PNG). The parser returns immediately with `page.text = ""` for scanned pages. `ingest.py`, which already runs in an async background task, then fills in the text by calling `vision_service.describe_image_bytes()` in a loop before building `text_blocks`. This decouples the sync parser from the async I/O without any architectural changes to the pipeline.

### PPTX vision pipeline: LibreOffice primary, Pillow fallback
python-pptx cannot render slides — it only reads XML. LibreOffice headless (`soffice --headless --convert-to png --outdir <tmpdir> <file>`) converts the entire PPTX to per-slide PNGs in under 2 seconds on M5 Pro. The output files are collected from the temp directory by globbing `*.png` (sorted by name for slide order), read to bytes, and returned. LibreOffice is at `/opt/homebrew/bin/soffice` on the dev Mac.

The Pillow fallback extracts embedded picture shapes from each slide using python-pptx's `shape.shape_type == 13` check, composes them onto a white canvas scaled to the presentation's EMU dimensions at 96 DPI, and saves as PNG. This handles image-only slides even without LibreOffice. Text-only slides produce a blank canvas (their text is already captured by `parse()` into `text_blocks`).

### Vision calls for PPTX supplement, not replace, text
`image_captions` from the PPTX vision pipeline flows into `extracted["images"]` alongside existing PDF image captions. The chunker handles these identically to all other image captions. This means a slide with both text and an image gets two chunks: one text chunk (from `parse()`) and one vision chunk (from `_render_slides_to_images()`). Image-only slides that previously produced 0 chunks now produce ≥1 chunk from the vision description.

### Log prefixes for observability
All new log lines use prefixes: `[vision-ocr]` for scanned PDF OCR and `[pptx-vision]` for PPTX slide rendering. These make it easy to `grep` backend output during testing and to filter log noise during normal text-PDF ingestion.

---

## What "STUB" Means

## Session 10 — Technical Decisions Made

### SHA-256 hash comparison, never plain storage
`api_key_manager.py` hashes every incoming key with `hashlib.sha256(key.encode()).hexdigest()` before any comparison. The plain key is held in memory only long enough to return it to the caller at creation time. The stored `api_keys.json` file contains only hashes — even if the file is leaked, no key can be recovered from it.

### Prefix for key identification
The first 9 characters of the key (`lako_` + 4 random chars) are stored as a plain `prefix` field. This lets the Settings UI show admins which key is which ("lako_-D9k…") without storing or transmitting the full key value. The prefix alone cannot be used to reconstruct or brute-force the key.

### FastAPI Depends() for permission checking
Each gateway endpoint uses a separate dependency function (`_require_query_permission`, `_require_ingest_permission`, `_require_key`) as its `Depends()` argument. This means the auth check, hash validation, `last_used` update, and permission check all happen before any endpoint logic runs — and are fully tested in isolation.

### Admin endpoints: no auth by design (V1)
`/api/admin/keys` endpoints intentionally have no authentication in V1. In a bank deployment, these are protected at the network layer (only the admin VLAN or localhost can reach port 8000's `/api/admin/*` routes). Adding auth to admin endpoints creates a chicken-and-egg problem: you need a key to create a key. The production mitigation is network-level firewall, not application-level auth.

### Gateway ingest/document is synchronous
Unlike the UI-based `POST /api/ingest/docs` (which uses background tasks and job polling), `POST /api/gateway/ingest/document` runs synchronously and returns when complete. This makes it simpler for API callers (one request, one response) but means the HTTP connection stays open during processing. Suitable for small documents via the API; large batches should use the UI pipeline.

---

## Session 9 — Technical Decisions Made

### Confluence Cloud v2 → v1 API fallback
`confluence_client.fetch_page()` first tries the Confluence Cloud v2 REST API (`/wiki/api/v2/pages/{id}?body-format=storage`). If that returns 404 (Server/DC installations don't have v2), it automatically retries with the v1 API (`/wiki/rest/api/content/{id}?expand=body.storage`). This makes the same client work against both Atlassian Cloud and self-hosted Confluence without any configuration.

### HTML chunking: heading prefix strategy
The HTML parser maintains a `current_heading` variable that tracks the most recent heading element. Every non-heading chunk (paragraph, list, table) is prefixed with the heading text before being stored. When the chunk is retrieved in isolation during RAG search, it still has enough context to be understood — a paragraph about "Credit limits" becomes "Credit Risk Policy\nCredit limits above EUR 500K require..." rather than a decontextualised fragment.

### Extra metadata fields in ChromaDB
`chroma_client.add_chunks()` previously only stored 4 hardcoded fields: `filename`, `page`, `chunk_type`, `timestamp`. Session 9 changes it to first spread all provided metadata fields, then override with the 4 core fields to ensure correct types. This lets Confluence chunks store `source`, `url`, `title`, `author`, `updated` alongside the standard fields — no schema migration needed, existing PDF chunks are unaffected.

### Source field propagation to frontend
`rag_engine.py` now includes `source` and `url` fields in every source citation dict. `SourceCitations.jsx` uses these to: (1) show a globe icon instead of a document icon for Confluence sources, (2) render the filename as a clickable external link when `url` is present. PDF sources are unchanged — `url` is `""` and the document icon is shown.

### Mock mode for local dev
`POST /api/ingest/confluence` accepts `mock: true` in the request body. When set, it skips the HTTP call entirely and returns a realistic set of 6 chunks representing a Rabobank risk management policy page. This lets the full frontend flow be tested (progress, success state, chunk count, RAG retrieval) without needing a real Confluence instance.

---

## Session 8 — Technical Decisions Made

### stream_chat() as an async generator, not a coroutine
`stream_chat()` uses `yield` inside an `async with httpx.AsyncClient(...)` block. This makes it a Python async generator function — it keeps the HTTP connection open as long as tokens are being yielded. `chat.py` wraps it in a nested `async def generate()` and passes that to FastAPI's `StreamingResponse`. This is the correct httpx + FastAPI streaming pattern: the connection stays alive, tokens flow directly to the browser without buffering.

### Ollama streaming JSON format
Ollama's streaming API sends one JSON object per line, each with `{"response": "token", "done": false}`. The final message has `"done": true` and an empty `response`. `stream_chat()` parses each line with `json.loads()`, yields `chunk["response"]` if non-empty, and returns when `done` is true. `json.JSONDecodeError` is silently skipped — occasional blank lines or keepalive lines do not crash the stream.

### RAG prompt format: [CONTEXT] / [QUESTION] delimiters
The augmented prompt uses explicit section markers: `[CONTEXT]` followed by numbered source blocks (`[Source N: filename | Page P | Type: T]`), then `[QUESTION]`. This structured format helps qwen3.5 clearly distinguish document excerpts from the user's question, reducing the risk of the model confusing document text with the query. The SYSTEM_PROMPT reinforces that the model should only answer from the provided context.

### "Not found" response — no LLM call when no chunks match
When ChromaDB returns zero chunks above the similarity threshold, `rag_engine.query()` returns the canned string immediately without calling the LLM. Calling the LLM with no context would either hallucinate an answer or produce a confusing response. The canned message is deterministic and honest: *"This information was not found in the knowledge base."* This saves ~10–30 seconds of LLM wait time per unanswerable query.

### Model selector: empty string = config default
`Chat.jsx` initialises `selectedModel` as `""`. When `""`, the API call passes `model: undefined`, which FastAPI interprets as `null`, and the backend falls back to `config["primary_model"]`. This means the default option in the dropdown always shows the actual configured model name (from Zustand `primaryModel`), and switching back to it passes nothing (not a hardcoded name), so if the admin changes the primary model in Settings, the Chat page picks it up immediately.

### RAG non-streaming, direct chat streaming
RAG responses are non-streaming (`ollama_client.chat()`) because they require the full answer before source citations can be attached and returned as a JSON object. Direct chat (RAG OFF) uses `stream_chat()` for perceived performance — tokens appear immediately, the user sees the model "thinking" in real time. The tradeoff: RAG mode has a delay before anything appears; direct mode starts rendering tokens within ~1 second.

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
*Sessions 1–11 complete — 2026-03-29*
