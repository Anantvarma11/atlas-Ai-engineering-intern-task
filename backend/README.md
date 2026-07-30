# Away Hotels API

A canonical hotel layer built from any number of supplier feeds (two Bangalore
feeds, "A" and "B", by default). Each physical hotel appears once, with merged
content, full source provenance, matched rooms with structured attributes, and
honest match confidence.

---

## Quick Start

### Option 1 — Docker (one command, recommended)

```bash
docker compose up
```

The image is ~170 MB. `canonical.db` is already committed, so the pipeline is
skipped and the API starts in under 10 seconds.

```
[start] canonical.db found — skipping pipeline.
[start] Starting API on port 8000 …
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### Option 2 — Local (Python 3.12)

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the pipeline (skip if canonical.db is already present)
python -m pipeline.run

# 4. Start the API
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

The committed `canonical.db` means this is normally a no-op. A full `--force`
rebuild over the ~7,200 hotels / ~21,200 rooms in `data/` takes roughly
**9 minutes** on a laptop — see `WRITEUP.md` for why (semantic embedding
search traded for wall-clock time) and what a faster path would look like.

### Optional: LLM adjudication of hard cases

The pipeline runs at **$0 by default**. If you want to sharpen the handful of
genuinely ambiguous hotel-matching cases, copy `.env.example` to `.env` and
set `CEREBRAS_API_KEY`:

```bash
cp .env.example .env
# edit .env and set CEREBRAS_API_KEY=csk-...
python -m pipeline.run --force
```

This adjudicates a **bounded, targeted** set of near-miss pairs (capped at
200, see `pipeline/llm_adjudicate.py`) that are geographically plausible but
too ambiguous on name evidence for the heuristic to decide — never the
obvious matches or non-matches. Every request/response is cached in
`pipeline/cache/llm_adjudications.json` (committed), so a re-run — or anyone
grading this without a key — reproduces the exact same result at $0. Actual
token spend accumulates in `pipeline/cache/llm_spend.json` and is surfaced
at `GET /stats`. See `WRITEUP.md` for the cost accounting.

### Optional: admin panel (add a supplier, re-run the pipeline from the UI)

Set `ADMIN_API_KEY` in `.env` to enable `/admin/*` (upload a supplier CSV/XLSX,
delete a staged file, trigger a pipeline re-run) and the frontend's `/admin`
page. Unset by default — the routes return `503` until a key is configured,
so there's no built-in password to guess.

---

## API Reference

Base URL: `http://localhost:8000`

Interactive docs (Swagger UI): `http://localhost:8000/docs`

### `GET /`
Health check.

```bash
curl http://localhost:8000/
# {"status":"ok","db":"ready"}
```

---

### `GET /stats`
Pipeline summary: hotel and room counts by match status, from the last real run.

```bash
curl http://localhost:8000/stats
```
```json
{
  "hotels": { "matched": 2540, "singleton": 2091 },
  "hotels_by_match_method": { "geo_fuzzy": 2459, "rescue": 66, "llm": 15, "singleton": 2091 },
  "rooms": { "matched": 1711, "singleton": 17773 },
  "near_misses": 26536,
  "llm_spend": {
    "lifetime_pairs_adjudicated": 97,
    "lifetime_prompt_tokens": 11413,
    "lifetime_completion_tokens": 17685,
    "lifetime_cost_usd": 0.0
  }
}
```

`llm_spend` is `null` until the optional LLM adjudication pass has run at
least once (see "Optional: LLM adjudication of hard cases" above); once it
has, this shows lifetime tokens and dollars spent, computed from the same
`pipeline/cache/llm_spend.json` that backs the write-up's cost figure.

---

### `GET /hotels`

Search or list canonical hotels.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `search` | string | `""` | FTS5 full-text search over name + address (prefix-aware) |
| `limit` | int | `20` | Max results (1–200) |
| `offset` | int | `0` | Pagination offset |
| `match_status` | string | — | Filter: `matched` \| `singleton` |

**Example requests**

```bash
# Search for Marriott hotels
curl "http://localhost:8000/hotels?search=Marriott&limit=5"

# Hotels in Koramangala
curl "http://localhost:8000/hotels?search=Koramangala&limit=10"

# All matched hotels, page 2
curl "http://localhost:8000/hotels?match_status=matched&limit=20&offset=20"

# List all hotels (no search)
curl "http://localhost:8000/hotels?limit=50"
```

**Response shape**

```json
{
  "total": 2540,
  "limit": 5,
  "offset": 0,
  "has_more": true,
  "hotels": [
    {
      "id": "CAN-01234",
      "name": "JW Marriott Hotel Bengaluru",
      "address": "...",
      "lat": 12.9716,
      "lon": 77.5946,
      "stars": 5.0,
      "amenities": ["Swimming pool", "Spa", "Gym"],
      "image_urls": ["https://storage.googleapis.com/..."],
      "match_status": "matched",
      "match_confidence": 0.93,
      "match_method": "geo_fuzzy",
      "match_note": null,
      "source_ids": { "supplier_a": "A-XXXXX", "supplier_b": "B-XXXXX" }
    }
  ]
}
```

---

### `GET /hotels/{id}`

Full canonical hotel record.

```bash
# Get hotel CAN-00001
curl "http://localhost:8000/hotels/CAN-00001"

# Pretty-print with jq
curl -s "http://localhost:8000/hotels/CAN-00001" | jq .
```

**Response shape** (abbreviated)

```json
{
  "id": "CAN-00001",
  "name": "Hotel Crystal Castle",
  "address": "Near Hotel Nandhini, 24th Main Road, JP Nagar, Bangalore",
  "lat": 12.90319,
  "lon": 77.58594,
  "stars": 3.0,
  "amenities": ["Smoke-free property", "24-hour front desk", "Smoke-Complimentary Property"],
  "image_urls": ["https://storage.googleapis.com/..."],
  "match_status": "matched",
  "match_confidence": 1.0,
  "match_method": "geo_fuzzy",
  "match_note": null,
  "source_ids": { "supplier_a": "A-07887", "supplier_b": "B-66857" },

  "sources": {
    "supplier_a": {
      "id": "A-07887",
      "name": "Hotel Crystal Castle",
      "address": "...",
      "lat": 12.90319, "lon": 77.58594,
      "stars": 3.0,
      "amenities": ["Smoke-free property", "24-hour front desk"],
      "image_urls": ["https://storage.googleapis.com/img/a/A-07887/0.jpg", "..."]
    },
    "supplier_b": {
      "id": "B-66857",
      "name": "Hotel Crystal Castle",
      "amenities": ["Smoke-Complimentary Property"],
      "image_urls": ["https://storage.googleapis.com/img/b/B-66857/0.jpg", "..."]
    }
  },

  "rooms": [
    {
      "id": "CAN-RM-000042",
      "name": "Deluxe Room · City view",
      "bed_type": "Double",
      "occupancy": "Double",
      "meal_plan": "Room Only",
      "view": "City",
      "is_smoking": false,
      "amenities": ["Double Bed", "225 sq.ft", "Wardrobe/closet", "TV"],
      "match_status": "matched",
      "match_confidence": 0.82,
      "sources": {
        "supplier_a": { "id": "RA-32340", "name": "Deluxe Room - Non Smoking · City view", "amenities": [] },
        "supplier_b": { "id": "RB-XXXXX", "name": "Deluxe, Double", "amenities": [] }
      }
    },
    {
      "id": "CAN-RM-000043",
      "name": "Run of House",
      "bed_type": null,
      "match_status": "singleton",
      "match_confidence": 1.0,
      "sources": { "supplier_b": { "id": "RB-YYYYY", "name": "Run of House", "amenities": [] } }
    }
  ],

  "near_misses": [
    {
      "supplier": "supplier_b",
      "supplier_id": "B-ZZZZZ",
      "name": "Crystal Palace Inn",
      "address": "...",
      "confidence": 0.47,
      "geo_score": 0.61,
      "name_score": 0.33
    }
  ]
}
```

Near-misses are attached to every hotel that had a plausible-but-rejected
candidate, not only to hotels that ended up matched — a `singleton` hotel
that almost matched is exactly the case a reviewer most wants visibility
into.

**Field reference**

| Field | Description |
|-------|-------------|
| `match_status` | `matched` (found in 2+ suppliers) / `singleton` (found in exactly one) |
| `match_confidence` | 0–1 combined score; 1.0 for singletons (no second source to compare against) |
| `match_method` | How a hotel match was decided: `geo_fuzzy` (main geo+semantic pass) / `rescue` (identical-name, relaxed-geo pass) / `llm` (Cerebras adjudication of a hard case) / `singleton` (found in only one supplier) |
| `match_note` | LLM's one-line rationale, only set when `match_method` is `llm` |
| `source_ids` / `sources` | `{supplier_name: id}` / `{supplier_name: raw record}` — one entry per supplier the hotel was seen in |
| `rooms[].bed_type` | `King` / `Queen` / `Twin` / `Double` / `Single` / `Bunk` / `Dormitory` / `Sofa Bed` / `Multiple Beds` or `null` |
| `rooms[].occupancy` | `Single` / `Double` / `Triple` / `Family` or `null` |
| `rooms[].meal_plan` | `Room Only` / `Breakfast` / `Half Board` / `Full Board` |
| `rooms[].view` | `City` / `Pool` / `Garden` / `Sea` / `Mountain` / `Courtyard` or `null` |
| `near_misses` | Sub-threshold candidates considered but not matched; sorted by confidence descending |

---

## Repository Structure

```
.
├── pipeline/
│   ├── load.py             # CSV parsing + cleaning
│   ├── match_hotels.py     # Geo-filtered semantic search + weighted one-to-one matching
│   ├── match_rooms.py      # Cross-supplier room matching + attribute extraction
│   ├── llm_adjudicate.py   # Optional Cerebras adjudication of hard near-misses
│   ├── merge.py            # Canonical record builder → SQLite + JSON
│   ├── run.py               # Pipeline entry-point
│   └── cache/               # LLM request/response cache + spend log (committed)
├── api/
│   ├── main.py              # FastAPI app + middleware (logging, rate limit, errors)
│   ├── models.py            # Pydantic response schemas
│   ├── db.py                # SQLite query helpers
│   └── routers/
│       └── admin.py         # Optional admin routes (upload supplier, trigger pipeline)
├── tests/                   # pytest: matching, merge/provenance, LLM adjudication, API contract
├── data/                     # Raw supplier feeds, named {supplier}_hotels.csv / {supplier}_rooms.csv
│   ├── supplier_a_hotels.csv
│   ├── supplier_a_rooms.csv
│   ├── supplier_b_hotels.csv
│   └── supplier_b_rooms.csv
├── canonical.db              # committed SQLite artifact (the pipeline's output)
├── canonical_hotels.json     # committed JSON artifact (same data, nested)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── start.sh
├── .env.example              # copy to .env to enable LLM adjudication / admin panel / tune config
└── WRITEUP.md
```

## Configuration (all optional — sane defaults, nothing required to run)

| Env var | Default | Purpose |
|---|---|---|
| `CEREBRAS_API_KEY` | unset | Enables the LLM adjudication pass in the pipeline (see above). Pipeline runs at $0 without it. |
| `ADMIN_API_KEY` | unset | Enables `/admin/*` and the frontend admin panel. Routes return `503` until set. |
| `CANONICAL_DB_PATH` | `./canonical.db` | Point the API at a DB built/mounted elsewhere. |
| `CORS_ORIGINS` | `*` | Comma-separated allow-list for a real deployment; `*` is fine for this read-only API. |
| `RATE_LIMIT_PER_MINUTE` | `300` | Per-IP sliding-window cap (in-memory, single-process); `0` disables it. |
| `LOG_LEVEL` | `INFO` | Python logging level for the API. |

Set these in `.env` (auto-loaded by both the pipeline and the API) or export
them directly — either works with `docker compose up` or a local run.

## Production-hardening notes

- **Errors never leak internals**: unhandled exceptions return a clean
  `{"detail": "Internal server error", "request_id": "..."}` (500), logged
  server-side with a stack trace; only genuinely unexpected bugs hit this
  path — `HTTPException`s (404s, validation errors) pass through unchanged.
- **Every response carries `X-Request-ID`** (also logged) for tracing a
  specific request through logs.
- **Read-only DB connections** (`mode=ro`): the API can never mutate
  `canonical.db`; a missing DB fails fast with a 503, not a silently-created
  empty file.
- **Basic per-IP rate limiting** is a single-process safeguard, not a
  substitute for an edge limiter in a real multi-instance deployment.
- **Admin routes are opt-in and unauthenticated by default**: with
  `ADMIN_API_KEY` unset they simply don't work (`503`), rather than falling
  back to a default credential.

## Rebuild the canonical layer

```bash
# Force a fresh run (overwrites canonical.db and canonical_hotels.json)
python -m pipeline.run --force
```

Add a new supplier by dropping `{name}_hotels.csv` and `{name}_rooms.csv`
(same columns as the existing files) into `data/` before re-running — the
pipeline discovers suppliers by filename, it isn't hardcoded to two.
