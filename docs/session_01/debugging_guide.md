# LAKO Session 1 — Debugging Guide
**Audience:** You when things break
**Date:** 2026-03-27

---

## Errors Encountered This Session

None — Session 1 was file creation only (no runtime execution required).

---

## Hypothetical Errors You May Encounter

### Error 1: `ModuleNotFoundError: No module named 'fastapi'`

**Symptom:** Backend crashes immediately when you run `uvicorn main:app`

**Cause:** Python dependencies not installed in the active virtual environment.

**Fix:**
```bash
cd lako/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

---

### Error 2: `Error: Cannot find module 'react'` (frontend)

**Symptom:** `npm run dev` fails immediately

**Cause:** `npm install` not yet run in the frontend directory.

**Fix:**
```bash
cd lako/frontend
npm install
npm run dev
```

---

### Error 3: `[LAKO] WARNING: config.json not found`

**Symptom:** Backend prints this warning on startup but still starts

**Cause:** Running `uvicorn` from wrong directory (not inside `backend/`), so relative path to `config/` is wrong.

**Fix:**
```bash
# Always start backend from inside backend/ directory
cd lako/backend
uvicorn main:app --reload
```

Alternatively, use the provided `start_backend.sh` script which handles the directory automatically.

---

### Error 4: Ollama models not found (`ollama list` shows nothing)

**Symptom:** `verify_session1.sh` fails the model checks

**Cause:** `ollama pull` commands were not run, or Ollama was not yet installed.

**Fix:**
```bash
# Make sure Ollama app is running (check menu bar icon on Mac)
ollama pull qwen3.5:9b        # ~8.8 GB download — takes time
ollama pull llava:13b          # ~10.5 GB download
ollama pull nomic-embed-text   # ~0.5 GB download
```

---

### Error 5: `CORS error` in browser when frontend calls backend

**Symptom:** Browser console shows `Access-Control-Allow-Origin` error

**Cause:** Frontend is running on a port other than 5173, but CORS is configured for 5173 only.

**Fix:** In `backend/main.py`, add your port to the `allow_origins` list:
```python
allow_origins=["http://localhost:5173", "http://localhost:YOUR_PORT"]
```

---

### Error 6: `Address already in use: 8000` or `5173`

**Symptom:** Server refuses to start

**Cause:** Previous server process still running in background.

**Fix (Mac):**
```bash
# Kill process on port 8000
lsof -ti:8000 | xargs kill -9

# Kill process on port 5173
lsof -ti:5173 | xargs kill -9
```

---

### Error 7: Frontend shows blank white page

**Symptom:** Browser opens but page is blank, no sidebar visible

**Cause:** JavaScript error preventing React from mounting. Check browser console (F12).

**Common sub-causes:**
- Missing Tailwind CSS build (run `npm run build` or check PostCSS config)
- i18n init error — check `frontend/src/i18n/i18n.js` imports
- React Router version mismatch

**Fix:** Open browser DevTools → Console → read the specific error message.

---

## Verification Checklist

Run this before declaring Session 1 complete:

```bash
cd lako
./verify_session1.sh
```

Expected output: all checkmarks green, 0 failures.

If any fail, this guide covers all common causes above.
