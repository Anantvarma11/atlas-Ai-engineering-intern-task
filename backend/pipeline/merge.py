"""
Build canonical hotel + room records and persist to SQLite + JSON.

Schema overview
---------------
canonical_hotels  — one row per real-world hotel
canonical_rooms   — one row per canonical room
near_misses       — sub-threshold hotel candidates
raw_hotels        — verbatim supplier records (provenance)
raw_rooms         — verbatim room records
hotels_fts        — FTS5 index over canonical_hotels for text search
"""

import json
import math
import sqlite3
from pathlib import Path

import pandas as pd

from pipeline.image_dedupe import dedupe_image_urls, flush_cache
from pipeline.match_rooms import extract_attrs, extract_occupancy, match_rooms_for_hotel

DB_PATH = Path(__file__).parent.parent / "canonical.db"
JSON_PATH = Path(__file__).parent.parent / "canonical_hotels.json"

# ──────────────────────────────────────────────────────────────────────────────
# Small helpers
# ──────────────────────────────────────────────────────────────────────────────

def _pick_name(names: list[str]) -> str:
    """Return whichever name is longest (usually more descriptive)."""
    valid = [n.strip() for n in names if n and str(n).strip()]
    if not valid:
        return ""
    return max(valid, key=len)


def _merge_lists(lists: list[list]) -> list:
    """Union multiple lists, deduplicating by lowercase string value."""
    seen: set[str] = set()
    result: list = []
    for lst in lists:
        for item in (lst or []):
            key = str(item).lower().strip()
            if key and key not in seen:
                seen.add(key)
                result.append(item)
    return result


def _safe_avg(vals: list):
    """Average values; handle NaN / None gracefully."""
    valid = []
    for v in vals:
        try:
            if v is not None and not math.isnan(float(v)):
                valid.append(float(v))
        except (TypeError, ValueError):
            pass
            
    if not valid:
        return None
    return round(sum(valid) / len(valid), 6)


def _safe_float(v):
    try:
        f = float(v)
        return None if math.isnan(f) else round(f, 6)
    except (TypeError, ValueError):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# SQLite DDL
# ──────────────────────────────────────────────────────────────────────────────

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS raw_hotels (
    supplier    TEXT,
    id          TEXT,
    name        TEXT,
    address     TEXT,
    lat         REAL,
    lon         REAL,
    stars       REAL,
    amenities   TEXT,   -- JSON array
    image_urls  TEXT,   -- JSON array
    PRIMARY KEY (supplier, id)
);

CREATE TABLE IF NOT EXISTS canonical_hotels (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    address         TEXT,
    lat             REAL,
    lon             REAL,
    stars           REAL,
    amenities       TEXT,   -- JSON array
    image_urls      TEXT,   -- JSON array
    match_status    TEXT NOT NULL,   -- 'matched' | 'singleton'
    match_confidence REAL NOT NULL,
    match_method    TEXT NOT NULL,   -- 'geo_fuzzy' | 'rescue' | 'singleton'
    match_note      TEXT,            -- LLM adjudication rationale
    source_ids      TEXT             -- JSON dictionary of {supplier: id}
);

CREATE TABLE IF NOT EXISTS raw_rooms (
    supplier    TEXT,
    room_id     TEXT,
    hotel_id    TEXT,
    name        TEXT,
    amenities   TEXT,    -- JSON array
    PRIMARY KEY (supplier, room_id)
);

CREATE TABLE IF NOT EXISTS canonical_rooms (
    id                   TEXT PRIMARY KEY,
    canonical_hotel_id   TEXT NOT NULL REFERENCES canonical_hotels(id),
    name                 TEXT,
    bed_type             TEXT,
    occupancy            TEXT,
    meal_plan            TEXT,
    view                 TEXT,
    is_smoking           INTEGER,   -- 0 / 1 / NULL
    amenities            TEXT,      -- JSON array
    match_status         TEXT NOT NULL,
    match_confidence     REAL NOT NULL,
    source_room_ids      TEXT,      -- JSON dictionary of {supplier: room_id}
    source_names         TEXT       -- JSON dictionary of {supplier: name}
);

