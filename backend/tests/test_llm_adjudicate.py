"""
Tests for the optional LLM adjudication pass (pipeline/llm_adjudicate.py).

Two properties matter most here, more than the adjudication logic itself:
1. Without a key and without a cache, the pipeline must not touch the
   network and must degrade to a no-op (the $0 baseline is never broken).
2. A pre-populated cache must be used even with no key present — that's
   what makes a prior LLM-adjudicated run reproducible for a grader who
   doesn't have (and shouldn't need) anyone's API key.
"""

import pandas as pd
import pytest

from pipeline import llm_adjudicate as la


def _hotel_row(id_, name, address="addr", lat=12.9, lon=77.5, stars=3.0):
    return pd.Series({
        "id": id_, "name": name, "address": address, "lat": lat, "lon": lon,
        "stars": stars, "amenities": [], "image_urls": [],
    })


def _near_miss(a_id, b_id, geo_score, name_score, supplier_a="a", supplier_b="b"):
    return {
        "a_id": f"{supplier_a}::{a_id}", "b_id": f"{supplier_b}::{b_id}",
        "supplier_a": supplier_a, "supplier_b": supplier_b,
        "confidence": (geo_score + name_score) / 2,
        "geo_score": geo_score, "name_score": name_score,
        "stars_score": 1.0, "dist_km": 0.05,
    }


def test_select_hard_cases_filters_by_geo_and_name():
    df = pd.DataFrame(
        [
            _near_miss("A-1", "B-1", geo_score=0.9, name_score=0.5),   # keep: ambiguous + close
            _near_miss("A-2", "B-2", geo_score=0.9, name_score=0.1),   # drop: heuristic already confident it's different
            _near_miss("A-3", "B-3", geo_score=0.9, name_score=0.95),  # drop: veto escape hatch already resolves this
            _near_miss("A-4", "B-4", geo_score=0.1, name_score=0.5),   # drop: not geographically plausible
        ]
    )
    selected = la._select_hard_cases(df, matched_nodes=set())
    assert list(selected["a_id"]) == ["a::A-1"]


def test_select_hard_cases_excludes_already_claimed_hotels():
    """A hotel already matched by the heuristic pass must not be re-adjudicated."""
    df = pd.DataFrame([_near_miss("A-1", "B-1", geo_score=0.9, name_score=0.5)])
    assert la._select_hard_cases(df, matched_nodes={"a::A-1"}).empty
    assert la._select_hard_cases(df, matched_nodes={"b::B-1"}).empty


def test_select_hard_cases_caps_at_max_pairs():
    rows = [_near_miss(f"A-{i}", f"B-{i}", geo_score=0.9, name_score=0.5) for i in range(la.MAX_PAIRS + 50)]
    selected = la._select_hard_cases(pd.DataFrame(rows), matched_nodes=set())
    assert len(selected) == la.MAX_PAIRS


def test_adjudicate_skips_without_key_or_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    monkeypatch.setattr(la, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(la, "SPEND_LOG_PATH", tmp_path / "spend.json")

    hotels_indexed = {
        "a": {"A-1": _hotel_row("A-1", "Hotel X")},
        "b": {"B-1": _hotel_row("B-1", "Hotel Y")},
    }
    near_misses = pd.DataFrame([_near_miss("A-1", "B-1", geo_score=0.9, name_score=0.5)])

    matches_df, report = la.adjudicate_hard_cases(near_misses, hotels_indexed, set())

    assert matches_df.empty
    assert report["enabled"] is False
    assert report["pairs_called"] == 0
    assert not (tmp_path / "spend.json").exists()


def test_adjudicate_uses_cache_without_network(tmp_path, monkeypatch):
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        '{"a::A-1::b::B-1": {"same_hotel": true, "confidence": 0.8, "reason": "same brand, renamed"}}'
    )
    monkeypatch.setattr(la, "CACHE_PATH", cache_path)
    monkeypatch.setattr(la, "SPEND_LOG_PATH", tmp_path / "spend.json")

    hotels_indexed = {
        "a": {"A-1": _hotel_row("A-1", "Hotel X")},
        "b": {"B-1": _hotel_row("B-1", "Hotel X Grand")},
    }
    near_misses = pd.DataFrame([_near_miss("A-1", "B-1", geo_score=0.9, name_score=0.5)])

    matches_df, report = la.adjudicate_hard_cases(near_misses, hotels_indexed, set())

    assert len(matches_df) == 1
    row = matches_df.iloc[0]
    assert row["a_id"] == "a::A-1" and row["b_id"] == "b::B-1"
    assert row["method"] == "llm"
    assert row["confidence"] == pytest.approx(0.8)
    assert report["pairs_cached_hit"] == 1
    assert report["pairs_called"] == 0


def test_adjudicate_respects_same_hotel_false(tmp_path, monkeypatch):
    """A cached 'different hotel' verdict must never produce a match."""
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        '{"a::A-1::b::B-1": {"same_hotel": false, "confidence": 0.9, "reason": "different brands"}}'
    )
    monkeypatch.setattr(la, "CACHE_PATH", cache_path)
    monkeypatch.setattr(la, "SPEND_LOG_PATH", tmp_path / "spend.json")

    hotels_indexed = {
        "a": {"A-1": _hotel_row("A-1", "Hotel X")},
        "b": {"B-1": _hotel_row("B-1", "Hotel Y")},
    }
    near_misses = pd.DataFrame([_near_miss("A-1", "B-1", geo_score=0.9, name_score=0.5)])

    matches_df, report = la.adjudicate_hard_cases(near_misses, hotels_indexed, set())
    assert matches_df.empty
    assert report["pairs_cached_hit"] == 1
    assert report["new_matches"] == 0


def test_adjudicate_one_to_one_among_llm_matches(tmp_path, monkeypatch):
    """Two near-miss pairs both claiming the same B hotel: only the
    higher-confidence adjudication should win, mirroring the heuristic
    matcher's one-to-one assignment."""
    monkeypatch.delenv("CEREBRAS_API_KEY", raising=False)
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        '{'
        '"a::A-1::b::B-1": {"same_hotel": true, "confidence": 0.6, "reason": "plausible"},'
        '"a::A-2::b::B-1": {"same_hotel": true, "confidence": 0.9, "reason": "stronger match"}'
        "}"
    )
    monkeypatch.setattr(la, "CACHE_PATH", cache_path)
    monkeypatch.setattr(la, "SPEND_LOG_PATH", tmp_path / "spend.json")

    hotels_indexed = {
        "a": {
            "A-1": _hotel_row("A-1", "Hotel X"),
            "A-2": _hotel_row("A-2", "Hotel X Grand"),
        },
        "b": {"B-1": _hotel_row("B-1", "Hotel X")},
    }
    near_misses = pd.DataFrame(
        [
            _near_miss("A-1", "B-1", geo_score=0.9, name_score=0.5),
            _near_miss("A-2", "B-1", geo_score=0.9, name_score=0.6),
        ]
    )

    matches_df, _ = la.adjudicate_hard_cases(near_misses, hotels_indexed, set())
    assert len(matches_df) == 1
    assert matches_df.iloc[0]["a_id"] == "a::A-2"
