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


def _hotel_df(rows):
    return pd.DataFrame(
        rows, columns=["id", "name", "address", "lat", "lon", "stars", "amenities", "image_urls"]
    )


def _near_miss(a_id, b_id, geo_score, name_score):
    return {
        "a_id": a_id, "b_id": b_id,
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
    selected = la._select_hard_cases(df, matched_a=set(), matched_b=set())
    assert list(selected["a_id"]) == ["A-1"]


def test_select_hard_cases_excludes_already_claimed_hotels():
    """A hotel already matched by the heuristic pass must not be re-adjudicated."""
    df = pd.DataFrame([_near_miss("A-1", "B-1", geo_score=0.9, name_score=0.5)])
    assert la._select_hard_cases(df, matched_a={"A-1"}, matched_b=set()).empty
    assert la._select_hard_cases(df, matched_a=set(), matched_b={"B-1"}).empty


def test_select_hard_cases_caps_at_max_pairs():
    rows = [_near_miss(f"A-{i}", f"B-{i}", geo_score=0.9, name_score=0.5) for i in range(la.MAX_PAIRS + 50)]
    selected = la._select_hard_cases(pd.DataFrame(rows), matched_a=set(), matched_b=set())
    assert len(selected) == la.MAX_PAIRS


def test_adjudicate_skips_without_key_or_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(la, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(la, "SPEND_LOG_PATH", tmp_path / "spend.json")

    df_a = _hotel_df([("A-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], [])])
    df_b = _hotel_df([("B-1", "Hotel Y", "addr", 12.9, 77.5, 3.0, [], [])])
    near_misses = pd.DataFrame([_near_miss("A-1", "B-1", geo_score=0.9, name_score=0.5)])

    matches_df, report = la.adjudicate_hard_cases(df_a, df_b, near_misses, set(), set())

    assert matches_df.empty
    assert report["enabled"] is False
    assert report["pairs_called"] == 0
    assert not (tmp_path / "spend.json").exists()


def test_adjudicate_uses_cache_without_network(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        '{"A-1::B-1": {"same_hotel": true, "confidence": 0.8, "reason": "same brand, renamed"}}'
    )
    monkeypatch.setattr(la, "CACHE_PATH", cache_path)
    monkeypatch.setattr(la, "SPEND_LOG_PATH", tmp_path / "spend.json")

    df_a = _hotel_df([("A-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], [])])
    df_b = _hotel_df([("B-1", "Hotel X Grand", "addr", 12.9, 77.5, 3.0, [], [])])
    near_misses = pd.DataFrame([_near_miss("A-1", "B-1", geo_score=0.9, name_score=0.5)])

    matches_df, report = la.adjudicate_hard_cases(df_a, df_b, near_misses, set(), set())

    assert len(matches_df) == 1
    row = matches_df.iloc[0]
    assert row["a_id"] == "A-1" and row["b_id"] == "B-1"
    assert row["method"] == "llm"
    assert row["confidence"] == pytest.approx(0.8)
    assert report["pairs_cached_hit"] == 1
    assert report["pairs_called"] == 0


def test_adjudicate_respects_same_hotel_false(tmp_path, monkeypatch):
    """A cached 'different hotel' verdict must never produce a match."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        '{"A-1::B-1": {"same_hotel": false, "confidence": 0.9, "reason": "different brands"}}'
    )
    monkeypatch.setattr(la, "CACHE_PATH", cache_path)
    monkeypatch.setattr(la, "SPEND_LOG_PATH", tmp_path / "spend.json")

    df_a = _hotel_df([("A-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], [])])
    df_b = _hotel_df([("B-1", "Hotel Y", "addr", 12.9, 77.5, 3.0, [], [])])
    near_misses = pd.DataFrame([_near_miss("A-1", "B-1", geo_score=0.9, name_score=0.5)])

    matches_df, report = la.adjudicate_hard_cases(df_a, df_b, near_misses, set(), set())
    assert matches_df.empty
    assert report["pairs_cached_hit"] == 1
    assert report["new_matches"] == 0


def test_adjudicate_one_to_one_among_llm_matches(tmp_path, monkeypatch):
    """Two near-miss pairs both claiming the same B hotel: only the
    higher-confidence adjudication should win, mirroring the heuristic
    matcher's greedy one-to-one assignment."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(
        '{'
        '"A-1::B-1": {"same_hotel": true, "confidence": 0.6, "reason": "plausible"},'
        '"A-2::B-1": {"same_hotel": true, "confidence": 0.9, "reason": "stronger match"}'
        "}"
    )
    monkeypatch.setattr(la, "CACHE_PATH", cache_path)
    monkeypatch.setattr(la, "SPEND_LOG_PATH", tmp_path / "spend.json")

    df_a = _hotel_df(
        [
            ("A-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], []),
            ("A-2", "Hotel X Grand", "addr", 12.9, 77.5, 3.0, [], []),
        ]
    )
    df_b = _hotel_df([("B-1", "Hotel X", "addr", 12.9, 77.5, 3.0, [], [])])
    near_misses = pd.DataFrame(
        [
            _near_miss("A-1", "B-1", geo_score=0.9, name_score=0.5),
            _near_miss("A-2", "B-1", geo_score=0.9, name_score=0.6),
        ]
    )

    matches_df, _ = la.adjudicate_hard_cases(df_a, df_b, near_misses, set(), set())
    assert len(matches_df) == 1
    assert matches_df.iloc[0]["a_id"] == "A-2"
