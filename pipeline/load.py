"""Load and clean supplier CSV files."""

import html
import pandas as pd
from pathlib import Path


def _parse_pipe(val) -> list[str]:
    """Split a pipe-separated field, deduplicate by lowercase key."""
    if pd.isna(val) or str(val).strip() == "":
        return []
    items = [x.strip() for x in str(val).split("|") if x.strip()]
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def load_hotels(path: Path | str) -> pd.DataFrame:
    """Load a supplier hotel CSV and return a clean DataFrame."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]

    # Unescape HTML entities (e.g. &#39; → ')
    df["name"] = df["name"].apply(lambda x: html.unescape(x).strip() if x else "")
    df["address"] = df["address"].apply(
        lambda x: html.unescape(x).strip() if x else ""
    )

    # Numeric conversions
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["stars"] = pd.to_numeric(df["stars"], errors="coerce")

    # Pipe-separated lists → deduplicated Python lists
    df["amenities"] = df["amenities"].apply(_parse_pipe)
    df["image_urls"] = df["image_urls"].apply(_parse_pipe)

    # Drop rows without coordinates — can't geo-match them
    n_before = len(df)
    df = df.dropna(subset=["lat", "lon"]).reset_index(drop=True)
    n_dropped = n_before - len(df)
    if n_dropped:
        print(f"  [load] Dropped {n_dropped} rows with missing lat/lon from {path}")

    return df


def load_rooms(path: Path | str) -> pd.DataFrame:
    """Load a supplier rooms CSV and return a clean DataFrame."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]

    df["name"] = df["name"].apply(lambda x: x.strip() if x else "")
    df["amenities"] = df["amenities"].apply(_parse_pipe)

    return df
