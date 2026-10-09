#!/bin/sh
# LAKO — container entrypoint (Render)
# Most modules resolve ./storage relative to the repo root; point that at the
# persistent disk so documents, Qdrant, SQLite and API keys survive redeploys.
set -e

DATA_DIR="${LAKO_STORAGE_DIR:-/var/data/storage}"
mkdir -p "$DATA_DIR" "$DATA_DIR/chromadb"
if [ ! -L /app/storage ]; then
  rm -rf /app/storage
  ln -s "$DATA_DIR" /app/storage
fi

cd /app/backend
python scripts/ensure_ui_key.py
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
