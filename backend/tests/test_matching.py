"""Unit tests for hotel matching guard-rails and room attribute extraction."""

import pandas as pd
import pytest

from pipeline.match_hotels import (
    MATCH_THRESHOLD,
    _geo_score,
    _haversine,
    _name_score,
    _prop_numbers,
    _stars_score,
    match_hotels,
)
from pipeline.match_rooms import (
    _normalize_room_name,
    extract_attrs,
    extract_occupancy,
    match_rooms_for_hotel,
)


# ──────────────────────────────────────────────────────────────────────────────
# Hotel matching primitives
# ──────────────────────────────────────────────────────────────────────────────

def test_haversine_zero_distance():
    assert _haversine(12.97, 77.59, 12.97, 77.59) == 0.0


def test_haversine_known_distance():
    # ~1 degree latitude ≈ 111 km
    d = _haversine(12.0, 77.0, 13.0, 77.0)
    assert 110 < d < 112


def test_geo_score_half_life():
    assert _geo_score(0.0) == 1.0
    assert abs(_geo_score(0.15) - 0.5) < 1e-9


def test_name_score_brand_prefix_stripped():
    # OYO prefix should not depress similarity
    assert _name_score("OYO 123 Grand Palace", "Grand Palace") > 0.9


def test_stars_score():
    assert _stars_score(3, 3) == 1.0
    assert _stars_score(3, 4) == 0.5
    assert _stars_score(None, 3) == 0.0


def test_prop_numbers():
    assert _prop_numbers("OYO 16455 Amazing Inn") == {"16455"}
    assert _prop_numbers("No numbers here") == set()


# ──────────────────────────────────────────────────────────────────────────────
# Hotel matching end-to-end guard-rails
# ──────────────────────────────────────────────────────────────────────────────

def _hotel_df(rows):
    return pd.DataFrame(rows, columns=["id", "name", "address", "lat", "lon", "stars", "amenities", "image_urls"])


def test_exact_pair_matches():
    df_a = _hotel_df([("A-1", "Hotel Crystal Castle", "addr", 12.903, 77.585, 3.0, [], [])])
    df_b = _hotel_df([("B-1", "Hotel Crystal Castle", "addr", 12.903, 77.585, 3.0, [], [])])
    matches, _ = match_hotels(df_a, df_b)
    assert len(matches) == 1
    assert matches.iloc[0]["confidence"] >= 0.99


def test_geo_only_pair_rejected():
    """Same coordinates + same stars but totally different names must NOT match."""
    df_a = _hotel_df([("A-1", "Ashwa Comfort", "addr", 12.903, 77.585, 3.0, [], [])])
    df_b = _hotel_df([("B-1", "Zenith Plaza Retreat", "addr", 12.903, 77.585, 3.0, [], [])])
    matches, near = match_hotels(df_a, df_b)
    assert len(matches) == 0
    assert len(near) == 1  # kept as a near-miss for review


def test_property_number_veto():
    """Different OYO property numbers at same location must NOT match."""
    df_a = _hotel_df([("A-1", "OYO 16455 Amazing Inn", "addr", 12.903, 77.585, 2.0, [], [])])
    df_b = _hotel_df([("B-1", "OYO 436 Emirates Suites", "addr", 12.903, 77.585, 2.0, [], [])])
    matches, _ = match_hotels(df_a, df_b)
    assert len(matches) == 0


def test_rescue_pass_catches_distant_identical_names():
    """Identical names ~600m apart (beyond 350m cutoff) should be rescued."""
    df_a = _hotel_df([("A-1", "The Grand Magnolia Residency", "addr", 12.9000, 77.5850, 3.0, [], [])])
    df_b = _hotel_df([("B-1", "The Grand Magnolia Residency", "addr", 12.9055, 77.5850, 3.0, [], [])])
    matches, _ = match_hotels(df_a, df_b)
    assert len(matches) == 1
    # Rescue confidence is name-driven and should still clear the threshold
    assert matches.iloc[0]["confidence"] >= MATCH_THRESHOLD


def test_match_method_tagged_geo_fuzzy_vs_rescue():
    """Matches from the main geo-blocked pass and the rescue pass must be
    distinguishable — the API surfaces this as match_method."""
    df_a = _hotel_df(
        [
            ("A-1", "Hotel Crystal Castle", "addr", 12.903, 77.585, 3.0, [], []),
            ("A-2", "The Grand Magnolia Residency", "addr", 12.9000, 77.5850, 3.0, [], []),
        ]
    )
    df_b = _hotel_df(
        [
            ("B-1", "Hotel Crystal Castle", "addr", 12.903, 77.585, 3.0, [], []),
            ("B-2", "The Grand Magnolia Residency", "addr", 12.9055, 77.5850, 3.0, [], []),
        ]
    )
    matches, _ = match_hotels(df_a, df_b)
    methods = dict(zip(matches["a_id"], matches["method"]))
    assert methods["A-1"] == "geo_fuzzy"
    assert methods["A-2"] == "rescue"


