#!/bin/bash
# LAKO — Session 1 Verification Script
# Run after completing manual setup (Section 6 of reference doc)
# Checks: Python, Node, Git, Ollama, models, folder structure

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  LAKO — Session 1 Verification"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

PASS=0
FAIL=0

check() {
  local label="$1"
  local cmd="$2"
  if eval "$cmd" > /dev/null 2>&1; then
    echo "  ✅ $label"
    PASS=$((PASS+1))
  else
    echo "  ❌ $label"
    FAIL=$((FAIL+1))
  fi
}

echo "── Tools ──────────────────────────────────────"
check "Python 3.11+"   "python3 --version | grep -E 'Python 3\.(11|12)'"
check "Node.js 20+"    "node --version | grep -E 'v(20|21|22)'"
check "Git"            "git --version"
check "Ollama"         "ollama --version"

echo ""
echo "── Ollama Models ──────────────────────────────"
check "qwen3.5:9b"        "ollama list | grep qwen3.5"
check "llava:13b"         "ollama list | grep llava"
check "nomic-embed-text"  "ollama list | grep nomic"

echo ""
echo "── Ollama Service ─────────────────────────────"
check "Ollama API reachable (:11434)"  "curl -s http://localhost:11434"

echo ""
echo "── Project Structure ──────────────────────────"
check "backend/main.py"              "test -f backend/main.py"
check "backend/config.py"            "test -f backend/config.py"
check "backend/requirements.txt"     "test -f backend/requirements.txt"
check "config/config.json"           "test -f config/config.json"
check "frontend/package.json"        "test -f frontend/package.json"
check "frontend/src/main.jsx"        "test -f frontend/src/main.jsx"
check "storage/chromadb/"            "test -d storage/chromadb"
check "storage/uploads/"             "test -d storage/uploads"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -eq 0 ]; then
  echo "  🎉 Session 1 complete! Ready for Session 2."
else
  echo "  ⚠️  Fix the failed items before proceeding."
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
