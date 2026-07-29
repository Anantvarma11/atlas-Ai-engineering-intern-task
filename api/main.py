"""
Away Hotels API — canonical hotel layer.

Endpoints
---------
GET /                       Health check
GET /hotels?search=...      Search / list canonical hotels
GET /hotels/{id}            Full detail for one canonical hotel
GET /stats                  Pipeline summary statistics
"""

import sqlite3
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api.db import (
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
    HotelSources,
    HotelSummary,
    NearMiss,
    RawSupplierHotel,
    RawSupplierRoom,
)

app = FastAPI(
    title="Away Hotels API",
    description=(
        "Canonical hotel layer built from two Bangalore supplier feeds. "
        "Each hotel appears once; matched rooms carry structured attributes "
        "and per-match confidence."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


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
    db_ok = Path(__file__).parent.parent.joinpath("canonical.db").exists()
    return {"status": "ok", "db": "ready" if db_ok else "missing"}


@app.get("/stats", tags=["meta"])
def stats(con: sqlite3.Connection = Depends(get_db)):
    """Pipeline summary: hotel and room counts by match status."""
    hotel_rows = con.execute(
        "SELECT match_status, COUNT(*) AS n FROM canonical_hotels GROUP BY match_status"
    ).fetchall()
    room_rows = con.execute(
        "SELECT match_status, COUNT(*) AS n FROM canonical_rooms GROUP BY match_status"
    ).fetchall()
    nm_count = con.execute("SELECT COUNT(*) FROM near_misses").fetchone()[0]

    return {
        "hotels": {r["match_status"]: r["n"] for r in hotel_rows},
        "rooms":  {r["match_status"]: r["n"] for r in room_rows},
        "near_misses": nm_count,
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
    match_status: str | None = Query(
        default=None,
        description="Filter by match_status: matched | a_only | b_only",
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
            supplier_a_id=h.get("supplier_a_id"),
            supplier_b_id=h.get("supplier_b_id"),
        )
        for h in hotels
    ]

    return HotelListResponse(total=total, limit=limit, offset=offset, hotels=summaries)


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
    - **Near-misses** (`near_misses`): B hotels that were geographically close
      but scored below the match threshold — honest about uncertainty.

    Match statuses
    - `matched`  — hotel (or room) found in both suppliers
    - `a_only`   — exists only in Supplier A
    - `b_only`   — exists only in Supplier B

    **Example**

        GET /hotels/CAN-00001
    """
    hotel = get_hotel_by_id(con, hotel_id)
    if hotel is None:
        raise HTTPException(status_code=404, detail=f"Hotel '{hotel_id}' not found")

    # ── Provenance: raw supplier records ──────────────────────────────────────
    raw_a = get_raw_hotel(con, "a", hotel["supplier_a_id"]) if hotel.get("supplier_a_id") else None
    raw_b = get_raw_hotel(con, "b", hotel["supplier_b_id"]) if hotel.get("supplier_b_id") else None

    sources = HotelSources(
        supplier_a=_raw_hotel_model(raw_a),
        supplier_b=_raw_hotel_model(raw_b),
    )

    # ── Rooms ─────────────────────────────────────────────────────────────────
    room_dicts = get_rooms_for_hotel(con, hotel_id)
    rooms = [_room_model(r) for r in room_dicts]

    # ── Near-misses ───────────────────────────────────────────────────────────
    nm_dicts = get_near_misses_for_hotel(con, hotel_id)
    near_misses = [
        NearMiss(
            supplier_b_id=n["supplier_b_id"],
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
        supplier_a_id=hotel.get("supplier_a_id"),
        supplier_b_id=hotel.get("supplier_b_id"),
        sources=sources,
        rooms=rooms,
        near_misses=near_misses,
    )