def test_one_to_one_assignment():
    """Two A hotels near one B hotel: only the better pair wins."""
    df_a = _hotel_df([
        ("A-1", "Sunrise Residency", "addr", 12.9030, 77.5850, 3.0, [], []),
        ("A-2", "Sunrise Residency Annex", "addr", 12.9031, 77.5851, 3.0, [], []),
    ])
    df_b = _hotel_df([("B-1", "Sunrise Residency", "addr", 12.9030, 77.5850, 3.0, [], [])])
    matches, _ = match_hotels(df_a, df_b)
    assert len(matches) == 1
    assert matches.iloc[0]["a_id"] == "A-1"


# ──────────────────────────────────────────────────────────────────────────────
# Room attribute extraction
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("Deluxe King Room", "King"),
    ("Queen Suite", "Queen"),
    ("Twin Deluxe Room w/ Breakfast", "Twin"),
    ("Deluxe, 3 Bed", "Multiple Beds"),
    ("Apartment, 2 Bedroom", "Multiple Beds"),
    ("One, 1 Bed", "Double"),
    ("Standard Room", None),          # no bed info → honest None
    ("Executive Suite", None),        # Suite is NOT a bed type
])
def test_bed_type_extraction(name, expected):
    assert extract_attrs(name)["bed_type"] == expected


def test_bed_type_from_amenities():
    # Supplier A buries bed info in amenities
    attrs = extract_attrs("Deluxe AC", ["Queen Bed", "196 sq.ft", "3 Adults"])
    assert attrs["bed_type"] == "Queen"


@pytest.mark.parametrize("name,expected", [
    ("Deluxe Room with Breakfast", "Breakfast"),
    ("Room w/ Breakfast", "Breakfast"),
    ("Standard Half Board", "Half Board"),
    ("All Inclusive Suite", "Full Board"),
    ("Standard Room", "Room Only"),
])
def test_meal_plan_extraction(name, expected):
    assert extract_attrs(name)["meal_plan"] == expected


@pytest.mark.parametrize("name,amenities,expected", [
    ("Deluxe", ["3 Adults"], "Triple"),
    ("Room for 2 Guests", [], "Double"),
    ("Single Room", [], "Single"),
    ("Family Room", [], "Family"),
    ("Deluxe King", [], "Double"),   # King implies 2
    ("Plain Room", [], None),
])
def test_occupancy_extraction(name, amenities, expected):
    assert extract_occupancy(name, amenities) == expected


def test_smoking_extraction():
    assert extract_attrs("Deluxe Non-Smoking")["is_smoking"] is False
    assert extract_attrs("Deluxe Room, Smoking Allowed")["is_smoking"] is True
    assert extract_attrs("Deluxe Room")["is_smoking"] is None


def test_view_extraction():
    assert extract_attrs("Deluxe City View")["view"] == "City"
    assert extract_attrs("Pool View Suite")["view"] == "Pool"


def test_normalize_room_name_expansions():
    assert "with breakfast" in _normalize_room_name("Deluxe w/ Breakfast")
    assert _normalize_room_name("Deluxe, Twin!") == "deluxe twin"


# ──────────────────────────────────────────────────────────────────────────────
# Room matching
# ──────────────────────────────────────────────────────────────────────────────

def _rooms_df(rows):
    return pd.DataFrame(rows, columns=["hotel_id", "room_id", "name", "amenities"])


def test_room_match_basic():
    ra = _rooms_df([("H1", "RA1", "Deluxe, Twin", [])])
    rb = _rooms_df([("H1", "RB1", "Twin Deluxe Room w/ Breakfast", [])])
    matched, ua, ub = match_rooms_for_hotel(ra, rb)
    assert len(matched) == 1
    assert not ua and not ub


def test_room_bed_conflict_veto():
    """'Deluxe King' must never match 'Deluxe Twin' despite similar names."""
    ra = _rooms_df([("H1", "RA1", "Deluxe King Room", [])])
    rb = _rooms_df([("H1", "RB1", "Deluxe Twin Room", [])])
    matched, ua, ub = match_rooms_for_hotel(ra, rb)
    assert len(matched) == 0
    assert ua == ["RA1"] and ub == ["RB1"]


def test_room_unmatched_stays_unmatched():
    ra = _rooms_df([("H1", "RA1", "Presidential Villa", [])])
    rb = _rooms_df([("H1", "RB1", "Budget Dorm Bed", [])])
    matched, ua, ub = match_rooms_for_hotel(ra, rb)
    assert len(matched) == 0
    assert ua == ["RA1"] and ub == ["RB1"]


def test_room_empty_sides():
    empty = _rooms_df([])
    rb = _rooms_df([("H1", "RB1", "Deluxe", [])])
    matched, ua, ub = match_rooms_for_hotel(empty, rb)
    assert matched == [] and ua == [] and ub == ["RB1"]
