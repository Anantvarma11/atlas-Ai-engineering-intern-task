"""
Room matching and structured-attribute extraction.

Challenges in the data
----------------------
- Supplier A encodes attributes in the name:  "Deluxe AC · City view"
  and in the amenities field:                 "Queen Bed|196 sq.ft|3 Adults"
- Supplier B encodes attributes in the name:  "Executive Suite, King"
  and amenities can be empty.
- Coverage is uneven: some hotels have 2 room types on one side and 100+
  on the other (or nothing at all on one side).

Approach
--------
1. Extract structured attributes (bed type, occupancy, meal plan, view,
   smoking) from both the room name AND the amenities string — Supplier A
   often buries "Queen Bed" or "3 Adults" in amenities, not the name.

2. Within each matched hotel pair, compute pairwise token_set_ratio on
   room names and do a greedy one-to-one assignment for scores ≥
   ROOM_MATCH_THRESHOLD.

3. Rooms that don't find a partner (a_only / b_only) are kept as-is;
   callers can still show them on a hotel page.

Cost: $0.
"""

import re

import pandas as pd
from rapidfuzz import fuzz

ROOM_MATCH_THRESHOLD = 0.55  # token_set_ratio / 100 ≥ this → matched


# ──────────────────────────────────────────────────────────────────────────────
# Attribute extraction
# ──────────────────────────────────────────────────────────────────────────────

_BED_PATTERNS: list[tuple[str, str]] = [
    # (canonical label, regex)
    ("King",    r"\bking\b"),
    ("Queen",   r"\bqueen\b"),
    ("Twin",    r"\btwin\b"),
    ("Double",  r"\bdouble\b"),
    ("Single",  r"\bsingle\b"),
    ("Suite",   r"\bsuite\b"),
    ("Bunk",    r"\bbunk\b"),
    ("Dormitory", r"\bdorm(?:itory)?\b"),
]

_MEAL_PATTERNS: list[tuple[str, str]] = [
    ("Breakfast",   r"\bbreakfast\b|\bbed\s*&\s*breakfast\b|\bbb\b|\bw/?\.?\s*breakfast\b"),
    ("Half Board",  r"\bhalf[\s\-]?board\b|\bhb\b"),
    ("Full Board",  r"\bfull[\s\-]?board\b|\bfb\b|\ball[\s\-]?inclusive\b"),
]

_VIEW_PATTERNS: list[tuple[str, str]] = [
    ("City",      r"\bcity\s*view\b|\bcity\b"),
    ("Pool",      r"\bpool\s*view\b|\bpool\b"),
    ("Garden",    r"\bgarden\s*view\b|\bgarden\b"),
    ("Sea",       r"\bsea\s*view\b|\bocean\s*view\b"),
    ("Mountain",  r"\bmountain\s*view\b"),
    ("Courtyard", r"\bcourtyard\b"),
]


def extract_attrs(name: str, amenities: list[str] | None = None) -> dict:
    """
    Extract structured room attributes from a room name + amenities.

    Returns a dict with keys:
        bed_type   : str | None
        meal_plan  : str          ("Room Only" if no meal plan found)
        view       : str | None
        is_smoking : bool | None
    """
    # Combine name + amenities into one searchable string
    parts = [name] + (amenities or [])
    text = " ".join(parts).lower()

    # Bed type — first match wins
    bed_type = None
    for label, pattern in _BED_PATTERNS:
        if re.search(pattern, text):
            bed_type = label
            break

    # Meal plan
    meal_plan = "Room Only"
    for label, pattern in _MEAL_PATTERNS:
        if re.search(pattern, text):
            meal_plan = label
            break

    # View
    view = None
    for label, pattern in _VIEW_PATTERNS:
        if re.search(pattern, text):
            view = label
            break

    # Smoking
    is_smoking: bool | None = None
    if re.search(r"\bnon[\s\-]?smoking\b|\bno[\s\-]?smoking\b|\bnonsmoking\b", text):
        is_smoking = False
    elif re.search(r"\bsmoking\b", text):
        is_smoking = True

    return {"bed_type": bed_type, "meal_plan": meal_plan, "view": view, "is_smoking": is_smoking}


def extract_occupancy(name: str, amenities: list[str] | None = None) -> str | None:
    """Infer maximum occupancy from name + amenities."""
    text = (name + " " + " ".join(amenities or [])).lower()

    # Explicit count: "3 Adults", "2 Guests", "4 Pax"
    m = re.search(r"(\d+)\s*(?:adults?|guests?|pax|persons?|people)", text)
    if m:
        n = int(m.group(1))
        if n == 1:
            return "Single"
        elif n == 2:
            return "Double"
        elif n == 3:
            return "Triple"
        else:
            return "Family"

    # Keyword fallback
    if re.search(r"\bsingle\b", text):
        return "Single"
    if re.search(r"\bcouple\b|\bdouble\b", text):
        return "Double"
    if re.search(r"\btriple\b", text):
        return "Triple"
    if re.search(r"\bfamily\b|\bquadruple\b|\bquad\b|\bfour\b", text):
        return "Family"

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Room matching for a single hotel pair
# ──────────────────────────────────────────────────────────────────────────────

def match_rooms_for_hotel(
    rooms_a: pd.DataFrame,
    rooms_b: pd.DataFrame,
) -> tuple[list[dict], list, list]:
    """
    Align rooms between two suppliers for one matched hotel pair.

    Parameters
    ----------
    rooms_a, rooms_b : DataFrames with columns [hotel_id, room_id, name, amenities]

    Returns
    -------
    matched        : list of dicts {room_a_id, room_b_id, name_a, name_b,
                                    amenities_a, amenities_b, match_confidence}
    unmatched_a    : list of room_id strings from A with no counterpart in B
    unmatched_b    : list of room_id strings from B with no counterpart in A
    """
    if rooms_a.empty and rooms_b.empty:
        return [], [], []

    if rooms_a.empty:
        return [], [], list(rooms_b["room_id"])

    if rooms_b.empty:
        return [], list(rooms_a["room_id"]), []

    # Compute all pairwise name-similarity scores
    scores: list[tuple[float, str, str]] = []
    for ra in rooms_a.itertuples(index=False):
        for rb in rooms_b.itertuples(index=False):
            s = fuzz.token_set_ratio(ra.name, rb.name) / 100.0
            scores.append((s, ra.room_id, rb.room_id))

    scores.sort(reverse=True)

    matched_a_ids: set[str] = set()
    matched_b_ids: set[str] = set()
    matched: list[dict] = []

    for score, a_rid, b_rid in scores:
        if score < ROOM_MATCH_THRESHOLD:
            break
        if a_rid in matched_a_ids or b_rid in matched_b_ids:
            continue

        ra_row = rooms_a[rooms_a["room_id"] == a_rid].iloc[0]
        rb_row = rooms_b[rooms_b["room_id"] == b_rid].iloc[0]

        matched.append(
            {
                "room_a_id": a_rid,
                "room_b_id": b_rid,
                "name_a": ra_row["name"],
                "name_b": rb_row["name"],
                "amenities_a": ra_row["amenities"],
                "amenities_b": rb_row["amenities"],
                "match_confidence": round(score, 4),
            }
        )
        matched_a_ids.add(a_rid)
        matched_b_ids.add(b_rid)

    unmatched_a = [rid for rid in rooms_a["room_id"] if rid not in matched_a_ids]
    unmatched_b = [rid for rid in rooms_b["room_id"] if rid not in matched_b_ids]

    return matched, unmatched_a, unmatched_b
