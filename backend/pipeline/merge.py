"""
Build canonical hotel + room records and persist to SQLite + JSON.

Schema overview
---------------
canonical_hotels  — one row per real-world hotel
canonical_rooms   — one row per canonical room (may span both suppliers)
near_misses       — sub-threshold hotel candidates, keyed by canonical_hotel_id
raw_hotels_a/b    — verbatim supplier records (provenance)
raw_rooms_a/b     — verbatim room records
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

def _pick_name(name_a: str, name_b: str) -> str:
    """Return whichever name is longer (usually more descriptive)."""
    a = (name_a or "").strip()
    b = (name_b or "").strip()
    if not a:
        return b
    if not b:
        return a
    return a if len(a) >= len(b) else b


def _merge_list(list_a: list, list_b: list) -> list:
    """Union two lists, deduplicating by lowercase string value."""
    seen: set[str] = set()
    result: list = []
    for item in list(list_a or []) + list(list_b or []):
        key = str(item).lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _safe_avg(a, b):
    """Average two values; handle NaN / None gracefully."""
    def _ok(v):
        try:
            return v is not None and not math.isnan(float(v))
        except (TypeError, ValueError):
            return False

    if _ok(a) and _ok(b):
        return round((float(a) + float(b)) / 2, 1)
    if _ok(a):
        return round(float(a), 1)
    if _ok(b):
        return round(float(b), 1)
    return None


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

CREATE TABLE IF NOT EXISTS raw_hotels_a (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    address     TEXT,
    lat         REAL,
    lon         REAL,
    stars       REAL,
    amenities   TEXT,   -- JSON array
    image_urls  TEXT    -- JSON array
);

CREATE TABLE IF NOT EXISTS raw_hotels_b (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    address     TEXT,
    lat         REAL,
    lon         REAL,
    stars       REAL,
    amenities   TEXT,
    image_urls  TEXT
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
    match_status    TEXT NOT NULL,   -- 'matched' | 'a_only' | 'b_only'
    match_confidence REAL NOT NULL,
    match_method    TEXT NOT NULL,   -- 'geo_fuzzy' | 'rescue' | 'llm' | 'singleton'
    match_note      TEXT,            -- LLM adjudication rationale, when match_method='llm'
    supplier_a_id   TEXT,
    supplier_b_id   TEXT
);

CREATE TABLE IF NOT EXISTS raw_rooms_a (
    room_id     TEXT PRIMARY KEY,
    hotel_id    TEXT,
    name        TEXT,
    amenities   TEXT    -- JSON array
);

CREATE TABLE IF NOT EXISTS raw_rooms_b (
    room_id     TEXT PRIMARY KEY,
    hotel_id    TEXT,
    name        TEXT,
    amenities   TEXT
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
    match_status         TEXT NOT NULL,   -- 'matched' | 'a_only' | 'b_only'
    match_confidence     REAL NOT NULL,
    room_a_id            TEXT,
    room_b_id            TEXT,
    name_a               TEXT,
    name_b               TEXT
);

CREATE TABLE IF NOT EXISTS near_misses (
    canonical_hotel_id  TEXT NOT NULL,
    candidate_supplier  TEXT NOT NULL,   -- 'a' | 'b' — which supplier the candidate belongs to
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
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    matches_df: pd.DataFrame,
    near_misses_df: pd.DataFrame,
    rooms_a_df: pd.DataFrame,
    rooms_b_df: pd.DataFrame,
    db_path: Path = DB_PATH,
    json_path: Path = JSON_PATH,
) -> tuple[int, int, int]:
    """
    Build canonical records and write to SQLite + JSON.

    Returns (n_hotels, n_rooms, n_near_misses).
    """
    # Index raw data for O(1) lookups
    hotels_a: dict = {row["id"]: row for _, row in df_a.iterrows()}
    hotels_b: dict = {row["id"]: row for _, row in df_b.iterrows()}

    # Group rooms by hotel_id
    rooms_a_by_hotel: dict[str, pd.DataFrame] = {}
    for hid, grp in rooms_a_df.groupby("hotel_id"):
        rooms_a_by_hotel[hid] = grp.reset_index(drop=True)

    rooms_b_by_hotel: dict[str, pd.DataFrame] = {}
    for hid, grp in rooms_b_df.groupby("hotel_id"):
        rooms_b_by_hotel[hid] = grp.reset_index(drop=True)

    matched_a_ids: set[str] = set()
    matched_b_ids: set[str] = set()
    if not matches_df.empty:
        matched_a_ids = set(matches_df["a_id"])
        matched_b_ids = set(matches_df["b_id"])

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

    # ── Helper: build one canonical room row ──────────────────────────────────
    def _make_room(
        cid: str,
        ra_row,  # Series or None
        rb_row,  # Series or None
        confidence: float,
        status: str,
    ) -> dict:
        name_a = ra_row["name"] if ra_row is not None else ""
        name_b = rb_row["name"] if rb_row is not None else ""
        canon_name = _pick_name(name_a, name_b)

        am_a = list(ra_row["amenities"]) if ra_row is not None else []
        am_b = list(rb_row["amenities"]) if rb_row is not None else []
        merged_am = _merge_list(am_a, am_b)

        attrs = extract_attrs(canon_name, merged_am)
        occ   = extract_occupancy(canon_name, merged_am)

        is_sm = attrs["is_smoking"]
        is_sm_int = None if is_sm is None else int(is_sm)

        return {
            "id":                   next_room_id(),
            "canonical_hotel_id":   cid,
            "name":                 canon_name,
            "bed_type":             attrs["bed_type"],
            "occupancy":            occ,
            "meal_plan":            attrs["meal_plan"],
            "view":                 attrs["view"],
            "is_smoking":           is_sm_int,
            "amenities":            merged_am,
            "match_status":         status,
            "match_confidence":     confidence,
            "room_a_id":            ra_row["room_id"] if ra_row is not None else None,
            "room_b_id":            rb_row["room_id"] if rb_row is not None else None,
            "name_a":               name_a or None,
            "name_b":               name_b or None,
        }

    # ── Helper: attach rooms to a canonical hotel ─────────────────────────────
    def _attach_rooms(cid: str, a_id: str | None, b_id: str | None) -> None:
        r_a = rooms_a_by_hotel.get(a_id, pd.DataFrame()) if a_id else pd.DataFrame()
        r_b = rooms_b_by_hotel.get(b_id, pd.DataFrame()) if b_id else pd.DataFrame()

        matched_rooms, unmatched_a_ids, unmatched_b_ids = match_rooms_for_hotel(r_a, r_b)

        for mr in matched_rooms:
            ra_row = r_a[r_a["room_id"] == mr["room_a_id"]].iloc[0]
            rb_row = r_b[r_b["room_id"] == mr["room_b_id"]].iloc[0]
            canonical_rooms.append(_make_room(cid, ra_row, rb_row, mr["match_confidence"], "matched"))

        for rid in unmatched_a_ids:
            ra_row = r_a[r_a["room_id"] == rid].iloc[0]
            canonical_rooms.append(_make_room(cid, ra_row, None, 1.0, "a_only"))

        for rid in unmatched_b_ids:
            rb_row = r_b[r_b["room_id"] == rid].iloc[0]
            canonical_rooms.append(_make_room(cid, None, rb_row, 1.0, "b_only"))

    # ── Near-miss helper: works for either side, since the candidate list
    #    generated during the geo-blocked pass already carries both ids. ────────
    has_nm_cols = not near_misses_df.empty and {"a_id", "b_id"} <= set(near_misses_df.columns)

    def _attach_near_misses(cid: str, a_id: str | None, b_id: str | None) -> None:
        if not has_nm_cols:
            return
        if a_id is not None:
            nm_rows = near_misses_df[near_misses_df["a_id"] == a_id]
            candidate_col, candidate_supplier = "b_id", "b"
        elif b_id is not None:
            nm_rows = near_misses_df[near_misses_df["b_id"] == b_id]
            candidate_col, candidate_supplier = "a_id", "a"
        else:
            return
        for _, nm in nm_rows.iterrows():
            near_miss_rows.append(
                {
                    "canonical_hotel_id": cid,
                    "candidate_supplier": candidate_supplier,
                    "candidate_id":       nm[candidate_col],
                    "confidence":         float(nm["confidence"]),
                    "geo_score":          float(nm.get("geo_score", 0) or 0),
                    "name_score":         float(nm.get("name_score", 0) or 0),
                }
            )

    # ── 1. Matched hotel pairs ────────────────────────────────────────────────
    if not matches_df.empty:
        for _, match in matches_df.iterrows():
            a_id = match["a_id"]
            b_id = match["b_id"]
            ra   = hotels_a[a_id]
            rb   = hotels_b[b_id]
            cid  = next_hotel_id()

            canonical_hotels.append(
                {
                    "id":               cid,
                    "name":             _pick_name(str(ra["name"]), str(rb["name"])),
                    "address":          str(ra["address"]) if ra["address"] else str(rb["address"]),
                    "lat":              _safe_avg(ra["lat"], rb["lat"]),
                    "lon":              _safe_avg(ra["lon"], rb["lon"]),
                    "stars":            _safe_avg(ra.get("stars"), rb.get("stars")),
                    "amenities":        _merge_list(ra["amenities"], rb["amenities"]),
                    "image_urls":       dedupe_image_urls(_merge_list(ra["image_urls"], rb["image_urls"])),
                    "match_status":     "matched",
                    "match_confidence": float(match["confidence"]),
                    "match_method":     str(match.get("method") or "geo_fuzzy"),
                    "match_note":       (str(match["llm_reason"]) if match.get("llm_reason") else None),
                    "supplier_a_id":    a_id,
                    "supplier_b_id":    b_id,
                }
            )

            _attach_near_misses(cid, a_id, None)
            _attach_rooms(cid, a_id, b_id)

    # ── 2. A-only hotels ──────────────────────────────────────────────────────
    for a_id, ra in hotels_a.items():
        if a_id in matched_a_ids:
            continue
        cid = next_hotel_id()
        canonical_hotels.append(
            {
                "id":               cid,
                "name":             str(ra["name"]),
                "address":          str(ra["address"]),
                "lat":              _safe_float(ra["lat"]),
                "lon":              _safe_float(ra["lon"]),
                "stars":            _safe_float(ra.get("stars")),
                "amenities":        list(ra["amenities"]),
                "image_urls":       list(ra["image_urls"]),
                "match_status":     "a_only",
                "match_confidence": 1.0,
                "match_method":     "singleton",
                "match_note":       None,
                "supplier_a_id":    a_id,
                "supplier_b_id":    None,
            }
        )
        _attach_near_misses(cid, a_id, None)
        _attach_rooms(cid, a_id, None)

    # ── 3. B-only hotels ──────────────────────────────────────────────────────
    for b_id, rb in hotels_b.items():
        if b_id in matched_b_ids:
            continue
        cid = next_hotel_id()
        canonical_hotels.append(
            {
                "id":               cid,
                "name":             str(rb["name"]),
                "address":          str(rb["address"]),
                "lat":              _safe_float(rb["lat"]),
                "lon":              _safe_float(rb["lon"]),
                "stars":            _safe_float(rb.get("stars")),
                "amenities":        list(rb["amenities"]),
                "image_urls":       list(rb["image_urls"]),
                "match_status":     "b_only",
                "match_confidence": 1.0,
                "match_method":     "singleton",
                "match_note":       None,
                "supplier_a_id":    None,
                "supplier_b_id":    b_id,
            }
        )
        _attach_near_misses(cid, None, b_id)
        _attach_rooms(cid, None, b_id)

    flush_cache()

    # ── Write to SQLite ────────────────────────────────────────────────────────
    _write_db(
        db_path,
        df_a, df_b,
        rooms_a_df, rooms_b_df,
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
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    rooms_a_df: pd.DataFrame,
    rooms_b_df: pd.DataFrame,
    canonical_hotels: list[dict],
    canonical_rooms:  list[dict],
    near_miss_rows:   list[dict],
) -> None:
    db_path.unlink(missing_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(_DDL)

    # ── Raw supplier hotels ───────────────────────────────────────────────────
    def _hotel_rows(df: pd.DataFrame):
        for _, r in df.iterrows():
            yield (
                r["id"], r["name"], r["address"],
                _safe_float(r["lat"]), _safe_float(r["lon"]),
                _safe_float(r.get("stars")),
                json.dumps(list(r["amenities"])),
                json.dumps(list(r["image_urls"])),
            )

    con.executemany(
        "INSERT OR REPLACE INTO raw_hotels_a VALUES (?,?,?,?,?,?,?,?)",
        _hotel_rows(df_a),
    )
    con.executemany(
        "INSERT OR REPLACE INTO raw_hotels_b VALUES (?,?,?,?,?,?,?,?)",
        _hotel_rows(df_b),
    )

    # ── Raw supplier rooms ────────────────────────────────────────────────────
    def _room_rows(df: pd.DataFrame):
        for _, r in df.iterrows():
            yield (r["room_id"], r["hotel_id"], r["name"], json.dumps(list(r["amenities"])))

    con.executemany("INSERT OR REPLACE INTO raw_rooms_a VALUES (?,?,?,?)", _room_rows(rooms_a_df))
    con.executemany("INSERT OR REPLACE INTO raw_rooms_b VALUES (?,?,?,?)", _room_rows(rooms_b_df))

    # ── Canonical hotels ──────────────────────────────────────────────────────
    hotel_rows = [
        (
            h["id"], h["name"], h["address"],
            h["lat"], h["lon"], h["stars"],
            json.dumps(h["amenities"]),
            json.dumps(h["image_urls"]),
            h["match_status"], h["match_confidence"], h["match_method"], h.get("match_note"),
            h["supplier_a_id"], h["supplier_b_id"],
        )
        for h in canonical_hotels
    ]
    con.executemany(
        "INSERT INTO canonical_hotels VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
            r["room_a_id"], r["room_b_id"],
            r["name_a"], r["name_b"],
        )
        for r in canonical_rooms
    ]
    con.executemany(
        "INSERT INTO canonical_rooms VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
    """Write the canonical artifact JSON (hotels + rooms nested)."""
    # Index rooms and near-misses by hotel id
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
