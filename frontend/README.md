# Atlas Hotels — Frontend

A React + TypeScript + Tailwind UI for browsing the canonical hotel layer: search, per-hotel provenance (both supplier records side by side), matched rooms with normalized attributes, and near-miss candidates.

## Quick start

```bash
npm install
cp .env.example .env.local   # only if the API isn't on http://localhost:8000
npm run dev
```

Opens on `http://localhost:5173`. The backend must be running separately — see [`../backend/README.md`](../backend/README.md) (`docker compose up` from `backend/`, or `uvicorn api.main:app` locally).

`VITE_API_URL` (optional, defaults to `http://localhost:8000`) points the UI at the API.

## Structure

```text
src/
├── api/          # fetch client + response types (mirrors the FastAPI schema)
├── components/   # MatchBadge, ConfidenceRing, HotelCard, ProvenancePanel, RoomsList, ...
├── pages/        # HotelList (search/browse), HotelDetail (provenance + rooms + near-misses)
└── lib/          # formatting helpers
```

## Build

```bash
npm run build     # tsc -b && vite build → dist/
npm run preview   # serve the production build locally
```
