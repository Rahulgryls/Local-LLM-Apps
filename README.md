# LAKO — Local AI Knowledge Orchestrator

**Version:** V1 — Initial Release
**Build:** 14 sessions / 4–5 weeks
**Target:** Internal bank AI knowledge platform

> Everything runs locally. No cloud calls. No external API keys. No data leaves the bank's infrastructure — satisfying GDPR, Dutch banking secrecy law, and DNB regulatory requirements.

---

## What LAKO Does

- Ingests PDFs, Word, Excel, PowerPoint, and plain text files
- Ingests single Confluence pages by URL
- Processes embedded images and diagrams using a local vision model
- Chunks and embeds all content into a local vector database (ChromaDB)
- Answers questions using Retrieval-Augmented Generation (RAG)
- Exposes a REST API for external applications to query the LLM
- Provides a browser-based UI accessible from any internal machine

---

## Technology Stack

| Layer          | Technology              |
|----------------|-------------------------|
| Backend        | Python FastAPI (async)  |
| Frontend       | React + Vite            |
| Styling        | TailwindCSS + shadcn/ui |
| State Mgmt     | Zustand                 |
| LLM Runtime    | Ollama                  |
| Primary LLM    | qwen3.5:9b              |
| Vision Model   | llava:13b               |
| Embeddings     | nomic-embed-text        |
| Vector DB      | ChromaDB (local)        |
| PDF Parsing    | PyMuPDF + Tesseract OCR |
| Excel Parsing  | openpyxl + pandas       |
| Word Parsing   | python-docx             |
| PPT Parsing    | python-pptx             |
| i18n           | react-i18next (EN + NL) |

---

## Service Ports

| Service          | URL                          |
|------------------|------------------------------|
| React Frontend   | http://localhost:5173        |
| FastAPI Backend  | http://localhost:8000        |
| FastAPI Swagger  | http://localhost:8000/docs   |
| Ollama           | http://localhost:11434       |

---

## Quick Start

### Prerequisites (one-time — manual setup)
```bash
# 1. Install Homebrew
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Install tools
brew install python@3.11 node@20 git

# 3. Install and start Ollama (download from https://ollama.com/download)

# 4. Pull required models
ollama pull qwen3.5:9b
ollama pull llava:13b
ollama pull nomic-embed-text
```

### Start LAKO
```bash
# Terminal 1 — Backend
./start_backend.sh

# Terminal 2 — Frontend
./start_frontend.sh

# Open browser
open http://localhost:5173
```

### Verify Session 1
```bash
./verify_session1.sh
```

---

## Project Structure

```
lako/
├── backend/
│   ├── main.py              # FastAPI entry point
│   ├── config.py            # Config loader
│   ├── requirements.txt     # Python dependencies
│   ├── routers/             # API route handlers
│   │   ├── chat.py          # POST /api/chat
│   │   ├── rag.py           # POST /api/rag/query
│   │   ├── ingest.py        # POST /api/ingest/docs
│   │   ├── confluence.py    # POST /api/ingest/confluence
│   │   ├── models.py        # GET /api/models
│   │   └── vector.py        # GET /api/vector/status
│   └── services/
│       ├── ollama_client.py # Ollama API wrapper
│       ├── chroma_client.py # ChromaDB wrapper
│       ├── embedder.py      # Text embedding service
│       ├── chunker.py       # Document chunking
│       ├── rag_engine.py    # Full RAG pipeline
│       ├── vision_service.py# Image description (llava)
│       ├── confluence_client.py
│       └── parsers/
│           ├── pdf_parser.py
│           ├── txt_parser.py
│           ├── excel_parser.py
│           ├── word_parser.py
│           └── ppt_parser.py
├── frontend/
│   ├── src/
│   │   ├── pages/           # Dashboard, Chat, Ingestion, Settings
│   │   ├── components/      # Sidebar, Header, ProgressBar, Citations
│   │   ├── store/           # Zustand state
│   │   └── i18n/            # EN + NL translations
│   ├── package.json
│   └── vite.config.js
├── storage/
│   ├── chromadb/            # Vector database (persisted)
│   └── uploads/             # Uploaded documents
├── config/
│   └── config.json          # All model names and settings
├── docs/
│   ├── Master_Changelog.md  # Running session log
│   └── session_01/          # Session 1 documentation
├── start_backend.sh
├── start_frontend.sh
└── verify_session1.sh
```

---

## Configuration

Edit `config/config.json` to change models or settings:

```json
{
  "primary_model":   "qwen3.5:9b",
  "vision_model":    "llava:13b",
  "embedding_model": "nomic-embed-text",
  "top_k":           5,
  "similarity_threshold": 0.7
}
```

**Bank server upgrade:** change `primary_model` to `"qwen3.14b"` or `"qwen3.32b"` — restart backend. No code changes.

---

## Build Sessions

| Session | Tool        | What Gets Built |
|---------|-------------|-----------------|
| 1       | OpenClaw    | Environment setup, folder structure, dependency install |
| 2       | Claude Code | FastAPI skeleton, React UI shell, sidebar navigation |
| 3       | Claude Code | Ollama integration, model detection, Settings page |
| 4       | Claude Code | ChromaDB setup, embedder, chunker, config.json wiring |
| 5       | Claude Code | PDF + TXT ingestion pipeline, file upload endpoint |
| 6       | Claude Code | Excel, Word, PowerPoint parsers |
| 7       | Claude Code | Vision pipeline: image extraction + llava description |
| 8       | Claude Code | RAG engine, Chat interface with streaming |
| 9       | Claude Code | Confluence single page ingestion |
| 10      | Claude Code | REST API gateway, API key auth |
| 11      | Claude Code | Dashboard, polling progress UI |
| 12      | Claude Code | i18n EN + NL |
| 13      | OpenClaw    | Full integration testing, auto bug fixing |
| 14      | OpenClaw    | Edge case resolution, final cleanup |

---

*Prepared for vibe coding — Claude Code + OpenClaw*
*Session 1 complete — 2026-03-27*
