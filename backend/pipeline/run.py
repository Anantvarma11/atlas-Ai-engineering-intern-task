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

# Load a local .env file (if present) so DEEPSEEK_API_KEY etc. don't need to
# be exported manually. Optional dependency — degrades silently if missing.
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from pipeline.load import load_hotels, load_rooms
from pipeline.llm_adjudicate import adjudicate_hard_cases
from pipeline.match_hotels import match_hotels
from pipeline.merge import DB_PATH, JSON_PATH, build_canonical

DATA_DIR = PROJECT_ROOT


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
    df_a    = load_hotels(DATA_DIR / "supplier_a.csv")
    df_b    = load_hotels(DATA_DIR / "supplier_b.csv")
    rooms_a = load_rooms(DATA_DIR  / "rooms_a.csv")
    rooms_b = load_rooms(DATA_DIR  / "rooms_b.csv")
    print(
        f"[pipeline]   supplier_a: {len(df_a):,} hotels  "
        f"| supplier_b: {len(df_b):,} hotels  "
        f"| rooms_a: {len(rooms_a):,}  "
        f"| rooms_b: {len(rooms_b):,}"
    )

    # ── Match hotels ───────────────────────────────────────────────────────────
    print("[pipeline] Running hotel entity-resolution …")
    t1 = time.perf_counter()
    matches_df, near_misses_df = match_hotels(df_a, df_b)
    t2 = time.perf_counter()
    print(
        f"[pipeline]   {len(matches_df):,} matched pairs  "
        f"| {len(near_misses_df):,} near-miss pairs  "
        f"(took {t2 - t1:.1f}s)"
    )

    # ── Optional LLM adjudication of the hardest remaining near-misses ────────
    # Fully opt-in: no-ops at $0 unless DEEPSEEK_API_KEY is set or a cache of
    # previous adjudications already exists. See pipeline/llm_adjudicate.py.
    matched_a_ids = set(matches_df["a_id"]) if not matches_df.empty else set()
    matched_b_ids = set(matches_df["b_id"]) if not matches_df.empty else set()
    llm_matches_df, llm_report = adjudicate_hard_cases(
        df_a, df_b, near_misses_df, matched_a_ids, matched_b_ids
    )
    if llm_report["pairs_considered"]:
        print(
            f"[pipeline] LLM adjudication: {llm_report['pairs_considered']} hard case(s) considered, "
            f"{llm_report['pairs_cached_hit']} from cache, {llm_report['pairs_called']} new API call(s), "
            f"{llm_report['new_matches']} promoted to matches, "
            f"${llm_report['cost_usd_this_run']:.6f} spent this run"
        )
    if not llm_matches_df.empty:
        matches_df = pd.concat([matches_df, llm_matches_df], ignore_index=True)
        newly_matched_a = set(llm_matches_df["a_id"])
        newly_matched_b = set(llm_matches_df["b_id"])
        if not near_misses_df.empty:
            # Drop near-miss rows for pairs the LLM just promoted to matches,
            # and any other near-miss involving a now-claimed hotel, so the
            # API doesn't show a hotel as both matched and a live near-miss.
            near_misses_df = near_misses_df[
                ~near_misses_df["a_id"].isin(newly_matched_a)
                & ~near_misses_df["b_id"].isin(newly_matched_b)
            ]

    # ── Merge + persist ────────────────────────────────────────────────────────
    print("[pipeline] Building canonical records and writing DB …")
    n_hotels, n_rooms, n_nm = build_canonical(
        df_a, df_b,
        matches_df, near_misses_df,
        rooms_a, rooms_b,
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