CREATE TABLE IF NOT EXISTS near_misses (
    canonical_hotel_id  TEXT NOT NULL,
    candidate_supplier  TEXT NOT NULL,
    candidate_id        TEXT NOT NULL,
    confidence          REAL,
    geo_score           REAL,
    name_score          REAL
);

CREATE VIRTUAL TABLE IF NOT EXISTS hotels_fts USING fts5(
    id,
    name,
    address,
    tokenize = 'unicode61'
);

CREATE INDEX IF NOT EXISTS idx_rooms_hotel ON canonical_rooms(canonical_hotel_id);
CREATE INDEX IF NOT EXISTS idx_nm_hotel    ON near_misses(canonical_hotel_id);
"""


# ──────────────────────────────────────────────────────────────────────────────
# Main builder
# ──────────────────────────────────────────────────────────────────────────────

def build_canonical(
    hotel_dfs: dict[str, pd.DataFrame],
    room_dfs: dict[str, pd.DataFrame],
    components: list[dict],
    near_misses_df: pd.DataFrame,
    db_path: Path = DB_PATH,
    json_path: Path = JSON_PATH,
) -> tuple[int, int, int]:
    """
    Build canonical records and write to SQLite + JSON.
    Returns (n_hotels, n_rooms, n_near_misses).
    """
    # Index raw data for O(1) lookups
    hotels_indexed: dict[str, dict[str, dict]] = {}
    for supp, df in hotel_dfs.items():
        hotels_indexed[supp] = {row["id"]: row for _, row in df.iterrows()}

    # Group rooms by supplier and hotel_id
    rooms_by_hotel: dict[str, dict[str, pd.DataFrame]] = {}
    for supp, df in room_dfs.items():
        rooms_by_hotel[supp] = {}
        for hid, grp in df.groupby("hotel_id"):
            rooms_by_hotel[supp][hid] = grp.reset_index(drop=True)

    canonical_hotels: list[dict] = []
    canonical_rooms:  list[dict] = []
    near_miss_rows:   list[dict] = []

    hotel_counter = 1
    room_counter  = 1

    def next_hotel_id() -> str:
        nonlocal hotel_counter
        hid = f"CAN-{hotel_counter:05d}"
        hotel_counter += 1
        return hid

    def next_room_id() -> str:
        nonlocal room_counter
        rid = f"CAN-RM-{room_counter:06d}"
        room_counter += 1
        return rid

    def _attach_rooms(cid: str, source_ids: dict[str, str]) -> None:
        cluster_room_dfs: dict[str, pd.DataFrame] = {}
        for supp, hid in source_ids.items():
            r_df = rooms_by_hotel.get(supp, {}).get(hid)
            if r_df is not None and not r_df.empty:
                cluster_room_dfs[supp] = r_df

        if not cluster_room_dfs:
            return

        for comp in match_rooms_for_hotel(cluster_room_dfs):
            source_room_ids = {n["supplier"]: n["room_id"] for n in comp["nodes"]}
            source_names = {n["supplier"]: n["name"] for n in comp["nodes"]}

            canon_name = _pick_name([n["name"] for n in comp["nodes"]])
            merged_am = _merge_lists([n["amenities"] for n in comp["nodes"]])

            attrs = extract_attrs(canon_name, merged_am)
            occ = extract_occupancy(canon_name, merged_am)
            is_sm = attrs["is_smoking"]

            canonical_rooms.append({
                "id": next_room_id(),
                "canonical_hotel_id": cid,
                "name": canon_name,
                "bed_type": attrs["bed_type"],
                "occupancy": occ,
                "meal_plan": attrs["meal_plan"],
                "view": attrs["view"],
                "is_smoking": None if is_sm is None else int(is_sm),
                "amenities": merged_am,
                "match_status": "matched" if len(comp["nodes"]) > 1 else "singleton",
                "match_confidence": comp["confidence"],
                "source_room_ids": source_room_ids,
                "source_names": source_names,
            })

    def _attach_near_misses(cid: str, source_ids: dict[str, str]) -> None:
        if near_misses_df.empty:
            return
            
        for supp, hid in source_ids.items():
            # If this hotel was involved in any near miss
            node_id = f"{supp}::{hid}"
            
            # Find rows where a_id or b_id matches
            nm_a = near_misses_df[near_misses_df["a_id"] == node_id]
            for _, row in nm_a.iterrows():
                near_miss_rows.append({
                    "canonical_hotel_id": cid,
                    "candidate_supplier": row["supplier_b"],
                    "candidate_id": row["b_id"].split("::")[1],
                    "confidence": float(row["confidence"]),
                    "geo_score": float(row["geo_score"]),
                    "name_score": float(row["name_score"])
                })
                
            nm_b = near_misses_df[near_misses_df["b_id"] == node_id]
            for _, row in nm_b.iterrows():
                near_miss_rows.append({
                    "canonical_hotel_id": cid,
                    "candidate_supplier": row["supplier_a"],
                    "candidate_id": row["a_id"].split("::")[1],
                    "confidence": float(row["confidence"]),
                    "geo_score": float(row["geo_score"]),
                    "name_score": float(row["name_score"])
                })

    for comp in components:
        cid = next_hotel_id()
        names = []
        addresses = []
        lats = []
        lons = []
        stars = []
        amenities = []
        images = []
        source_ids = {}

        for node in comp["nodes"]:
            supp = node["supplier"]
            hid = node["id"]
            if supp in hotels_indexed and hid in hotels_indexed[supp]:
                raw = hotels_indexed[supp][hid]
                names.append(str(raw["name"]))
                if raw["address"]:
                    addresses.append(str(raw["address"]))
                lats.append(raw["lat"])
                lons.append(raw["lon"])
                stars.append(raw.get("stars"))
                amenities.append(list(raw["amenities"]))
                images.append(list(raw["image_urls"]))
                source_ids[supp] = hid

        if not source_ids:
            continue

        canonical_hotels.append({
            "id": cid,
            "name": _pick_name(names),
            "address": _pick_name(addresses), # Just pick the longest address
            "lat": _safe_avg(lats),
            "lon": _safe_avg(lons),
            "stars": _safe_avg(stars),
            "amenities": _merge_lists(amenities),
            "image_urls": dedupe_image_urls(_merge_lists(images)),
            "match_status": "matched" if len(source_ids) > 1 else "singleton",
            "match_confidence": float(comp["confidence"]),
            "match_method": comp["method"],
            "match_note": comp.get("note"),
            "source_ids": source_ids
        })

        _attach_rooms(cid, source_ids)
        _attach_near_misses(cid, source_ids)

    flush_cache()

    # ── Write to SQLite ────────────────────────────────────────────────────────
    _write_db(
        db_path,
        hotel_dfs, room_dfs,
        canonical_hotels, canonical_rooms, near_miss_rows,
    )

    # ── Write JSON artifact ────────────────────────────────────────────────────
    _write_json(json_path, canonical_hotels, canonical_rooms, near_miss_rows)

    return len(canonical_hotels), len(canonical_rooms), len(near_miss_rows)


# ──────────────────────────────────────────────────────────────────────────────
# Persistence helpers
# ──────────────────────────────────────────────────────────────────────────────

def _write_db(
    db_path: Path,
    hotel_dfs: dict[str, pd.DataFrame],
    room_dfs: dict[str, pd.DataFrame],
    canonical_hotels: list[dict],
    canonical_rooms:  list[dict],
    near_miss_rows:   list[dict],
) -> None:
    db_path.unlink(missing_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(_DDL)

    # ── Raw supplier hotels ───────────────────────────────────────────────────
    raw_hotel_rows = []
    for supp, df in hotel_dfs.items():
        for _, r in df.iterrows():
            raw_hotel_rows.append((
                supp, r["id"], r["name"], r["address"],
                _safe_float(r["lat"]), _safe_float(r["lon"]),
                _safe_float(r.get("stars")),
                json.dumps(list(r["amenities"])),
                json.dumps(list(r["image_urls"])),
            ))
            
    con.executemany(
        "INSERT OR REPLACE INTO raw_hotels VALUES (?,?,?,?,?,?,?,?,?)",
        raw_hotel_rows,
    )

    # ── Raw supplier rooms ────────────────────────────────────────────────────
    raw_room_rows = []
    for supp, df in room_dfs.items():
        for _, r in df.iterrows():
            raw_room_rows.append((
                supp, r["room_id"], r["hotel_id"], r["name"], 
                json.dumps(list(r["amenities"]))
            ))
            
    con.executemany("INSERT OR REPLACE INTO raw_rooms VALUES (?,?,?,?,?)", raw_room_rows)

    # ── Canonical hotels ──────────────────────────────────────────────────────
    hotel_rows = [
        (
            h["id"], h["name"], h["address"],
            h["lat"], h["lon"], h["stars"],
            json.dumps(h["amenities"]),
            json.dumps(h["image_urls"]),
            h["match_status"], h["match_confidence"], h["match_method"], h.get("match_note"),
            json.dumps(h["source_ids"]),
        )
        for h in canonical_hotels
    ]
    con.executemany(
        "INSERT INTO canonical_hotels VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        hotel_rows,
    )

    # ── FTS index ─────────────────────────────────────────────────────────────
    fts_rows = [(h["id"], h["name"], h["address"]) for h in canonical_hotels]
    con.executemany("INSERT INTO hotels_fts(id, name, address) VALUES (?,?,?)", fts_rows)

    # ── Canonical rooms ───────────────────────────────────────────────────────
    room_rows = [
        (
            r["id"], r["canonical_hotel_id"], r["name"],
            r["bed_type"], r["occupancy"], r["meal_plan"],
            r["view"], r["is_smoking"],
            json.dumps(r["amenities"]),
            r["match_status"], r["match_confidence"],
            json.dumps(r["source_room_ids"]),
            json.dumps(r["source_names"]),
        )
        for r in canonical_rooms
    ]
    con.executemany(
        "INSERT INTO canonical_rooms VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        room_rows,
    )

    # ── Near-misses ───────────────────────────────────────────────────────────
    nm_rows = [
        (
            n["canonical_hotel_id"], n["candidate_supplier"], n["candidate_id"],
            n["confidence"], n["geo_score"], n["name_score"],
        )
        for n in near_miss_rows
    ]
    con.executemany("INSERT INTO near_misses VALUES (?,?,?,?,?,?)", nm_rows)

    con.commit()
    con.close()


def _write_json(
    json_path: Path,
    canonical_hotels: list[dict],
    canonical_rooms:  list[dict],
    near_miss_rows:   list[dict],
) -> None:
    rooms_by_hotel: dict[str, list[dict]] = {}
    for r in canonical_rooms:
        rooms_by_hotel.setdefault(r["canonical_hotel_id"], []).append(r)

    nm_by_hotel: dict[str, list[dict]] = {}
    for n in near_miss_rows:
        nm_by_hotel.setdefault(n["canonical_hotel_id"], []).append(n)

    output = []
    for h in canonical_hotels:
        entry = dict(h)
        entry["rooms"]      = rooms_by_hotel.get(h["id"], [])
        entry["near_misses"] = nm_by_hotel.get(h["id"], [])
        output.append(entry)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
