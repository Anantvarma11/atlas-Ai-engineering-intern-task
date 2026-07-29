#!/usr/bin/env bash
set -e

# Run the pipeline only if canonical.db hasn't been built yet.
# (It's committed to the repo, so this is normally a no-op.)
if [ ! -f /app/canonical.db ]; then
    echo "[start] canonical.db not found — running pipeline …"
    python3 -m pipeline.run
else
    echo "[start] canonical.db found — skipping pipeline."
fi

echo "[start] Starting API on port 8000 …"
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
