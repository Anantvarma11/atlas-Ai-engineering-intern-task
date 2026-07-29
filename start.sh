#!/usr/bin/env bash
# Starts the Away Hotels backend (FastAPI) and frontend (Vite) together for
# local development. Docker's own entrypoint is backend/start.sh — this one
# is for running both without containers.
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

# Prefer a backend-local venv, then a root-level one, then system python3.
if [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
    PYTHON="$BACKEND_DIR/.venv/bin/python"
elif [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON="$ROOT_DIR/.venv/bin/python"
else
    PYTHON="python3"
fi

cleanup() {
    echo
    echo "[start] Shutting down…"
    [ -n "${API_PID:-}" ] && kill "$API_PID" 2>/dev/null
    [ -n "${UI_PID:-}" ] && kill "$UI_PID" 2>/dev/null
    wait 2>/dev/null
}
trap cleanup EXIT INT TERM

# ── Backend ──────────────────────────────────────────────────────────────
cd "$BACKEND_DIR"
if [ ! -f canonical.db ]; then
    echo "[start] canonical.db not found — running pipeline…"
    "$PYTHON" -m pipeline.run
else
    echo "[start] canonical.db found — skipping pipeline."
fi

echo "[start] Starting API on http://localhost:8000 …"
"$PYTHON" -m uvicorn api.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!

# ── Frontend ─────────────────────────────────────────────────────────────
cd "$FRONTEND_DIR"
if [ ! -d node_modules ]; then
    echo "[start] Installing frontend dependencies…"
    npm install
fi

echo "[start] Starting UI on http://localhost:5173 …"
npm run dev &
UI_PID=$!

wait "$API_PID" "$UI_PID"
