"""
Hotel entity-resolution via geo-filtered semantic search + weighted matching.

Strategy
--------
1. **Semantic embedding**: every hotel, from every supplier, is embedded via
   Qdrant's FastEmbed (`BAAI/bge-small-en-v1.5`), run fully in-process
   (embedded Qdrant — no external service to stand up). This handles
   synonyms and reordering that plain string similarity misses.

2. **Geo-filtered candidate search**: for each hotel we query for its nearest
   semantic neighbors, restricted to a 1.5 km geo radius, then score
   candidates within a stricter 350 m hard cutoff (relaxed to 1.5 km only
   for the rescue pass, see below).

3. **Weighted graph + one-to-one matching**: candidate pairs across
   suppliers become edges (weight = geo + name + stars, see below). We run
   `networkx.max_weight_matching` over the accepted edges so that no hotel
   is ever claimed by more than one counterpart per supplier pair — the
   same one-to-one guarantee as a strict bipartite assignment, generalized
   to any number of suppliers.

4. **Rescue pass** (recall): pairs with near-identical names but outside the
   350 m cutoff (up to 1.5 km) are matched on relaxed geo weighting — catches
   real pairs whose supplier coordinates disagree by more than the hard
   cutoff.

5. **Near-misses**: edges that scored above NEAR_MISS_THRESHOLD but lost the
   matching (either below MATCH_THRESHOLD, vetoed, or out-competed by a
   better-scoring edge on one of their two endpoints) are kept for the API
   and for optional LLM adjudication.

Cost: $0 — no LLM calls, no external services.
"""

import re
from math import atan2, cos, radians, sin, sqrt

import networkx as nx
import pandas as pd
from qdrant_client import QdrantClient
from qdrant_client.models import models

# ──────────────────────────────────────────────────────────────────────────────
# Tunables
# ──────────────────────────────────────────────────────────────────────────────
MAX_DIST_KM = 0.35         # hard cut-off for candidates (350 m)
GEO_HALF_LIFE_KM = 0.15    # geo_score = 0.5 at this distance
MATCH_THRESHOLD = 0.55     # combined ≥ this → accepted match
NEAR_MISS_THRESHOLD = 0.30 # combined ≥ this → stored as near-miss
MIN_NAME_SCORE = 0.45      # matches must have at least this much name evidence
NUM_VETO_NAME_SCORE = 0.85 # disjoint property numbers need this to survive

# Rescue pass (name-driven, relaxed geo)
RESCUE_NAME_SCORE = 0.95   # near-identical names
RESCUE_MAX_DIST_KM = 1.5   # relaxed geo cutoff
RESCUE_GEO_HALF_LIFE_KM = 0.75
RESCUE_SEARCH_RADIUS_M = 1500.0

# Weight breakdown:  geo 45 %  |  name 45 %  |  stars 10 %
W_GEO = 0.45
W_NAME = 0.45
W_STARS = 0.10

# FastEmbed cosine similarity for near-duplicate hotel names is compressed
# into a narrow band (unrelated names still score ~0.7-0.8) — stretch it
# back out to a 0-1 range so the existing thresholds stay meaningful.
_SIM_FLOOR = 0.75
_SIM_SPAN = 0.25

CANDIDATES_PER_HOTEL = 50

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
    """Lowercase + strip known OTA brand prefixes for fairer similarity scoring."""
    n = (name or "").lower().strip()
    for prefix in _BRAND_PREFIXES:
        if n.startswith(prefix):
            n = n[len(prefix):]
            break
    return re.sub(r"\s+", " ", n)


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


