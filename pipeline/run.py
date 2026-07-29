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

from pipeline.load import load_hotels, load_rooms
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
