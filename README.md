# Away Hotels API

A canonical hotel layer built from two Bangalore supplier feeds. Each physical hotel appears once, with merged content, source provenance, matched rooms with structured attributes, and honest match confidence.

---

## Quick Start

### Option 1 — Docker (one command, recommended)

```bash
docker compose up
```

The image is ~170 MB. On first build it installs Python packages; `canonical.db` is already committed so the pipeline is skipped and the API starts in under 10 seconds.

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

The pipeline takes ~8–10 s on a laptop and is idempotent (`--force` re-runs it).

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
Pipeline summary: hotel and room counts by match status.

```bash
curl http://localhost:8000/stats
```
```json
{
  "hotels":  { "matched": 2564, "a_only": 845, "b_only": 1198 },
  "rooms":   { "matched": 1753, "a_only": 2148, "b_only": 15541 },
  "near_misses": 21742
}
```

---

### `GET /hotels`

Search or list canonical hotels.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `search` | string | `""` | FTS5 full-text search over name + address (prefix-aware) |
| `limit` | int | `20` | Max results (1–200) |
| `offset` | int | `0` | Pagination offset |
| `match_status` | string | — | Filter: `matched` \| `a_only` \| `b_only` |

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
  "total": 3,
  "limit": 5,
  "offset": 0,
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
      "supplier_a_id": "A-XXXXX",
      "supplier_b_id": "B-XXXXX"
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
  "supplier_a_id": "A-07887",
  "supplier_b_id": "B-66857",

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
      "supplier_a_room": { "id": "RA-32340", "name": "Deluxe Room - Non Smoking · City view", "amenities": ["..."] },
      "supplier_b_room": { "id": "RB-XXXXX", "name": "Deluxe, Double",                        "amenities": [] }
    },
    {
      "id": "CAN-RM-000043",
      "name": "Run of House",
      "bed_type": null,
      "match_status": "b_only",
      "match_confidence": 1.0,
      "supplier_a_room": null,
      "supplier_b_room": { "id": "RB-YYYYY", "name": "Run of House", "amenities": [] }
    }
  ],

  "near_misses": [
    {
      "supplier_b_id": "B-ZZZZZ",
      "name": "Crystal Palace Inn",
      "address": "...",
      "confidence": 0.47,
      "geo_score": 0.61,
      "name_score": 0.33
    }
  ]
}
```

**Field reference**

| Field | Description |
|-------|-------------|
| `match_status` | `matched` / `a_only` / `b_only` for both hotels and rooms |
| `match_confidence` | 0–1 combined score; 1.0 for singletons (no second source to compare against) |
| `sources` | Verbatim supplier records — full provenance |
| `rooms[].bed_type` | `King` / `Queen` / `Twin` / `Double` / `Single` / `Suite` / `Bunk` / `Dormitory` or `null` |
| `rooms[].occupancy` | `Single` / `Double` / `Triple` / `Family` or `null` |
| `rooms[].meal_plan` | `Room Only` / `Breakfast` / `Half Board` / `Full Board` |
| `rooms[].view` | `City` / `Pool` / `Garden` / `Sea` / `Mountain` / `Courtyard` or `null` |
| `near_misses` | Sub-threshold B candidates; sorted by confidence descending |

---

## Repository Structure

```
.
├── pipeline/
│   ├── load.py          # CSV parsing + cleaning
│   ├── match_hotels.py  # Geo-blocking + fuzzy entity resolution
│   ├── match_rooms.py   # Room matching + attribute extraction
│   ├── merge.py         # Canonical record builder → SQLite + JSON
│   └── run.py           # Pipeline entry-point
├── api/
│   ├── main.py          # FastAPI app
│   ├── models.py        # Pydantic response schemas
│   └── db.py            # SQLite query helpers
├── supplier_a.csv        # Supplier A hotel feed (~3 400 rows)
├── supplier_b.csv        # Supplier B hotel feed (~3 800 rows)
├── rooms_a.csv           # Supplier A room feed (~3 900 rows)
├── rooms_b.csv           # Supplier B room feed (~17 300 rows)
├── canonical.db          # ✅ Committed SQLite artifact
├── canonical_hotels.json # ✅ Committed JSON artifact (hotels + rooms + near-misses)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── start.sh
└── WRITEUP.md
```

## Rebuild the canonical layer

```bash
# Force a fresh run (overwrites canonical.db and canonical_hotels.json)
python -m pipeline.run --force
```
