"""
Away Hotels API — canonical hotel layer.

Endpoints
---------
GET /                       Health check
GET /hotels?search=...      Search / list canonical hotels
GET /hotels/{id}            Full detail for one canonical hotel
GET /stats                  Pipeline summary statistics
"""

import json
import logging
import os
import sqlite3
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Literal

# Optional: pick up CORS_ORIGINS / RATE_LIMIT_PER_MINUTE / LOG_LEVEL /
# CANONICAL_DB_PATH from a local .env without requiring it to be exported
# manually. No-op if python-dotenv isn't installed or .env doesn't exist.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("away.api")

from api.db import (
    DB_PATH,
    get_db,
    get_hotel_by_id,
    get_near_misses_for_hotel,
    get_raw_hotel,
    get_rooms_for_hotel,
    search_hotels,
)
from api.models import (
    CanonicalRoom,
    HotelDetail,
    HotelListResponse,
    HotelSummary,
    NearMiss,
    RawSupplierHotel,
    RawSupplierRoom,
)
from pipeline.llm_adjudicate import SPEND_LOG_PATH

from api.routers import admin

app = FastAPI(
    title="Away Hotels API",
    description=(
        "Canonical hotel layer built from two Bangalore supplier feeds. "
        "Each hotel appears once; matched rooms carry structured attributes "
        "and per-match confidence."
    ),
    version="1.0.0",
)

app.include_router(admin.router)

