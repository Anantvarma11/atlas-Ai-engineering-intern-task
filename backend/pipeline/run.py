#!/usr/bin/env python3
"""
Pipeline entry-point.

Usage
-----
    python -m pipeline.run               # skip if canonical.db already exists
    python -m pipeline.run --force       # re-run even if db exists
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path when invoked directly
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

# Load a local .env file (if present) so CEREBRAS_API_KEY etc. don't need to
# be exported manually. Optional dependency — degrades silently if missing.
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from pipeline.load import load_hotels, load_rooms
from pipeline.llm_adjudicate import adjudicate_hard_cases
from pipeline.match_hotels import apply_llm_matches, match_hotels
from pipeline.merge import DB_PATH, JSON_PATH, build_canonical

DATA_DIR = PROJECT_ROOT / "data"


def main() -> None:
    parser = argparse.ArgumentParser(description="Hotels canonical-layer pipeline")
    parser.add_argument(
        "--force", action="store_true",
        help="Rebuild canonical.db even if it already exists",
    )
    args = parser.parse_args()

    if DB_PATH.exists() and not args.force:
        print(f"[pipeline] canonical.db already exists at {DB_PATH}.")
        print("[pipeline] Pass --force to rebuild. Skipping.")
        return

    t0 = time.perf_counter()

    # ── Load ───────────────────────────────────────────────────────────────────
    print("[pipeline] Loading supplier CSVs …")
    hotel_dfs = {}
    room_dfs = {}
    
    for csv_file in DATA_DIR.glob("*_hotels.csv"):
        supp = csv_file.name.replace("_hotels.csv", "")
        df = load_hotels(csv_file)
        hotel_dfs[supp] = df
        print(f"[pipeline]   {supp}: {len(df):,} hotels")
        
    for csv_file in DATA_DIR.glob("*_rooms.csv"):
        supp = csv_file.name.replace("_rooms.csv", "")
        df = load_rooms(csv_file)
        room_dfs[supp] = df
        print(f"[pipeline]   {supp} rooms: {len(df):,}")

    if not hotel_dfs:
        print("[pipeline] No *_hotels.csv files found in data directory.")
        return

    # ── Match hotels ───────────────────────────────────────────────────────────
    print("[pipeline] Running N-way hotel entity-resolution …")
    t1 = time.perf_counter()
    components, near_misses_df = match_hotels(hotel_dfs)
    t2 = time.perf_counter()
    print(
        f"[pipeline]   {len(components):,} canonical clusters identified  "
        f"| {len(near_misses_df):,} near-miss edges  "
        f"(took {t2 - t1:.1f}s)"
    )

    # ── Optional LLM adjudication of the hardest remaining near-misses ────────
    # Fully opt-in: no-ops at $0 unless CEREBRAS_API_KEY is set or a cache of
    # previous adjudications already exists. See pipeline/llm_adjudicate.py.
    matched_nodes = {
        f"{n['supplier']}::{n['id']}"
        for comp in components if len(comp["nodes"]) > 1
        for n in comp["nodes"]
    }
    hotels_indexed = {
        supp: {row["id"]: row for _, row in df.iterrows()}
        for supp, df in hotel_dfs.items()
    }
    llm_matches_df, llm_report = adjudicate_hard_cases(near_misses_df, hotels_indexed, matched_nodes)
    if llm_report["pairs_considered"]:
        print(
            f"[pipeline] LLM adjudication: {llm_report['pairs_considered']} hard case(s) considered, "
            f"{llm_report['pairs_cached_hit']} from cache, {llm_report['pairs_called']} new API call(s), "
            f"{llm_report['new_matches']} promoted to matches, "
            f"${llm_report['cost_usd_this_run']:.6f} spent this run"
        )
    if not llm_matches_df.empty:
        components = apply_llm_matches(components, llm_matches_df)
        promoted = set(zip(llm_matches_df["a_id"], llm_matches_df["b_id"]))
        near_misses_df = near_misses_df[
            ~near_misses_df.apply(lambda r: (r["a_id"], r["b_id"]) in promoted, axis=1)
        ]

    # ── Merge + persist ────────────────────────────────────────────────────────
    print("[pipeline] Building canonical records and writing DB …")
    n_hotels, n_rooms, n_nm = build_canonical(
        hotel_dfs,
        room_dfs,
        components,
        near_misses_df,
        db_path=DB_PATH,
        json_path=JSON_PATH,
    )

    elapsed = time.perf_counter() - t0
    print(
        f"[pipeline] Done in {elapsed:.1f}s — "
        f"{n_hotels:,} canonical hotels | "
        f"{n_rooms:,} canonical rooms | "
        f"{n_nm:,} near-miss pairs"
    )
    print(f"[pipeline] Artifacts: {DB_PATH}  {JSON_PATH}")


if __name__ == "__main__":
    main()
