"""
Hotel entity-resolution via geo-blocking + fuzzy name matching.

Strategy
--------
Brute-forcing all 3 400 × 3 800 ≈ 13 M pairs through an expensive scorer
is wasteful.  Instead we:

1. **Geo-block**: assign each hotel to a 0.005°-grid cell (~555 m side).
   For each A-hotel we only examine B-hotels in the same cell + its 8
   neighbours — cutting candidates by ~99 %.

2. **Score candidates** (haversine < 350 m) with three signals:
   - geo_score  : exponential decay, half-life 150 m
   - name_score : RapidFuzz token_set_ratio (handles word re-ordering)
   - stars_score: 1 − |Δstars| / 2 (small tie-breaker)

3. **Greedy one-to-one assignment**: sort all candidates by combined
   confidence desc, accept the highest-confidence pair first, skip if
   either hotel is already taken.

4. **Guard-rails** (accuracy):
   - MIN_NAME_SCORE: a pair can never be accepted on geography alone —
     perfect geo + equal stars sums to 0.55 which would clear the match
     threshold with *zero* name evidence. We require name_score ≥ 0.45.
   - Property-number veto: budget brands encode a unique property id in
     the name ("OYO 16455 …" vs "OYO 436 …"). If both names carry numbers
     and the sets are disjoint, the pair is vetoed unless the rest of the
     name is near-identical (name_score ≥ 0.85).

5. **Rescue pass** (recall): after the main geo-blocked pass, unmatched
   A/B hotels with near-identical names (token_set_ratio ≥ 95) within
   1.5 km are matched — catches real pairs whose supplier coordinates
   disagree by more than the 350 m hard cutoff.

6. **Near-misses**: candidate pairs whose combined score falls between
   NEAR_MISS_THRESHOLD and MATCH_THRESHOLD (plus vetoed pairs) — stored
   for the API so reviewers can see what the matcher almost chose.

Cost: $0 — no LLM calls.
"""

import re
from collections import defaultdict
from math import atan2, cos, radians, sin, sqrt

import pandas as pd
from rapidfuzz import fuzz

# ──────────────────────────────────────────────────────────────────────────────
# Tunables
# ──────────────────────────────────────────────────────────────────────────────
GRID_SIZE = 0.005          # degrees — each cell ≈ 555 m × 555 m in Bangalore
MAX_DIST_KM = 0.35         # hard cut-off for candidates (350 m)
GEO_HALF_LIFE_KM = 0.15   # geo_score = 0.5 at this distance
MATCH_THRESHOLD = 0.55     # combined ≥ this → accepted match
NEAR_MISS_THRESHOLD = 0.30 # combined ≥ this → stored as near-miss
MIN_NAME_SCORE = 0.45      # matches must have at least this much name evidence
NUM_VETO_NAME_SCORE = 0.85 # disjoint property numbers need this to survive

# Rescue pass (name-driven, relaxed geo)
RESCUE_NAME_SCORE = 0.95   # near-identical names
RESCUE_MAX_DIST_KM = 1.5   # relaxed geo cutoff
RESCUE_GEO_HALF_LIFE_KM = 0.75

# Weight breakdown:  geo 45 %  |  name 45 %  |  stars 10 %
W_GEO = 0.45
W_NAME = 0.45
W_STARS = 0.10

# OTA/brand prefixes that obscure the property name
_BRAND_PREFIXES = [
    "collection o ", "hotel o ", "fabhotel ", "oyo ", "oyo rooms ",
    "treebo trend ", "treebo ", "spot on ", "goroomgo ", "zostel ",
    "the hosteller ", "zostel plus ",
]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in km."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2.0 * R * atan2(sqrt(a), sqrt(1.0 - a))


def _geo_score(dist_km: float) -> float:
    """Exponential decay: 1.0 at 0 m, 0.5 at GEO_HALF_LIFE_KM."""
    return 0.5 ** (dist_km / GEO_HALF_LIFE_KM)


