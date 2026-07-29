"""
SQLite query helpers for the canonical hotels API.

All queries read from canonical.db (written by the pipeline).
Connections are opened per-request via FastAPI dependency injection.
"""

import json
import os
import sqlite3
from pathlib import Path
from typing import Generator

# Overridable so a production deployment can point at a DB built/mounted
# elsewhere without editing source (e.g. a read replica volume).
DB_PATH = Path(os.environ.get("CANONICAL_DB_PATH", "")) if os.environ.get("CANONICAL_DB_PATH") else (
    Path(__file__).parent.parent / "canonical.db"
)


# ──────────────────────────────────────────────────────────────────────────────
# Connection lifecycle (FastAPI dependency)
# ──────────────────────────────────────────────────────────────────────────────

def get_db() -> Generator[sqlite3.Connection, None, None]:
    """
    Yield a read-only SQLite connection with row_factory set.

    Opened with mode=ro so a missing database raises immediately (503 at the
    API layer) instead of silently creating an empty file, and so the API
    can never mutate the canonical artifact.
    """
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    except sqlite3.OperationalError as exc:
        from fastapi import HTTPException  # local import to keep db.py framework-light

        raise HTTPException(
            status_code=503,
            detail="canonical.db not found — run `python -m pipeline.run` first",
        ) from exc
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


# ──────────────────────────────────────────────────────────────────────────────
# Internal row parsers
# ──────────────────────────────────────────────────────────────────────────────

def _parse_hotel_row(row: sqlite3.Row) -> dict:
    """Convert a canonical_hotels row to a plain dict with parsed JSON fields."""
    d = dict(row)
    d["amenities"]  = json.loads(d.get("amenities") or "[]")
    d["image_urls"] = json.loads(d.get("image_urls") or "[]")
    return d


def _parse_raw_hotel_row(row: sqlite3.Row | None) -> dict | None:
    """Convert a raw_hotels_a/b row to a plain dict."""
    if row is None:
        return None
    d = dict(row)
    d["amenities"]  = json.loads(d.get("amenities") or "[]")
    d["image_urls"] = json.loads(d.get("image_urls") or "[]")
    return d


def _parse_room_row(row: sqlite3.Row) -> dict:
    """Convert a canonical_rooms row to a plain dict."""
    d = dict(row)
    d["amenities"] = json.loads(d.get("amenities") or "[]")
    # SQLite stores NULL / 0 / 1 for is_smoking; convert to bool | None
    sm = d.get("is_smoking")
    d["is_smoking"] = None if sm is None else bool(sm)
    return d


def _parse_raw_room_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["amenities"] = json.loads(d.get("amenities") or "[]")
    return d


# ──────────────────────────────────────────────────────────────────────────────
# Search helpers
# ──────────────────────────────────────────────────────────────────────────────

def _fts_query(raw: str) -> str:
    """
    Convert a free-text query into a safe FTS5 MATCH expression.

    Strategy: wrap each token in double-quotes (escaping existing quotes)
    and append '*' for prefix matching so partial names work.
    """
    tokens = raw.strip().split()
    if not tokens:
        return '""'
    safe_tokens = ['"' + t.replace('"', '""') + '"*' for t in tokens]
    return " ".join(safe_tokens)


# ──────────────────────────────────────────────────────────────────────────────
# Query functions
# ──────────────────────────────────────────────────────────────────────────────

def search_hotels(
    con: sqlite3.Connection,
    search: str,
    limit: int,
    offset: int,
    match_status: str | None = None,
) -> tuple[int, list[dict]]:
    """
    Full-text search (FTS5) over canonical hotel names + addresses.
    Falls back to LIKE if the FTS index fails (e.g. empty query).

    Returns (total_count, list_of_hotel_dicts).
    """
    status_clause = ""
    status_params: tuple = ()
    if match_status:
        status_clause = "AND ch.match_status = ?"
        status_params = (match_status,)

    if search.strip():
        fts_expr = _fts_query(search)
        try:
            count_row = con.execute(
                f"""
                SELECT COUNT(*) FROM hotels_fts fts
                JOIN canonical_hotels ch ON fts.id = ch.id
                WHERE hotels_fts MATCH ? {status_clause}
                """,
                (fts_expr,) + status_params,
            ).fetchone()
            total = count_row[0]

            rows = con.execute(
                f"""
                SELECT ch.* FROM hotels_fts fts
                JOIN canonical_hotels ch ON fts.id = ch.id
                WHERE hotels_fts MATCH ? {status_clause}
                ORDER BY rank
                LIMIT ? OFFSET ?
                """,
                (fts_expr,) + status_params + (limit, offset),
            ).fetchall()
        except sqlite3.OperationalError:
            # Malformed FTS query — fall back to LIKE
            like_val = f"%{search}%"
            count_row = con.execute(
                f"""
                SELECT COUNT(*) FROM canonical_hotels ch
                WHERE (ch.name LIKE ? OR ch.address LIKE ?) {status_clause}
                """,
                (like_val, like_val) + status_params,
            ).fetchone()
            total = count_row[0]

            rows = con.execute(
                f"""
                SELECT * FROM canonical_hotels ch
                WHERE (ch.name LIKE ? OR ch.address LIKE ?) {status_clause}
                ORDER BY ch.name
                LIMIT ? OFFSET ?
                """,
                (like_val, like_val) + status_params + (limit, offset),
            ).fetchall()
    else:
        # No search query — return all, newest canonical IDs last
        count_row = con.execute(
            f"SELECT COUNT(*) FROM canonical_hotels ch WHERE 1=1 {status_clause}",
            status_params,
        ).fetchone()
        total = count_row[0]

        rows = con.execute(
            f"""
            SELECT * FROM canonical_hotels ch
            WHERE 1=1 {status_clause}
            ORDER BY ch.id
            LIMIT ? OFFSET ?
            """,
            status_params + (limit, offset),
        ).fetchall()

    return total, [_parse_hotel_row(r) for r in rows]