def _stretch_similarity(score: float) -> float:
    return max(0.0, (score - _SIM_FLOOR) / _SIM_SPAN)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def match_hotels(
    dfs: dict[str, pd.DataFrame],
    qclient: QdrantClient | None = None,
) -> tuple[list[dict], pd.DataFrame]:
    """
    Match hotels across any number of suppliers.

    Parameters
    ----------
    dfs : {supplier_name: DataFrame} with columns
          [id, name, address, lat, lon, stars, amenities, image_urls]

    Returns
    -------
    components : list of clusters. Each cluster is
        {"nodes": [{"supplier": str, "id": str}, ...],
         "confidence": float,   # 1.0 for singletons, the matching edge's
                                 # combined score otherwise
         "method": str}         # "singleton" | "geo_fuzzy" | "rescue"
        Every cluster has at most one hotel per supplier (one-to-one
        assignment, enforced by max-weight matching below).
    near_misses_df : DataFrame of edges that were considered but not part of
        the final matching, for the API and optional LLM adjudication.
    """
    docs: list[str] = []
    metadata: list[dict] = []
    ids: list[int] = []

    current_idx = 0
    for supp, df in dfs.items():
        for row in df.itertuples(index=False):
            docs.append(_normalize_name(row.name))
            metadata.append({
                "supplier": supp,
                "id": row.id,
                "name": row.name,
                "stars": row.stars,
                "location": {"lat": row.lat, "lon": row.lon},
            })
            ids.append(current_idx)
            current_idx += 1

    if not docs:
        return [], pd.DataFrame()

    client = qclient if qclient is not None else QdrantClient(":memory:")
    collection = "hotels"
    if client.collection_exists(collection):
        client.delete_collection(collection)
    client.add(collection_name=collection, documents=docs, metadata=metadata, ids=ids)

    # ── Graph construction: nodes = hotels, edges = cross-supplier candidates ──
    G = nx.Graph()
    for m in metadata:
        G.add_node(f"{m['supplier']}::{m['id']}", supplier=m["supplier"], id=m["id"])

    for i, doc in enumerate(docs):
        meta_a = metadata[i]
        node_a = f"{meta_a['supplier']}::{meta_a['id']}"

        results = client.query(
            collection_name=collection,
            query_text=doc,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="location",
                        geo_radius=models.GeoRadius(
                            center=models.GeoPoint(lat=meta_a["location"]["lat"], lon=meta_a["location"]["lon"]),
                            radius=RESCUE_SEARCH_RADIUS_M,
                        ),
                    )
                ]
            ),
            limit=CANDIDATES_PER_HOTEL,
        )

        for r in results:
            meta_b = r.metadata
            node_b = f"{meta_b['supplier']}::{meta_b['id']}"

            if node_a == node_b or meta_a["supplier"] == meta_b["supplier"]:
                continue

            ns = _stretch_similarity(r.score)
            dist = _haversine(
                meta_a["location"]["lat"], meta_a["location"]["lon"],
                meta_b["location"]["lat"], meta_b["location"]["lon"],
            )

            is_rescue = False
            eligible = True
            combined = 0.0
            gs = 0.0
            ss = 0.0

            if dist <= MAX_DIST_KM:
                gs = _geo_score(dist)
                ss = _stars_score(meta_a["stars"], meta_b["stars"])
                combined = W_GEO * gs + W_NAME * ns + W_STARS * ss

                eligible = ns >= MIN_NAME_SCORE
                nums_a = _prop_numbers(meta_a["name"])
                nums_b = _prop_numbers(meta_b["name"])
                if nums_a and nums_b and not (nums_a & nums_b) and ns < NUM_VETO_NAME_SCORE:
                    eligible = False

            elif dist <= RESCUE_MAX_DIST_KM and ns >= RESCUE_NAME_SCORE:
                nums_a = _prop_numbers(meta_a["name"])
                nums_b = _prop_numbers(meta_b["name"])
                if nums_a and nums_b and not (nums_a & nums_b):
                    continue
                gs = 0.5 ** (dist / RESCUE_GEO_HALF_LIFE_KM)
                ss = _stars_score(meta_a["stars"], meta_b["stars"])
                combined = 0.70 * ns + 0.20 * gs + 0.10 * ss
                is_rescue = True
            else:
                continue

            if combined < NEAR_MISS_THRESHOLD:
                continue

            if G.has_edge(node_a, node_b):
                if combined <= G[node_a][node_b]["weight"]:
                    continue

            G.add_edge(
                node_a, node_b,
                weight=combined, geo_score=gs, name_score=ns,
                stars_score=ss, dist_km=dist, eligible=eligible,
                is_rescue=is_rescue,
            )

    # ── One-to-one resolution: max-weight matching over accepted edges ───────
    G_valid = nx.Graph()
    for u, v, data in G.edges(data=True):
        if data["eligible"] and data["weight"] >= MATCH_THRESHOLD:
            G_valid.add_edge(u, v, **data)

    matching = nx.max_weight_matching(G_valid, maxcardinality=False)

    components: list[dict] = []
    clustered_nodes: set[str] = set()
    for u, v in matching:
        data = G_valid[u][v]
        components.append({
            "nodes": [
                {"supplier": G.nodes[u]["supplier"], "id": G.nodes[u]["id"]},
                {"supplier": G.nodes[v]["supplier"], "id": G.nodes[v]["id"]},
            ],
            "confidence": round(data["weight"], 4),
            "method": "rescue" if data["is_rescue"] else "geo_fuzzy",
        })
        clustered_nodes.add(u)
        clustered_nodes.add(v)

    for node in G.nodes():
        if node not in clustered_nodes:
            components.append({
                "nodes": [{"supplier": G.nodes[node]["supplier"], "id": G.nodes[node]["id"]}],
                "confidence": 1.0,
                "method": "singleton",
            })

    matched_pairs = {frozenset((u, v)) for u, v in matching}

    near_misses = []
    for u, v, data in G.edges(data=True):
        if frozenset((u, v)) in matched_pairs:
            continue
        near_misses.append({
            "a_id": u,
            "b_id": v,
            "supplier_a": G.nodes[u]["supplier"],
            "supplier_b": G.nodes[v]["supplier"],
            "confidence": round(data["weight"], 4),
            "geo_score": round(data["geo_score"], 4),
            "name_score": round(data["name_score"], 4),
            "stars_score": round(data["stars_score"], 4),
            "dist_km": round(data["dist_km"], 4),
            "method": "rescue" if data["is_rescue"] else "geo_fuzzy",
        })

    near_misses_df = pd.DataFrame(near_misses) if near_misses else pd.DataFrame(
        columns=["a_id", "b_id", "supplier_a", "supplier_b", "confidence",
                 "geo_score", "name_score", "stars_score", "dist_km", "method"]
    )

    return components, near_misses_df


