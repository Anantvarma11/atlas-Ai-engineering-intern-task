"""
Optional LLM adjudication pass for genuinely ambiguous near-miss hotel pairs.

Why
---
Geo + fuzzy-name scoring (see match_hotels.py) resolves the overwhelming
majority of pairs cleanly. A small residual is genuinely ambiguous to a
string/geo heuristic: physically close, partial name overlap, but not enough
evidence either way — a legal name vs a trade name, a rebrand, a supplier
using an aggregator prefix inconsistently. These are exactly the cases where
a bit of world knowledge (a human reviewer, or a cheap LLM call) beats more
string-matching cleverness. This is the "targeted use on hard cases" the
project requires as a demonstration of good judgment — the opposite of pushing
all ~13M A×B pairs, or even the ~300k geo-blocked candidates, through a model.

This module is entirely opt-in and fails soft:
- If CEREBRAS_API_KEY is unset and no cached response exists for a pair, that
  pair is left as a near-miss and the pipeline keeps running at $0 — nothing
  breaks and nothing regresses versus the pure-heuristic baseline.
- Every request/response is cached to pipeline/cache/llm_adjudications.json,
  keyed by the (a_id, b_id) pair, and committed to the repo. Re-running the
  pipeline never re-spends on a pair already adjudicated, and the artifact
  reproduces without anyone else's key.

Cost discipline
----------------
- Only pairs that are geographically plausible AND ambiguous on name evidence
  are candidates (see _select_hard_cases) — never the obvious matches or the
  obvious non-matches.
- Hard cap of MAX_PAIRS pairs per run, prioritized by how genuinely
  borderline they are.
- Pairs are batched (BATCH_SIZE per request) to amortize the fixed prompt
  overhead across many pairs per call.
- Actual token usage from the API response is accumulated in
  pipeline/cache/llm_spend.json (lifetime total), which is the source of
  truth for the "total API spend" figure in the write-up.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_PATH = CACHE_DIR / "llm_adjudications.json"
SPEND_LOG_PATH = CACHE_DIR / "llm_spend.json"

# ──────────────────────────────────────────────────────────────────────────────
# Tunables — deliberately conservative to keep this a targeted, bounded pass.
# ──────────────────────────────────────────────────────────────────────────────
GEO_FLOOR = 0.45   # geo_score >= this (~within 170 m) — must be plausibly co-located
NAME_LOW = 0.30    # below this, the heuristic is already confident: different hotel
NAME_HIGH = 0.85   # at/above this, the property-number veto's own escape hatch resolves it
MAX_PAIRS = 200    # hard cap per run — cost discipline, not a tuning knob to raise casually
BATCH_SIZE = 20    # pairs per request, amortizes fixed prompt overhead

MODEL = "gpt-oss-120b"
BASE_URL = "https://api.cerebras.ai/v1"

# Cerebras free tier pricing (USD)
PRICE_PER_1M_INPUT = 0.0
PRICE_PER_1M_OUTPUT = 0.0


def _pair_key(a_id: str, b_id: str) -> str:
    return f"{a_id}::{b_id}"


def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return default
    return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _select_hard_cases(
    near_misses_df: pd.DataFrame,
    matched_nodes: set,
) -> pd.DataFrame:
    """
    Pick the bounded set of near-miss pairs worth spending a model call on:
    geographically plausible, ambiguous on name evidence, and not already
    resolved (either side already claimed by a higher-confidence heuristic
    match would make an LLM call redundant and risk a conflicting claim).
    """
    if near_misses_df.empty or "a_id" not in near_misses_df.columns:
        return near_misses_df

    df = near_misses_df[
        (~near_misses_df["a_id"].isin(matched_nodes))
        & (~near_misses_df["b_id"].isin(matched_nodes))
        & (near_misses_df["geo_score"] >= GEO_FLOOR)
        & (near_misses_df["name_score"] >= NAME_LOW)
        & (near_misses_df["name_score"] < NAME_HIGH)
    ].copy()

    if df.empty:
        return df

    # Prioritize pairs closest to the "coin flip" zone (name_score ~0.5) —
    # those are where a heuristic is least confident and an LLM call is most
    # likely to change the outcome. Ties broken by tighter geo distance.
    df["_priority"] = df["geo_score"] - (df["name_score"] - 0.5).abs()
    df = df.sort_values("_priority", ascending=False).head(MAX_PAIRS)
    return df.drop(columns=["_priority"])


def _build_prompt(batch: list[dict]) -> str:
    lines = [
        "You are adjudicating hotel entity-resolution candidates for a travel data pipeline.",
        "Two hotel suppliers cover the same city (Bangalore, India). Each numbered pair below",
        "is geographically close, but a string-similarity heuristic could not confidently decide",
        "whether they describe the SAME physical hotel or two DIFFERENT hotels that happen to",
        "be near each other.",
        "",
        "For EACH pair, decide same_hotel using the names, addresses, and star ratings.",
        "Treat brand renames, legal-name-vs-trade-name, transliteration/spelling differences,",
        "and inconsistent OTA aggregator prefixes (OYO/FabHotel/Treebo/SpotOn) as possible",
        "same-hotel signals. Treat clearly distinct property names, unrelated brands, or",
        "non-overlapping property ID numbers as different hotels. If you are not reasonably",
        "confident, answer same_hotel=false with a lower confidence rather than guessing yes —",
        "a missed match is preferable to a false merge.",
        "",
        "Respond with ONLY a JSON object of this exact shape:",
        '{"adjudications": [{"index": <int>, "same_hotel": <bool>, "confidence": <0.0-1.0>, "reason": "<=15 words"}]}',
        "",
        "Pairs:",
    ]
    for item in batch:
        lines.append(
            f'{item["index"]}. A="{item["name_a"]}" ({item["address_a"]}, {item["stars_a"]} stars) '
            f'vs B="{item["name_b"]}" ({item["address_b"]}, {item["stars_b"]} stars); '
            f'{item["dist_m"]:.0f}m apart.'
        )
    return "\n".join(lines)


def _update_spend_log(prompt_tokens: int, completion_tokens: int, pairs_called: int) -> dict:
    log = _load_json(
        SPEND_LOG_PATH,
        {"lifetime_prompt_tokens": 0, "lifetime_completion_tokens": 0,
         "lifetime_pairs_adjudicated": 0, "lifetime_cost_usd": 0.0, "runs": []},
    )
    cost_this_run = round(
        prompt_tokens / 1_000_000 * PRICE_PER_1M_INPUT
        + completion_tokens / 1_000_000 * PRICE_PER_1M_OUTPUT,
        6,
    )
    log["lifetime_prompt_tokens"] += prompt_tokens
    log["lifetime_completion_tokens"] += completion_tokens
    log["lifetime_pairs_adjudicated"] += pairs_called
    log["lifetime_cost_usd"] = round(log["lifetime_cost_usd"] + cost_this_run, 6)
    log["runs"].append(
        {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "pairs_called": pairs_called,
            "cost_usd": cost_this_run,
        }
    )
    _save_json(SPEND_LOG_PATH, log)
    return log


def adjudicate_hard_cases(
    near_misses_df: pd.DataFrame,
    hotels_indexed: dict[str, dict],
    matched_nodes: set,
) -> tuple[pd.DataFrame, dict]:
    """
    Ask Cerebras to adjudicate the bounded set of genuinely ambiguous
    near-miss hotel pairs. Returns (new_matches_df, run_report).

    Parameters
    ----------
    near_misses_df : output of match_hotels() — a_id/b_id are "supplier::id"
                     node strings, supplier_a/supplier_b name which supplier
                     each side belongs to.
    hotels_indexed : {supplier: {raw_id: row}} for every supplier's raw
                      hotel table, for prompt construction.
    matched_nodes   : "supplier::id" strings already claimed by a
                      heuristic match, so an LLM call can't create a
                      conflicting double-claim.

    new_matches_df has the same a_id/b_id node-string shape as
    match_hotels()'s near_misses_df, plus "method"="llm" and an
    "llm_reason" column for provenance.
    """
    empty_matches = pd.DataFrame(
        columns=["a_id", "b_id", "confidence", "geo_score", "name_score",
                 "stars_score", "dist_km", "method", "llm_reason"]
    )
    report = {
        "enabled": False, "pairs_considered": 0, "pairs_cached_hit": 0,
        "pairs_called": 0, "new_matches": 0, "prompt_tokens": 0,
        "completion_tokens": 0, "cost_usd_this_run": 0.0,
    }

    candidates = _select_hard_cases(near_misses_df, matched_nodes)
    report["pairs_considered"] = len(candidates)
    if candidates.empty:
        return empty_matches, report

    api_key = os.environ.get("CEREBRAS_API_KEY", "").strip()
    cache = _load_json(CACHE_PATH, {})

    def _lookup(node_id: str, supplier: str):
        raw_id = node_id.split("::", 1)[1]
        return hotels_indexed.get(supplier, {}).get(raw_id)

    results: dict[str, dict] = {}
    to_call: list[dict] = []
    for _, row in candidates.iterrows():
        key = _pair_key(row["a_id"], row["b_id"])
        if key in cache:
            results[key] = cache[key]
        else:
            to_call.append(row.to_dict())

    report["pairs_cached_hit"] = len(results)

    if to_call:
        if not api_key:
            print(
                f"[llm] {len(to_call)} hard case(s) have no cached adjudication and "
                "CEREBRAS_API_KEY is not set — skipping (pipeline stays at $0 for "
                "these pairs). Set the key and re-run to adjudicate them once; "
                "results are cached afterward."
            )
        else:
            try:
                from openai import OpenAI
            except ImportError:
                print("[llm] `openai` package not installed — skipping LLM adjudication.")
                to_call = []
            else:
                client = OpenAI(api_key=api_key, base_url=BASE_URL)
                run_prompt_tokens = 0
                run_completion_tokens = 0

                for i in range(0, len(to_call), BATCH_SIZE):
                    batch_rows = to_call[i : i + BATCH_SIZE]
                    batch = []
                    for j, row in enumerate(batch_rows):
                        ra = _lookup(row["a_id"], row["supplier_a"])
                        rb = _lookup(row["b_id"], row["supplier_b"])
                        stars_a = ra.get("stars")
                        stars_b = rb.get("stars")
                        batch.append(
                            {
                                "index": j,
                                "name_a": ra["name"],
                                "address_a": ra["address"] or "unknown address",
                                "stars_a": stars_a if pd.notna(stars_a) else "unknown",
                                "name_b": rb["name"],
                                "address_b": rb["address"] or "unknown address",
                                "stars_b": stars_b if pd.notna(stars_b) else "unknown",
                                "dist_m": row["dist_km"] * 1000,
                            }
                        )
                    prompt = _build_prompt(batch)
                    try:
                        resp = client.chat.completions.create(
                            model=MODEL,
                            messages=[{"role": "user", "content": prompt}],
                            response_format={"type": "json_object"},
                            temperature=0,
                        )
                    except Exception as exc:  # network/API errors — skip this batch, don't crash the pipeline
                        print(f"[llm] request failed for batch starting at {i}: {exc}")
                        continue

                    usage = getattr(resp, "usage", None)
                    if usage:
                        run_prompt_tokens += usage.prompt_tokens
                        run_completion_tokens += usage.completion_tokens

                    try:
                        parsed = json.loads(resp.choices[0].message.content)
                        adjudications = {int(a["index"]): a for a in parsed["adjudications"]}
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                        print(f"[llm] could not parse response for batch starting at {i}: {exc}")
                        continue

                    for j, row in enumerate(batch_rows):
                        adj = adjudications.get(j)
                        if adj is None:
                            continue
                        key = _pair_key(row["a_id"], row["b_id"])
                        entry = {
                            "same_hotel": bool(adj.get("same_hotel", False)),
                            "confidence": float(adj.get("confidence", 0.0)),
                            "reason": str(adj.get("reason", ""))[:200],
                        }
                        cache[key] = entry
                        results[key] = entry
                        report["pairs_called"] += 1

                _save_json(CACHE_PATH, cache)
                report["prompt_tokens"] = run_prompt_tokens
                report["completion_tokens"] = run_completion_tokens
                report["cost_usd_this_run"] = round(
                    run_prompt_tokens / 1_000_000 * PRICE_PER_1M_INPUT
                    + run_completion_tokens / 1_000_000 * PRICE_PER_1M_OUTPUT,
                    6,
                )
                report["enabled"] = True
                if report["pairs_called"]:
                    _update_spend_log(run_prompt_tokens, run_completion_tokens, report["pairs_called"])

    # ── Turn "same_hotel" adjudications into matches, greedy one-to-one ───────
    scored: list[tuple[float, pd.Series, dict]] = []
    for _, row in candidates.iterrows():
        adj = results.get(_pair_key(row["a_id"], row["b_id"]))
        if adj and adj.get("same_hotel"):
            scored.append((float(adj.get("confidence", 0.0)), row, adj))
    scored.sort(key=lambda t: -t[0])

    llm_matched_a: set = set()
    llm_matched_b: set = set()
    new_matches: list[dict] = []
    for confidence, row, adj in scored:
        if row["a_id"] in llm_matched_a or row["b_id"] in llm_matched_b:
            continue
        llm_matched_a.add(row["a_id"])
        llm_matched_b.add(row["b_id"])
        new_matches.append(
            {
                "a_id": row["a_id"],
                "b_id": row["b_id"],
                "confidence": round(confidence, 4),
                "geo_score": row["geo_score"],
                "name_score": row["name_score"],
                "stars_score": row.get("stars_score", 0.0),
                "dist_km": row["dist_km"],
                "method": "llm",
                "llm_reason": adj.get("reason", ""),
            }
        )

    report["new_matches"] = len(new_matches)
    matches_df = pd.DataFrame(new_matches) if new_matches else empty_matches
    return matches_df, report
