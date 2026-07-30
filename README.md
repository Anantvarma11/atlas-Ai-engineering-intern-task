# Away Hotels

A canonical hotel layer built from any number of supplier feeds (two Bangalore feeds by default), plus a UI on top.

## Live Demo

- **Frontend UI:** [https://away-ai-engineering-intern-task.vercel.app](https://away-ai-engineering-intern-task.vercel.app)
- **Backend API:** [https://atlas-ai-engineering-intern-task-away.onrender.com/docs](https://atlas-ai-engineering-intern-task-away.onrender.com/docs)

```text
backend/    FastAPI service + matching pipeline — see backend/README.md
frontend/   React + TypeScript + Tailwind UI    — see frontend/README.md
```

## Run both

```bash
./start.sh
```

Builds `canonical.db` if it's missing, then starts the API and UI together. UI: `http://localhost:5173` · API: `http://localhost:8000` (docs at `/docs`). Ctrl-C stops both.

Prefer separate terminals, or just the API via Docker?

```bash
# Terminal 1 — API (from backend/)
cd backend
docker compose up          # or: uvicorn api.main:app --host 0.0.0.0 --port 8000

# Terminal 2 — UI (from frontend/)
cd frontend
npm install
npm run dev
```

See [`backend/README.md`](backend/README.md) for the API contract, matching approach, and cost accounting, and [`backend/WRITEUP.md`](backend/WRITEUP.md) for the write-up.