# Comma-separated list, e.g. "https://app.example.com,https://admin.example.com".
# Defaults to "*" (read-only GET API, no cookies/auth to leak) for the
# take-home context; set explicitly for a real deployment.
_cors_origins = os.environ.get("CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _cors_origins == "*" else [o.strip() for o in _cors_origins.split(",") if o.strip()],
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Assign a request id, log method/path/status/latency."""
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled error [%s] %s %s", request_id, request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "[%s] %s %s -> %d (%.1fms)",
        request_id,
        request.method,
        request.url.path + ("?" + request.url.query if request.url.query else ""),
        response.status_code,
        elapsed_ms,
    )
    return response


# ──────────────────────────────────────────────────────────────────────────────
# Basic per-IP rate limiting (sliding window, in-memory).
#
# This is a single-process safeguard against accidental hammering / naive
# scraping, not a substitute for an edge-level limiter (API gateway, nginx,
# Cloudflare) in a real multi-instance deployment — the in-memory window
# doesn't share state across processes or restarts. Disabled by setting
# RATE_LIMIT_PER_MINUTE=0.
# ──────────────────────────────────────────────────────────────────────────────
_RATE_LIMIT = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "300"))
_request_log: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if _RATE_LIMIT <= 0 or request.url.path in ("/", "/docs", "/openapi.json", "/redoc"):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    window = _request_log[client_ip]
    while window and now - window[0] > 60:
        window.popleft()

    if len(window) >= _RATE_LIMIT:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded — try again shortly."},
            headers={"Retry-After": "60"},
        )

    window.append(now)
    return await call_next(request)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _raw_hotel_model(d: dict | None) -> RawSupplierHotel | None:
    if not d:
        return None
    return RawSupplierHotel(
        id=d["id"],
        name=d["name"] or "",
        address=d["address"] or "",
        lat=d.get("lat"),
        lon=d.get("lon"),
        stars=d.get("stars"),
        amenities=d.get("amenities", []),
        image_urls=d.get("image_urls", []),
    )


def _room_model(d: dict) -> CanonicalRoom:
    """Convert a room dict (from db.get_rooms_for_hotel) to CanonicalRoom."""
    def _raw_room(rd: dict | None) -> RawSupplierRoom | None:
        if not rd:
            return None
        return RawSupplierRoom(
            id=rd["room_id"],
            name=rd.get("name") or "",
            amenities=rd.get("amenities", []),
        )

    return CanonicalRoom(
        id=d["id"],
        name=d.get("name") or "",
        bed_type=d.get("bed_type"),
        occupancy=d.get("occupancy"),
        meal_plan=d.get("meal_plan") or "Room Only",
        view=d.get("view"),
        is_smoking=d.get("is_smoking"),
        amenities=d.get("amenities", []),
        match_status=d["match_status"],
        match_confidence=d["match_confidence"],
        supplier_a_room=_raw_room(d.get("supplier_a_room")),
        supplier_b_room=_raw_room(d.get("supplier_b_room")),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/", tags=["health"])
def health():
    """Liveness check."""
    db_ok = DB_PATH.exists()
    return {"status": "ok", "db": "ready" if db_ok else "missing"}


@app.get("/stats", tags=["meta"])
def stats(con: sqlite3.Connection = Depends(get_db)):
    """Pipeline summary: hotel and room counts by match status, and LLM spend."""
    hotel_rows = con.execute(
        "SELECT match_status, COUNT(*) AS n FROM canonical_hotels GROUP BY match_status"
    ).fetchall()
    method_rows = con.execute(
        "SELECT match_method, COUNT(*) AS n FROM canonical_hotels GROUP BY match_method"
    ).fetchall()
    room_rows = con.execute(
        "SELECT match_status, COUNT(*) AS n FROM canonical_rooms GROUP BY match_status"
    ).fetchall()
    nm_count = con.execute("SELECT COUNT(*) FROM near_misses").fetchone()[0]

    llm_spend = None
    if SPEND_LOG_PATH.exists():
        try:
            data = json.loads(SPEND_LOG_PATH.read_text())
            llm_spend = {
                "lifetime_pairs_adjudicated": data.get("lifetime_pairs_adjudicated", 0),
                "lifetime_prompt_tokens":     data.get("lifetime_prompt_tokens", 0),
                "lifetime_completion_tokens": data.get("lifetime_completion_tokens", 0),
                "lifetime_cost_usd":          data.get("lifetime_cost_usd", 0.0),
            }
        except json.JSONDecodeError:
            llm_spend = None

    return {
        "hotels": {r["match_status"]: r["n"] for r in hotel_rows},
        "hotels_by_match_method": {r["match_method"]: r["n"] for r in method_rows},
        "rooms":  {r["match_status"]: r["n"] for r in room_rows},
        "near_misses": nm_count,
        "llm_spend": llm_spend,
    }


@app.get("/hotels", response_model=HotelListResponse, tags=["hotels"])
def list_hotels(
    search: str = Query(
        default="",
        description=(
            "Free-text search over hotel name and address. "
            "Supports partial matches (e.g. 'Marriott', 'Koramangala', 'MG Road')."
        ),
    ),
    limit: int = Query(default=20, ge=1, le=200, description="Results per page"),
    offset: int = Query(default=0, ge=0, description="Pagination offset"),
    match_status: Literal["matched", "singleton"] | None = Query(
        default=None,
        description="Filter by match_status: matched | singleton",
    ),
    con: sqlite3.Connection = Depends(get_db),
):
    """
    Search or list canonical hotels.

    - `search` uses FTS5 full-text search (prefix-aware) over name + address.
    - Results are ordered by relevance when `search` is provided, by ID otherwise.
    - Pagination via `limit` / `offset`.

    **Example**

        GET /hotels?search=Taj&limit=5
        GET /hotels?search=Koramangala&match_status=matched
        GET /hotels?limit=50&offset=100
    """
    total, hotels = search_hotels(con, search, limit, offset, match_status)

    summaries = [
        HotelSummary(
            id=h["id"],
            name=h["name"],
            address=h.get("address") or "",
            lat=h.get("lat"),
            lon=h.get("lon"),
            stars=h.get("stars"),
            amenities=h.get("amenities", []),
            image_urls=h.get("image_urls", []),
            match_status=h["match_status"],
            match_confidence=h["match_confidence"],
            match_method=h.get("match_method") or "singleton",
            match_note=h.get("match_note"),
            source_ids=h.get("source_ids", {}),
        )
        for h in hotels
    ]

    return HotelListResponse(
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(summaries)) < total,
        hotels=summaries,
    )


@app.get("/hotels/{hotel_id}", response_model=HotelDetail, tags=["hotels"])
def get_hotel(
    hotel_id: str,
    con: sqlite3.Connection = Depends(get_db),
):
    """
    Full canonical hotel record.

    Includes:
    - **Merged content**: name, address, coordinates, stars, amenities, images.
    - **Provenance** (`sources`): verbatim records from each supplier.
    - **Rooms** (`rooms`): canonical room list with structured attributes
      (bed type, occupancy, meal plan, view, smoking), per-room match
      confidence, and the underlying supplier room records.
    - **Near-misses** (`near_misses`): candidates from the other supplier that
      were geographically close but scored below the match threshold —
      honest about uncertainty.

    Match statuses
    - `matched`  — hotel (or room) found in multiple suppliers
    - `singleton` — exists in only one supplier

    **Example**

        GET /hotels/CAN-00001
    """
    hotel = get_hotel_by_id(con, hotel_id)
    if hotel is None:
        raise HTTPException(status_code=404, detail=f"Hotel '{hotel_id}' not found")

    # ── Provenance: raw supplier records ──────────────────────────────────────
    sources = {}
    for supp, sid in hotel.get("source_ids", {}).items():
        raw_rec = get_raw_hotel(con, supp, sid)
        if raw_rec:
            sources[supp] = _raw_hotel_model(raw_rec)

    # ── Rooms ─────────────────────────────────────────────────────────────────
    room_dicts = get_rooms_for_hotel(con, hotel_id)
    
    rooms = []
    for d in room_dicts:
        c = CanonicalRoom(
            id=d["id"],
            name=d.get("name") or "",
            bed_type=d.get("bed_type"),
            occupancy=d.get("occupancy"),
            meal_plan=d.get("meal_plan") or "Room Only",
            view=d.get("view"),
            is_smoking=d.get("is_smoking"),
            amenities=d.get("amenities", []),
            match_status=d["match_status"],
            match_confidence=d["match_confidence"],
        )
        for supp, s_dict in d.get("sources", {}).items():
            if s_dict:
                c.sources[supp] = RawSupplierRoom(
                    id=s_dict["room_id"],
                    name=s_dict.get("name") or "",
                    amenities=s_dict.get("amenities", []),
                )
        rooms.append(c)

    # ── Near-misses ───────────────────────────────────────────────────────────
    nm_dicts = get_near_misses_for_hotel(con, hotel_id)
    near_misses = [
        NearMiss(
            supplier=n["supplier"],
            supplier_id=n["supplier_id"],
            name=n["name"],
            address=n["address"],
            confidence=n["confidence"],
            geo_score=n["geo_score"],
            name_score=n["name_score"],
        )
        for n in nm_dicts
    ]

    return HotelDetail(
        id=hotel["id"],
        name=hotel["name"],
        address=hotel.get("address") or "",
        lat=hotel.get("lat"),
        lon=hotel.get("lon"),
        stars=hotel.get("stars"),
        amenities=hotel.get("amenities", []),
        image_urls=hotel.get("image_urls", []),
        match_status=hotel["match_status"],
        match_confidence=hotel["match_confidence"],
        match_method=hotel.get("match_method") or "singleton",
        match_note=hotel.get("match_note"),
        source_ids=hotel.get("source_ids", {}),
        sources=sources,
        rooms=rooms,
        near_misses=near_misses,
    )
