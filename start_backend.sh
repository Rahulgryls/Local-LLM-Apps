#!/bin/bash
# LAKO — Start Backend
# Runs FastAPI server on http://localhost:8000
# Usage: ./start_backend.sh

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  LAKO Backend — FastAPI + Uvicorn"
echo "  URL:  http://localhost:8000"
echo "  Docs: http://localhost:8000/docs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Navigate to backend directory
cd "$(dirname "$0")/backend"

# Check Python
if ! command -v python3 &>/dev/null; then
  echo "❌ python3 not found. Run: brew install python@3.11"
  exit 1
fi

# Check if venv exists, create if not
if [ ! -d ".venv" ]; then
  echo "📦 Creating virtual environment..."
  python3 -m venv .venv
fi

# Activate venv
source .venv/bin/activate

# Install dependencies
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt -q

# Verify Ollama is running
echo "🔍 Checking Ollama..."
if curl -s http://localhost:11434 > /dev/null 2>&1; then
  echo "✅ Ollama is running"
else
  echo "⚠️  Ollama not detected on :11434 — start Ollama app first"
fi

# Start server
echo "🚀 Starting backend..."
uvicorn main:app --reload --host 0.0.0.0 --port 8000