def _normalize_name(name: str) -> str:
    """Lowercase + strip known OTA brand prefixes for fairer fuzzy matching."""
    n = name.lower().strip()
    for prefix in _BRAND_PREFIXES:
        if n.startswith(prefix):
            n = n[len(prefix):]
            break
    # Collapse extra whitespace
    n = re.sub(r"\s+", " ", n)
    return n


def _name_score(name_a: str, name_b: str) -> float:
    """token_set_ratio handles word reordering and partial matches."""
    return fuzz.token_set_ratio(_normalize_name(name_a), _normalize_name(name_b)) / 100.0


def _prop_numbers(name: str) -> set[str]:
    """Extract property-id style numbers (2+ digits) from a hotel name."""
    return set(re.findall(r"\b\d{2,6}\b", name or ""))


def _stars_score(stars_a, stars_b) -> float:
    """1.0 if equal, 0.5 if ±1 star, 0.0 if ±2 stars or missing."""
    try:
        diff = abs(float(stars_a) - float(stars_b))
        return max(0.0, 1.0 - diff / 2.0)
    except (TypeError, ValueError):
        return 0.0


def _build_grid(df: pd.DataFrame) -> dict[tuple[int, int], list]:
    """Map each hotel to its integer grid cell."""
    grid: dict[tuple[int, int], list] = defaultdict(list)
    for row in df.itertuples(index=False):
        lat_bin = int(row.lat / GRID_SIZE)
        lon_bin = int(row.lon / GRID_SIZE)
        grid[(lat_bin, lon_bin)].append(row)
    return grid


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def match_hotels(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Match hotels from supplier A against supplier B.

    Returns
    -------
    matches_df   : columns [a_id, b_id, confidence, geo_score, name_score, stars_score, dist_km]
    near_misses_df : same schema, for pairs below MATCH_THRESHOLD but above NEAR_MISS_THRESHOLD
    """
    grid_b = _build_grid(df_b)

    all_candidates: list[dict] = []

    for row_a in df_a.itertuples(index=False):
        lat_bin = int(row_a.lat / GRID_SIZE)
        lon_bin = int(row_a.lon / GRID_SIZE)

        # Gather B-candidates from 3×3 neighbourhood
        b_candidates = []
        for dlat in (-1, 0, 1):
            for dlon in (-1, 0, 1):
                b_candidates.extend(grid_b[(lat_bin + dlat, lon_bin + dlon)])

        for row_b in b_candidates:
            dist = _haversine(row_a.lat, row_a.lon, row_b.lat, row_b.lon)
            if dist > MAX_DIST_KM:
                continue

            gs = _geo_score(dist)
            ns = _name_score(row_a.name, row_b.name)
            ss = _stars_score(row_a.stars, row_b.stars)
            combined = W_GEO * gs + W_NAME * ns + W_STARS * ss

            if combined < NEAR_MISS_THRESHOLD:
                continue

            # ── Accuracy guard-rails ──────────────────────────────────────
            # 1. Never match on geography alone.
            eligible = ns >= MIN_NAME_SCORE
            # 2. Disjoint property numbers ("OYO 16455" vs "OYO 436") veto
            #    the pair unless the rest of the name is near-identical.
            if eligible:
                nums_a = _prop_numbers(row_a.name)
                nums_b = _prop_numbers(row_b.name)
                if nums_a and nums_b and not (nums_a & nums_b) and ns < NUM_VETO_NAME_SCORE:
                    eligible = False

            all_candidates.append(
                {
                    "a_id": row_a.id,
                    "b_id": row_b.id,
                    "confidence": round(combined, 4),
                    "geo_score": round(gs, 4),
                    "name_score": round(ns, 4),
                    "stars_score": round(ss, 4),
                    "dist_km": round(dist, 4),
                    "eligible": eligible,
                }
            )

    # ── Greedy one-to-one assignment ──────────────────────────────────────────
    matched_a: set[str] = set()
    matched_b: set[str] = set()
    matches: list[dict] = []
    near_misses: list[dict] = []

    if all_candidates:
        candidates_df = pd.DataFrame(all_candidates).sort_values("confidence", ascending=False)
        for row in candidates_df.itertuples(index=False):
            d = row._asdict()
            d.pop("eligible", None)
            d["method"] = "geo_fuzzy"
            if row.confidence >= MATCH_THRESHOLD and row.eligible:
                if row.a_id not in matched_a and row.b_id not in matched_b:
                    matches.append(d)
                    matched_a.add(row.a_id)
                    matched_b.add(row.b_id)
                # If one side is already claimed, this becomes a near-miss for
                # the *other* side — we don't store it here to keep it simple.
            else:
                # Below threshold or vetoed — store as near-miss
                near_misses.append(d)

    # ── Rescue pass: near-identical names, relaxed geo ────────────────────────
    rescue = _rescue_pass(df_a, df_b, matched_a, matched_b)
    matches.extend(rescue)

    matches_df = pd.DataFrame(matches) if matches else pd.DataFrame(
        columns=["a_id", "b_id", "confidence", "geo_score", "name_score", "stars_score", "dist_km"]
    )
    near_misses_df = pd.DataFrame(near_misses) if near_misses else pd.DataFrame(
        columns=["a_id", "b_id", "confidence", "geo_score", "name_score", "stars_score", "dist_km"]
    )

    return matches_df, near_misses_df


def _rescue_pass(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    matched_a: set,
    matched_b: set,
) -> list[dict]:
    """
    Catch false negatives from the 350 m hard cutoff: unmatched hotels whose
    names are near-identical (token_set_ratio ≥ RESCUE_NAME_SCORE) and that
    sit within RESCUE_MAX_DIST_KM of each other.

    Confidence is name-driven (0.70·name + 0.20·relaxed-geo + 0.10·stars)
    to stay honest about the weaker geographic evidence.
    """
    rest_a = [r for r in df_a.itertuples(index=False) if r.id not in matched_a]
    rest_b = [r for r in df_b.itertuples(index=False) if r.id not in matched_b]
    if not rest_a or not rest_b:
        return []

    norm_b = [_normalize_name(r.name) for r in rest_b]

    candidates: list[tuple[float, float, object, object]] = []
    for ra in rest_a:
        na = _normalize_name(ra.name)
        if not na:
            continue
        for rb, nb in zip(rest_b, norm_b):
            if not nb:
                continue
            ns = fuzz.token_set_ratio(na, nb) / 100.0
            if ns < RESCUE_NAME_SCORE:
                continue
            dist = _haversine(ra.lat, ra.lon, rb.lat, rb.lon)
            if dist > RESCUE_MAX_DIST_KM:
                continue
            # Disjoint property numbers still veto here
            nums_a = _prop_numbers(ra.name)
            nums_b = _prop_numbers(rb.name)
            if nums_a and nums_b and not (nums_a & nums_b):
                continue
            candidates.append((ns, dist, ra, rb))

    # Greedy one-to-one, best name score first, closer wins ties
    candidates.sort(key=lambda t: (-t[0], t[1]))
    taken_a: set = set()
    taken_b: set = set()
    rescued: list[dict] = []
    for ns, dist, ra, rb in candidates:
        if ra.id in taken_a or rb.id in taken_b:
            continue
        taken_a.add(ra.id)
        taken_b.add(rb.id)
        gs = 0.5 ** (dist / RESCUE_GEO_HALF_LIFE_KM)
        ss = _stars_score(ra.stars, rb.stars)
        confidence = 0.70 * ns + 0.20 * gs + 0.10 * ss
        rescued.append(
            {
                "a_id": ra.id,
                "b_id": rb.id,
                "confidence": round(confidence, 4),
                "geo_score": round(gs, 4),
                "name_score": round(ns, 4),
                "stars_score": round(ss, 4),
                "dist_km": round(dist, 4),
                "method": "rescue",
            }
        )
    return rescued
