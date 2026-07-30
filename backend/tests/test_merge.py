"""
Tests for canonical merge/build logic — especially near-miss provenance,
which used to be silently dropped for singleton hotels (near-misses were
only ever attached to hotels that ended up matched).
"""

import sqlite3

import pandas as pd

from pipeline.merge import build_canonical


def _hotel_df(rows):
    return pd.DataFrame(
        rows, columns=["id", "name", "address", "lat", "lon", "stars", "amenities", "image_urls"]
    )


def _rooms_df(rows):
    return pd.DataFrame(rows, columns=["hotel_id", "room_id", "name", "amenities"])


def _empty_near_misses():
    return pd.DataFrame(
        columns=["a_id", "b_id", "supplier_a", "supplier_b", "confidence",
                 "geo_score", "name_score", "stars_score", "dist_km", "method"]
    )


def test_near_miss_attached_to_singleton_hotel(tmp_path):
    """A hotel that almost matched but didn't (singleton) must still surface
    its near-miss candidate to the API — this is exactly the case a
    reviewer most wants to see, and it used to be dropped entirely."""
    hotel_dfs = {
        "a": _hotel_df([("A-1", "Ashwa Comfort", "addr", 12.903, 77.585, 3.0, [], [])]),
        "b": _hotel_df([("B-1", "Something Else Entirely", "addr", 12.903, 77.585, 3.0, [], [])]),
    }
    room_dfs = {"a": _rooms_df([]), "b": _rooms_df([])}
    components = [
        {"nodes": [{"supplier": "a", "id": "A-1"}], "confidence": 1.0, "method": "singleton"},
        {"nodes": [{"supplier": "b", "id": "B-1"}], "confidence": 1.0, "method": "singleton"},
    ]
    near_misses_df = pd.DataFrame([{
        "a_id": "a::A-1", "b_id": "b::B-1", "supplier_a": "a", "supplier_b": "b",
        "confidence": 0.45, "geo_score": 1.0, "name_score": 0.1, "stars_score": 1.0, "dist_km": 0.0,
        "method": "geo_fuzzy",
    }])

    db_path, json_path = tmp_path / "test.db", tmp_path / "test.json"
    build_canonical(hotel_dfs, room_dfs, components, near_misses_df, db_path=db_path, json_path=json_path)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    hotel_a = con.execute(
        "SELECT * FROM canonical_hotels WHERE source_ids LIKE '%A-1%'"
    ).fetchone()
    assert hotel_a is not None
    assert hotel_a["match_status"] == "singleton"
    nm = con.execute(
        "SELECT * FROM near_misses WHERE canonical_hotel_id=?", (hotel_a["id"],)
    ).fetchall()
    assert len(nm) == 1
    assert nm[0]["candidate_supplier"] == "b"
    assert nm[0]["candidate_id"] == "B-1"
    con.close()


def test_matched_hotel_carries_method_and_llm_note(tmp_path):
    """LLM-adjudicated matches must be distinguishable from heuristic matches,
    with the model's rationale preserved for a reviewer to audit."""
    hotel_dfs = {
        "a": _hotel_df([("A-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], [])]),
        "b": _hotel_df([("B-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], [])]),
    }
    room_dfs = {"a": _rooms_df([]), "b": _rooms_df([])}
    components = [
        {
            "nodes": [{"supplier": "a", "id": "A-1"}, {"supplier": "b", "id": "B-1"}],
            "confidence": 0.8,
            "method": "llm",
            "note": "same brand, renamed",
        },
    ]

    db_path, json_path = tmp_path / "test.db", tmp_path / "test.json"
    build_canonical(hotel_dfs, room_dfs, components, _empty_near_misses(), db_path=db_path, json_path=json_path)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    hotel = con.execute("SELECT * FROM canonical_hotels WHERE match_status='matched'").fetchone()
    assert hotel["match_method"] == "llm"
    assert hotel["match_note"] == "same brand, renamed"
    con.close()


def test_geo_fuzzy_match_has_no_note(tmp_path):
    """Ordinary heuristic matches must not carry a spurious LLM note."""
    hotel_dfs = {
        "a": _hotel_df([("A-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], [])]),
        "b": _hotel_df([("B-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], [])]),
    }
    room_dfs = {"a": _rooms_df([]), "b": _rooms_df([])}
    components = [
        {
            "nodes": [{"supplier": "a", "id": "A-1"}, {"supplier": "b", "id": "B-1"}],
            "confidence": 0.99,
            "method": "geo_fuzzy",
        },
    ]

    db_path, json_path = tmp_path / "test.db", tmp_path / "test.json"
    build_canonical(hotel_dfs, room_dfs, components, _empty_near_misses(), db_path=db_path, json_path=json_path)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    hotel = con.execute("SELECT * FROM canonical_hotels WHERE match_status='matched'").fetchone()
    assert hotel["match_method"] == "geo_fuzzy"
    assert hotel["match_note"] is None
    con.close()


def test_rooms_matched_across_suppliers_within_cluster(tmp_path):
    """Rooms for a matched hotel pair must actually be cross-supplier
    matched, not dumped as independent singletons (a past regression)."""
    hotel_dfs = {
        "a": _hotel_df([("A-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], [])]),
        "b": _hotel_df([("B-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], [])]),
    }
    room_dfs = {
        "a": _rooms_df([("A-1", "RA1", "Deluxe King Room", [])]),
        "b": _rooms_df([("B-1", "RB1", "King Deluxe Room", [])]),
    }
    components = [
        {
            "nodes": [{"supplier": "a", "id": "A-1"}, {"supplier": "b", "id": "B-1"}],
            "confidence": 0.95,
            "method": "geo_fuzzy",
        },
    ]

    db_path, json_path = tmp_path / "test.db", tmp_path / "test.json"
    build_canonical(hotel_dfs, room_dfs, components, _empty_near_misses(), db_path=db_path, json_path=json_path)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rooms = con.execute("SELECT * FROM canonical_rooms").fetchall()
    assert len(rooms) == 1
    assert rooms[0]["match_status"] == "matched"
    con.close()
