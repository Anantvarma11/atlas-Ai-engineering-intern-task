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

2. Within each canonical hotel cluster, embed room names (FastEmbed, in
   memory) and run `networkx.max_weight_matching` across suppliers for a
   one-to-one assignment — the same shape of problem as hotel matching,
   minus the geo signal, with a bed-type conflict veto in place of the
   property-number veto.

3. Rooms that don't find a partner are kept as their own singleton
   canonical room; callers can still show them on a hotel page.

Cost: $0.
"""

import re

import pandas as pd

ROOM_MATCH_THRESHOLD = 0.55  # token_set_ratio / 100 ≥ this → matched

# Abbreviations expanded before fuzzy comparison ("Deluxe w/ Breakfast" ==
# "Deluxe with Breakfast") so notation differences don't depress scores.
_NAME_EXPANSIONS: list[tuple[str, str]] = [
    (r"\bw/\s*", "with "),
    (r"\bdbl\b", "double"),
    (r"\bsgl\b", "single"),
    (r"\btpl\b", "triple"),
    (r"\bquad\b", "quadruple"),
    (r"\bexec\b", "executive"),
    (r"\bdlx\b", "deluxe"),
    (r"\bstd\b", "standard"),
    (r"\bsup\b", "superior"),
    (r"\bac\b", "air conditioned"),
    (r"\bnon-ac\b", "non air conditioned"),
    (r"\bbrkfst\b", "breakfast"),
    (r"\bapt\b", "apartment"),
]


def _normalize_room_name(name: str) -> str:
    """Lowercase, expand abbreviations, strip punctuation for fair matching."""
    n = (name or "").lower()
    for pattern, repl in _NAME_EXPANSIONS:
        n = re.sub(pattern, repl, n)
    n = re.sub(r"[^\w\s]", " ", n)     # punctuation → space
    n = re.sub(r"\s+", " ", n).strip()
    return n


# ──────────────────────────────────────────────────────────────────────────────
# Attribute extraction
# ──────────────────────────────────────────────────────────────────────────────

_BED_PATTERNS: list[tuple[str, str]] = [
    # (canonical label, regex) — order matters: most specific first.
    # NOTE: "Suite" is intentionally NOT a bed type (it's a room category);
    # treating it as one caused false bed conflicts between suppliers.
    ("King",          r"\bking\b"),
    ("Queen",         r"\bqueen\b"),
    ("Twin",          r"\btwin\b|\bhollywood\s*twin\b"),
    ("Double",        r"\bdouble\b|\bdbl\b"),
    ("Single",        r"\bsingle\b|\bsgl\b"),
    ("Bunk",          r"\bbunk\b"),
    ("Dormitory",     r"\bdorm(?:itory)?\b|\bhostel\s*bed\b"),
    ("Sofa Bed",      r"\bsofa[\s\-]?bed\b|\bsofa\s*cum\s*bed\b"),
    ("Multiple Beds", r"\bmultiple\s*beds\b|\b[2-9]\s*beds\b"),
    # Numeric forms: "1 Bed", "3 Bed Room", "2 Bedroom", "1 Bedroom Apartment"
    ("Multiple Beds", r"\b[2-9]\s*bed(?:s|\s*room)?\b"),
    ("Double",        r"\b1\s*bed(?:\b|\s*room\b)"),
    ("Multiple Beds", r"\b[2-9]\s*bedrooms?\b"),
    ("Double",        r"\b1\s*bedroom\b"),
]

_MEAL_PATTERNS: list[tuple[str, str]] = [
    ("Half Board",  r"\bhalf[\s\-]?board\b|\bhb\b"),
    ("Full Board",  r"\bfull[\s\-]?board\b|\bfb\b|\ball[\s\-]?inclusive\b"),
    ("Breakfast",   r"\bbreakfast\b|\bbed\s*&\s*breakfast\b|\bb\s*&\s*b\b|\bbb\b"
                    r"|\bw/?\.?\s*breakfast\b|\bcomplimentary\s+breakfast\b|\bfree\s+breakfast\b"),
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

    # Explicit count: "3 Adults", "2 Guests", "4 Pax", "sleeps 4", "for 3 people"
    m = re.search(r"(\d+)\s*(?:adults?|guests?|pax|persons?|people|sleeper)", text)
    if not m:
        m = re.search(r"\bsleeps\s*(\d+)", text)
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
    if re.search(r"\bsingle\b|\bsgl\b", text):
        return "Single"
    if re.search(r"\bcouple\b|\bdouble\b|\bdbl\b|\bking\b|\bqueen\b|\btwin\b", text):
        return "Double"
    if re.search(r"\btriple\b|\btpl\b", text):
        return "Triple"
    if re.search(r"\bfamily\b|\bquadruple\b|\bquad\b|\bdormitory\b|\bdorm\b", text):
        return "Family"

    return None


import uuid

import networkx as nx
from qdrant_client import QdrantClient

# FastEmbed automatically loads BAAI/bge-small-en-v1.5 and caches it. A single
# in-memory client is reused across hotels to avoid reloading the model; each
# call gets its own throwaway collection (see match_rooms_for_hotel).
_qclient = QdrantClient(":memory:")

ROOM_MATCH_THRESHOLD = 0.55  # minimum stretched semantic similarity → matched

# FastEmbed cosine similarity for room names is compressed into a narrow band
# (unrelated names still score ~0.7-0.8) — stretch it back to 0-1 so the
# threshold above stays meaningful.
_SIM_FLOOR = 0.75
_SIM_SPAN = 0.25


def _bed_of(name: str, amenities: list[str] | None) -> str | None:
    return extract_attrs(name, amenities)["bed_type"]


def match_rooms_for_hotel(room_dfs: dict[str, pd.DataFrame]) -> list[dict]:
    """
    Match rooms across any number of suppliers for a single canonical hotel
    cluster.

    Parameters
    ----------
    room_dfs : {supplier_name: DataFrame} with columns
               [hotel_id, room_id, name, amenities], already filtered down to
               the rooms belonging to this one hotel cluster.

    Returns
    -------
    components : list of clusters, each
        {"nodes": [{"supplier", "room_id", "name", "amenities"}, ...],
         "confidence": float,
         "method": "matched" | "singleton"}
        Every cluster has at most one room per supplier (one-to-one
        assignment via max-weight matching, mirroring match_hotels).
    """
    nodes: list[dict] = []
    for supp, df in room_dfs.items():
        for row in df.itertuples(index=False):
            nodes.append({
                "supplier": supp,
                "room_id": row.room_id,
                "name": row.name,
                "amenities": list(row.amenities) if row.amenities is not None else [],
            })

    if not nodes:
        return []

    docs = [_normalize_room_name(n["name"]) for n in nodes]
    beds = [_bed_of(n["name"], n["amenities"]) for n in nodes]

    col_name = f"rooms_{uuid.uuid4().hex}"
    _qclient.add(collection_name=col_name, documents=docs, ids=list(range(len(nodes))))

    G = nx.Graph()
    G.add_nodes_from(range(len(nodes)))

    for i, doc in enumerate(docs):
        results = _qclient.query(collection_name=col_name, query_text=doc, limit=len(nodes))
        for res in results:
            j = res.id
            if j == i or nodes[j]["supplier"] == nodes[i]["supplier"]:
                continue

            s = max(0.0, (res.score - _SIM_FLOOR) / _SIM_SPAN)
            if s < ROOM_MATCH_THRESHOLD:
                continue

            # Bed-type conflict veto: "Deluxe King" must not match "Deluxe Twin".
            if beds[i] and beds[j] and beds[i] != beds[j]:
                continue

            if G.has_edge(i, j) and G[i][j]["weight"] >= s:
                continue
            G.add_edge(i, j, weight=s)

    _qclient.delete_collection(collection_name=col_name)

    matching = nx.max_weight_matching(G, maxcardinality=False)

    components: list[dict] = []
    clustered: set[int] = set()
    for i, j in matching:
        components.append({
            "nodes": [nodes[i], nodes[j]],
            "confidence": round(G[i][j]["weight"], 4),
            "method": "matched",
        })
        clustered.add(i)
        clustered.add(j)

    for i in range(len(nodes)):
        if i not in clustered:
            components.append({"nodes": [nodes[i]], "confidence": 1.0, "method": "singleton"})

    return components
