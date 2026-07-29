"""
Tests for canonical merge/build logic — especially near-miss provenance,
which used to be silently dropped for a_only/b_only hotels (near-misses
were only ever attached to hotels that ended up matched).
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


def _empty_matches():
    return pd.DataFrame(
        columns=["a_id", "b_id", "confidence", "geo_score", "name_score", "stars_score", "dist_km", "method"]
    )


def test_near_miss_attached_to_a_only_hotel(tmp_path):
    """A hotel that almost matched but didn't (a_only) must still surface its
    near-miss candidate to the API — this is exactly the case a reviewer
    most wants to see, and it used to be dropped entirely."""
    df_a = _hotel_df([("A-1", "Ashwa Comfort", "addr", 12.903, 77.585, 3.0, [], [])])
    df_b = _hotel_df([("B-1", "Something Else Entirely", "addr", 12.903, 77.585, 3.0, [], [])])
    near_misses_df = pd.DataFrame(
        [{"a_id": "A-1", "b_id": "B-1", "confidence": 0.45, "geo_score": 1.0, "name_score": 0.1}]
    )
    rooms_empty = _rooms_df([])

    db_path, json_path = tmp_path / "test.db", tmp_path / "test.json"
    build_canonical(
        df_a, df_b, _empty_matches(), near_misses_df, rooms_empty, rooms_empty,
        db_path=db_path, json_path=json_path,
    )

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    hotel = con.execute("SELECT * FROM canonical_hotels WHERE match_status='a_only'").fetchone()
    assert hotel is not None
    nm = con.execute(
        "SELECT * FROM near_misses WHERE canonical_hotel_id=?", (hotel["id"],)
    ).fetchall()
    assert len(nm) == 1
    assert nm[0]["candidate_supplier"] == "b"
    assert nm[0]["candidate_id"] == "B-1"
    con.close()


def test_near_miss_attached_to_b_only_hotel(tmp_path):
    """Symmetric case: a b_only hotel's near-miss A candidate must also show up."""
    df_a = _hotel_df([("A-1", "Something Else Entirely", "addr", 12.903, 77.585, 3.0, [], [])])
    df_b = _hotel_df([("B-1", "Ashwa Comfort", "addr", 12.903, 77.585, 3.0, [], [])])
    near_misses_df = pd.DataFrame(
        [{"a_id": "A-1", "b_id": "B-1", "confidence": 0.45, "geo_score": 1.0, "name_score": 0.1}]
    )
    rooms_empty = _rooms_df([])

    db_path, json_path = tmp_path / "test.db", tmp_path / "test.json"
    build_canonical(
        df_a, df_b, _empty_matches(), near_misses_df, rooms_empty, rooms_empty,
        db_path=db_path, json_path=json_path,
    )

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    hotel = con.execute("SELECT * FROM canonical_hotels WHERE match_status='b_only'").fetchone()
    assert hotel is not None
    nm = con.execute(
        "SELECT * FROM near_misses WHERE canonical_hotel_id=?", (hotel["id"],)
    ).fetchall()
    assert len(nm) == 1
    assert nm[0]["candidate_supplier"] == "a"
    assert nm[0]["candidate_id"] == "A-1"
    con.close()


def test_matched_hotel_carries_method_and_llm_note(tmp_path):
    """LLM-adjudicated matches must be distinguishable from heuristic matches,
    with the model's rationale preserved for a reviewer to audit."""
    df_a = _hotel_df([("A-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], [])])
    df_b = _hotel_df([("B-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], [])])
    matches_df = pd.DataFrame(
        [
            {
                "a_id": "A-1", "b_id": "B-1", "confidence": 0.8,
                "geo_score": 1.0, "name_score": 0.5, "stars_score": 1.0, "dist_km": 0.0,
                "method": "llm", "llm_reason": "same brand, renamed",
            }
        ]
    )
    rooms_empty = _rooms_df([])

    db_path, json_path = tmp_path / "test.db", tmp_path / "test.json"
    build_canonical(
        df_a, df_b, matches_df, pd.DataFrame(), rooms_empty, rooms_empty,
        db_path=db_path, json_path=json_path,
    )

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    hotel = con.execute("SELECT * FROM canonical_hotels WHERE match_status='matched'").fetchone()
    assert hotel["match_method"] == "llm"
    assert hotel["match_note"] == "same brand, renamed"
    con.close()


def test_geo_fuzzy_match_has_no_note(tmp_path):
    """Ordinary heuristic matches must not carry a spurious LLM note."""
    df_a = _hotel_df([("A-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], [])])
    df_b = _hotel_df([("B-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], [])])
    matches_df = pd.DataFrame(
        [
            {
                "a_id": "A-1", "b_id": "B-1", "confidence": 0.99,
                "geo_score": 1.0, "name_score": 1.0, "stars_score": 1.0, "dist_km": 0.0,
                "method": "geo_fuzzy",
            }
        ]
    )
    rooms_empty = _rooms_df([])

    db_path, json_path = tmp_path / "test.db", tmp_path / "test.json"
    build_canonical(
        df_a, df_b, matches_df, pd.DataFrame(), rooms_empty, rooms_empty,
        db_path=db_path, json_path=json_path,
    )

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    hotel = con.execute("SELECT * FROM canonical_hotels WHERE match_status='matched'").fetchone()
    assert hotel["match_method"] == "geo_fuzzy"
    assert hotel["match_note"] is None
    con.close()
