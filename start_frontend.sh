#!/bin/bash
# LAKO — Start Frontend
# Runs React + Vite dev server on http://localhost:5173
# Usage: ./start_frontend.sh

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  LAKO Frontend — React + Vite"
echo "  URL: http://localhost:5173"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Navigate to frontend directory
cd "$(dirname "$0")/frontend"

# Check Node.js
if ! command -v node &>/dev/null; then
  echo "❌ node not found. Run: brew install node@20"
  exit 1
fi

echo "📦 Installing npm dependencies (first run only)..."
npm install

echo "🚀 Starting frontend dev server..."
npm run dev