def get_hotel_by_id(con: sqlite3.Connection, hotel_id: str) -> dict | None:
    """Fetch a single canonical hotel row; return None if not found."""
    row = con.execute(
        "SELECT * FROM canonical_hotels WHERE id = ?", (hotel_id,)
    ).fetchone()
    if row is None:
        return None
    return _parse_hotel_row(row)


def get_raw_hotel(con: sqlite3.Connection, supplier: str, supplier_id: str) -> dict | None:
    """Fetch a verbatim supplier hotel record (supplier = 'a' or 'b')."""
    table = "raw_hotels_a" if supplier == "a" else "raw_hotels_b"
    row = con.execute(f"SELECT * FROM {table} WHERE id = ?", (supplier_id,)).fetchone()
    return _parse_raw_hotel_row(row)


def get_rooms_for_hotel(con: sqlite3.Connection, hotel_id: str) -> list[dict]:
    """Fetch all canonical rooms for a hotel, including raw room info."""
    rows = con.execute(
        "SELECT * FROM canonical_rooms WHERE canonical_hotel_id = ? ORDER BY id",
        (hotel_id,),
    ).fetchall()
    if not rows:
        return []

    # Fetch raw room records in bulk for this hotel
    room_a_ids = [r["room_a_id"] for r in rows if r["room_a_id"]]
    room_b_ids = [r["room_b_id"] for r in rows if r["room_b_id"]]

    raw_a: dict[str, dict] = {}
    if room_a_ids:
        placeholders = ",".join("?" * len(room_a_ids))
        for rr in con.execute(
            f"SELECT * FROM raw_rooms_a WHERE room_id IN ({placeholders})", room_a_ids
        ).fetchall():
            raw_a[rr["room_id"]] = _parse_raw_room_row(rr)

    raw_b: dict[str, dict] = {}
    if room_b_ids:
        placeholders = ",".join("?" * len(room_b_ids))
        for rr in con.execute(
            f"SELECT * FROM raw_rooms_b WHERE room_id IN ({placeholders})", room_b_ids
        ).fetchall():
            raw_b[rr["room_id"]] = _parse_raw_room_row(rr)

    result = []
    for row in rows:
        d = _parse_room_row(row)
        d["supplier_a_room"] = raw_a.get(d.get("room_a_id")) if d.get("room_a_id") else None
        d["supplier_b_room"] = raw_b.get(d.get("room_b_id")) if d.get("room_b_id") else None
        result.append(d)

    return result


def get_near_misses_for_hotel(con: sqlite3.Connection, hotel_id: str) -> list[dict]:
    """
    Fetch sub-threshold candidates for a canonical hotel, enriched with the
    candidate's name and address. Candidates can come from either supplier:
    an A-based hotel (matched or a_only) has near-miss B candidates, and a
    b_only hotel has near-miss A candidates.
    """
    rows = con.execute(
        """
        SELECT candidate_supplier, candidate_id, confidence, geo_score, name_score
        FROM near_misses
        WHERE canonical_hotel_id = ?
        ORDER BY confidence DESC
        LIMIT 10
        """,
        (hotel_id,),
    ).fetchall()
    if not rows:
        return []

    a_ids = [r["candidate_id"] for r in rows if r["candidate_supplier"] == "a"]
    b_ids = [r["candidate_id"] for r in rows if r["candidate_supplier"] == "b"]

    info_a: dict[str, sqlite3.Row] = {}
    if a_ids:
        placeholders = ",".join("?" * len(a_ids))
        for rr in con.execute(
            f"SELECT id, name, address FROM raw_hotels_a WHERE id IN ({placeholders})", a_ids
        ).fetchall():
            info_a[rr["id"]] = rr

    info_b: dict[str, sqlite3.Row] = {}
    if b_ids:
        placeholders = ",".join("?" * len(b_ids))
        for rr in con.execute(
            f"SELECT id, name, address FROM raw_hotels_b WHERE id IN ({placeholders})", b_ids
        ).fetchall():
            info_b[rr["id"]] = rr

    result = []
    for r in rows:
        lookup = info_a if r["candidate_supplier"] == "a" else info_b
        info = lookup.get(r["candidate_id"])
        result.append(
            {
                "supplier":    r["candidate_supplier"],
                "supplier_id": r["candidate_id"],
                "name":        info["name"] if info else "",
                "address":     info["address"] if info else "",
                "confidence":  r["confidence"],
                "geo_score":   r["geo_score"],
                "name_score":  r["name_score"],
            }
        )
    return result