def apply_llm_matches(components: list[dict], llm_matches_df: pd.DataFrame) -> list[dict]:
    """
    Fold LLM-adjudicated node pairs (a_id/b_id = "supplier::id" strings) into
    the existing component list, merging whichever clusters those two nodes
    currently belong to (each may be a singleton or already part of a
    heuristic match) into one, tagged method="llm".
    """
    if llm_matches_df.empty:
        return components

    node_to_component: dict[str, dict] = {}
    for comp in components:
        for n in comp["nodes"]:
            node_to_component[f"{n['supplier']}::{n['id']}"] = comp

    remaining = [c for c in components]

    for _, row in llm_matches_df.iterrows():
        a_id, b_id = row["a_id"], row["b_id"]
        comp_a = node_to_component.get(a_id)
        comp_b = node_to_component.get(b_id)
        if comp_a is None or comp_b is None or comp_a is comp_b:
            continue

        merged = {
            "nodes": comp_a["nodes"] + comp_b["nodes"],
            "confidence": round(float(row["confidence"]), 4),
            "method": "llm",
            "note": row.get("llm_reason"),
        }
        if comp_a in remaining:
            remaining.remove(comp_a)
        if comp_b in remaining:
            remaining.remove(comp_b)
        remaining.append(merged)

        for n in merged["nodes"]:
            node_to_component[f"{n['supplier']}::{n['id']}"] = merged

    return remaining
