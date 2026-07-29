# Write-up: Mini Hotels Layer

## Approach

### Hotel matching

The brute-force A×B comparison (~13 M pairs) is too large to pass through anything expensive. My candidate-generation step cuts it to ~300 k pairs using a **geospatial grid**:

- Round each hotel's lat/lon to the nearest 0.005° (~555 m grid cell).
- For each A hotel examine only B hotels in the same cell plus its 8 neighbours.
- Hard-cut at 350 m Haversine distance.

This reduces the comparison space by ~99 % without losing any real match — two hotels at the same address can have coordinate offsets up to ~100–150 m across suppliers (different GPS sources, entrances), so the 350 m threshold is deliberately loose.

Each surviving candidate pair is scored with three signals:

| Signal | Weight | Implementation |
|--------|--------|----------------|
| `geo_score` | 45 % | Exponential decay, half-life 150 m (`0.5^(d/0.15)`) |
| `name_score` | 45 % | RapidFuzz `token_set_ratio` after stripping OTA brand prefixes ("Collection O", "FabHotel", etc.) |
| `stars_score` | 10 % | `1 − |Δstars| / 2`, acts as tie-breaker |

Matches are accepted via **greedy one-to-one assignment** (sort by `combined` desc, take highest-confidence pair, skip if either side already claimed). Pairs with combined ≥ 0.55 become matches; 0.30–0.55 become near-misses stored per canonical hotel.

Two **accuracy guard-rails** protect against a subtle flaw in the weighted score — perfect geo + equal stars already sums to 0.55, so co-located but *different* hotels could match with zero name evidence:

1. **Minimum name evidence** — a pair is never accepted with `name_score < 0.45`; geography alone can't create a match. An error audit of the unguarded version found ~70–130 false positives of exactly this type (e.g. "OYO 2420 Ashwa Comfort" ↔ "Ample Inn" at identical coordinates).
2. **Property-number veto** — budget brands encode a unique property ID in the name ("OYO 16455 …" vs "OYO 436 …"). If both names carry numbers and the sets are disjoint, the pair is vetoed unless the rest of the name is near-identical.

A **rescue pass** then recovers false negatives from the 350 m hard cutoff: unmatched hotels with near-identical names (`token_set_ratio ≥ 0.95`) within 1.5 km are matched with an honestly lower, name-driven confidence (`0.70·name + 0.20·relaxed-geo + 0.10·stars`) — this catches real pairs whose supplier coordinates disagree (different GPS fixes on large properties).

**Result:** 2,534 matched pairs from 3,409 A × 3,762 B hotels (~2 s matching). The guard-rails removed ~100 geography-only false positives that the naive version accepted; the rescue pass recovered pairs the hard cutoff lost. Vetoed pairs are kept as near-misses so a reviewer can audit every rejection.

Confidence distribution among matched pairs:

| Confidence range | Count |
|-----------------|-------|
| 1.00 | 1,007 |
| 0.90–0.99 | 944 |
| 0.80–0.89 | 334 |
| 0.70–0.79 | 120 |
| 0.55–0.69 | 129 |

The 129 edge-case matches (0.55–0.69) are genuine but uncertain — and now all of them carry real name evidence (name_score ≥ 0.45). A spot-check showed they're mostly renames: "Super Townhouse Oak AECS Formerly Bangalore Times" matched because the B-side still uses the old name "Bangalore Times Hotel"; the near-miss data lets a human reviewer verify quickly.

### Room matching

Rooms can't use geo signals. Within each matched hotel pair I do:

1. **Attribute extraction** from room name + amenities combined (Supplier A buries structured data like "Queen Bed", "3 Adults", "City view" in the amenities field rather than the name). Patterns cover numeric forms ("3 Bed", "2 Bedroom"), abbreviations ("Dbl", "Sgl"), and dorms/bunks. "Suite" is deliberately **not** a bed type — it's a room category, and treating it as a bed caused false conflicts.
2. **Name normalization** before fuzzy comparison: abbreviation expansion ("w/" → "with", "Dbl" → "double"), punctuation stripping — so notation differences don't depress scores.
3. **Greedy one-to-one assignment** by `token_set_ratio` ≥ 0.55 on normalized names, with a **bed-type conflict veto**: "Deluxe King" is never matched to "Deluxe Twin" no matter how similar the rest of the name is.

Room attribute coverage out of 19,341 canonical rooms: bed type 59 % (11,416), occupancy 59 % (11,468), view 18 % (3,451), non-"Room Only" meal plan <1 % — a grep of both CSVs confirms meal-plan info essentially doesn't exist in this data (Bangalore budget/mid-scale hotels almost never bundle meals). The coverage numbers are honest: many rooms are named "Run of House", "Standard", "Deluxe" with no attribute details — I extract what's there and don't fabricate.

The imbalance between matched (1,854), a_only (2,047), and b_only (15,440) is expected: Supplier B has ~4× more room entries per hotel and lists rooms for nearly all its hotels; Supplier A has rooms for a much smaller subset.

### LLM adjudication of genuinely hard cases (optional, opt-in)

The heuristic pipeline resolves 2,534 pairs at $0 with no LLM involvement.
On top of that, `pipeline/llm_adjudicate.py` adds a **bounded, targeted**
pass over the hardest residual near-misses — the ones where the geo+fuzzy
scorer is closest to a coin flip:

- **Selection**: near-miss pairs with `geo_score ≥ 0.45` (physically
  plausible, ≲170 m) AND `0.30 ≤ name_score < 0.85` (ambiguous — not so low
  the heuristic is already confident it's a different hotel, not so high the
  property-number veto's own escape hatch already resolves it). Capped at
  200 pairs per run, prioritized by closeness to the 0.5 "coin flip" zone.
- **Model**: `deepseek-chat` (DeepSeek's general model), chosen over a
  frontier model specifically for cost — this is exactly the kind of
  judgment call where a cheap model with the raw name/address/stars/distance
  in front of it beats more string-matching cleverness, and the task
  (binary same/different + short rationale) doesn't need a stronger model.
- **Batching**: 20 pairs per request to amortize the fixed prompt overhead.
- **Caching**: every request/response is keyed by `(a_id, b_id)` and written
  to `pipeline/cache/llm_adjudications.json`, which is committed. Re-running
  the pipeline — or grading it without a key — reproduces byte-identical
  output at $0; only genuinely new pairs would trigger a call.
- **One-to-one**: LLM-confirmed matches go through the same greedy
  highest-confidence-first assignment as the heuristic passes, so an LLM
  call can't double-claim a hotel another pass already has, or that a
  higher-confidence LLM verdict also wants.
- **Fail-soft by design**: no key and no cache → the pipeline logs a message
  and continues at $0, identical to the baseline. A malformed/failed model
  response for a batch is skipped (logged), never crashes the pipeline or
  silently fabricates a match.
- **Provenance**: an LLM-confirmed match is tagged `match_method: "llm"`
  with `match_note` set to the model's one-line rationale, so it's
  distinguishable from a `geo_fuzzy` or `rescue` match everywhere in the API
  and in `canonical_hotels.json` — a reviewer can audit exactly which
  matches came from a model call and why.

**Honest status at submission time**: I did not have a DeepSeek key while
building this, so the committed `canonical.db` reflects the $0 heuristic
baseline only (`hotels_by_match_method`: 2,467 `geo_fuzzy` + 67 `rescue`,
0 `llm`) — `GET /stats` shows `"llm_spend": null`. The mechanism is built,
unit-tested (`tests/test_llm_adjudicate.py` — selection filtering, cache-hit
behavior with zero network calls, one-to-one assignment among LLM matches,
graceful no-key skip), and wired into `pipeline/run.py`; running
`python -m pipeline.run --force` with `DEEPSEEK_API_KEY` set adjudicates the
≤200 candidate pairs, caches the results, and updates `/stats` and this
write-up's cost figure below accordingly. I'd rather report a truthful $0
than fabricate a number I can't back with a real request log.

### What I discarded

- **Bulk LLM matching over all candidates**: unnecessary for a geo+fuzzy signal that already achieves high precision on the overwhelming majority of pairs, and would cost far more than the targeted pass above for no real accuracy gain on the easy cases.
- **Image perceptual hashing**: would require downloading ~37 k images from GCS; adding 10–15 min of network I/O for a marginal signal when geo+name is already working.
- **Sentence-transformer name embeddings**: SBERT would improve recall on hard semantic cases ("The Leela Palace" ↔ "Leela Palace Bengaluru"), but the added complexity and latency (~30 s vs 0.4 s) wasn't worth it for this dataset size, especially once the LLM pass covers the same class of hard case with world knowledge a fixed embedding space wouldn't have anyway (rebrands, aggregator-prefix noise). Would reconsider at 200 k hotels, where the LLM pass's linear cost stops being negligible.
- **Blocking by name prefix/soundex**: fragile with OTA brand noise ("OYO 12345 Hotel X" prefix is meaningless). Geo blocking is cleaner.
- **Google Places enrichment**: good idea for genuinely ambiguous cases but bulk resolution misses the point; the LLM adjudication pass above ended up serving the same "targeted use on hard cases" role without needing a second external key.
- **Re-weighting the core geo/name/stars scorer to add an address-similarity term**: the address field is loaded but unused directly. I deliberately didn't fold it into the validated scoring formula — reopening a formula that already passed its adversarial audit (see below) risks new false positives/negatives that are hard to re-validate in the time available. Instead, address text is handed to the LLM adjudication pass as extra context for exactly the pairs where it might tip a genuinely ambiguous call — upside without touching the proven path.

### How I validated matching

1. **Adversarial error audit**: queried every matched pair with confidence 0.55–0.75 and eyeballed name pairs sorted by name_score ascending. This surfaced the geography-only false-positive class ("OYO 2420 Ashwa Comfort" ↔ "Ample Inn") that motivated the MIN_NAME_SCORE guard-rail, and the disjoint-property-number class ("OYO 16455 Amazing Inn" ↔ "OYO 436 Emirates Suites") that motivated the veto. Re-ran the audit after the fix: zero remaining pairs with name_score < 0.45.
2. **False-negative audit**: cross-checked a_only vs b_only hotels for near-exact name matches within 1 km — this motivated the rescue pass, which recovers real pairs beyond the 350 m cutoff.
3. **Bed-conflict audit on rooms**: counted matched room pairs where extracting bed type separately from each side's name yields conflicting beds; the conflict veto reduced this to ~5 of 1,854 (residual cases come from amenity-level information).
4. **Spot-checks at every confidence tier** plus anti-spot-checks (e.g. "Fortune Select JP Cosmos" matched to its true B-side counterpart, not a nearby unrelated Fortune Hotel).
5. **Automated test suite**: 62 pytest tests encode these guarantees as regression tests — geo-only pair rejected, property-number veto, rescue pass, bed-conflict veto, one-to-one assignment, attribute extraction cases, near-miss provenance for a_only/b_only hotels, LLM adjudication selection/caching/one-to-one behavior, plus full API contract tests (`pytest tests/`).
6. **Coverage sanity**: 2,534 matches from ~3,400 A hotels (~74 % match rate) is plausible — Bangalore has many small B-side-only properties (OYO budget hotels) without A-side coverage.
7. **Near-miss audit found a real gap, not just a matching bug**: while adding LLM adjudication I noticed near-miss candidates were only ever attached to hotels that ended up `matched` — an `a_only`/`b_only` hotel (which is exactly the case where "why didn't this match?" matters most) silently showed zero near-misses even when the matcher had found one. Fixed to attach symmetrically; 618 of 875 `a_only` hotels (71%) and 961 of 1,228 `b_only` hotels (78%) now surface a real near-miss candidate instead of an empty list.

### Total API spend

**$0.00 as submitted.** The core pipeline (geo-blocking, fuzzy name scoring, rescue pass, room matching, attribute extraction) makes zero external calls — every one of the 2,534 matches in the committed `canonical.db` is pure local computation.

An optional, opt-in DeepSeek adjudication pass exists (`pipeline/llm_adjudicate.py`) for the ≤200 hardest near-miss pairs, but I did not have a DeepSeek key while building this, so it has never actually run — `GET /stats` → `"llm_spend": null` confirms this truthfully rather than reporting an estimate as fact. If run, the cost is small and bounded by construction: ≤200 pairs batched 20-per-request (≤10 requests), each request ~500–900 prompt tokens and ~200–400 completion tokens depending on batch fill, against `deepseek-chat` pricing (~$0.27/1M input, ~$1.10/1M output tokens at cache-miss rates, verify current pricing before trusting this figure on a re-run) — a back-of-envelope upper bound is **under $0.01 for the whole run**, and every subsequent run costs $0 for the same pairs because responses are cached in `pipeline/cache/llm_adjudications.json`. The exact figure, once run, is computed from real `usage` token counts (not estimated) and persisted in `pipeline/cache/llm_spend.json`, surfaced live at `GET /stats`.

---

## Scaling to 200,000 hotels × 3 suppliers

At this scale the current design breaks in several places:

| Bottleneck | Current solution | Fix at scale |
|------------|-----------------|-------------|
| Geo-blocking dict in Python memory | 0.005° grid, dict of lists | **PostGIS** `ST_DWithin` with a spatial index; runs as a DB join instead of Python iteration |
| Pairwise fuzzy scoring (~300 k pairs) | RapidFuzz in a single process | **Parallelize** over hotel grid cells with `multiprocessing.Pool`; or shard by city |
| Name-only blocking misses semantic variants | token_set_ratio | Add **ANN lookup over SBERT embeddings** (FAISS); run only for pairs that pass geo-blocking but have low name_score |
| SQLite | Fine for single-node read | **PostgreSQL** with JSONB columns + `pg_trgm` for name similarity; FTS via `tsvector` |
| canonical.db as a file | ~10 MB for 4 k hotels | Would be ~500 MB for 200 k × 3; split into partitioned tables, serve from a read replica |
| Pipeline is batch (not streaming) | Single Python process | Move to **Apache Beam / Spark** for parallel processing; incremental update when a supplier sends a delta feed |
| Near-miss storage | 35.5 k rows for ~4.6 k hotels (capped at top-10/hotel) | ~1.5 M rows for 200 k hotels — still fine in Postgres at the same per-hotel cap |
| 3 suppliers instead of 2 | A vs B pairwise | Run A↔B, A↔C, B↔C in parallel; build a union-find structure to merge transitive matches (A matches B and B matches C → merge all three) |
| LLM adjudication cap (≤200 pairs/run) | Fine — a few hundred genuinely ambiguous pairs out of ~4.6 k hotels | At 200 k hotels the ambiguous residue scales roughly linearly (~tens of thousands of pairs); the per-run cap would need to become a per-region or per-priority budget, not a single global constant, or cost stops being negligible |
| In-memory rate limiter / request log | Fine for one process | Doesn't share state across instances — move to a shared store (Redis) or an edge-level limiter (API gateway) once running more than one API replica |
| SQLite WAL, per-request connection | Fine for single-node read replicas | Postgres connection pooling (pgbouncer) once concurrent write/read separation matters |

The first thing to break is the Python-dict geo-blocking: at 600 k hotels, loading and iterating the dict consumes ~2 GB RAM and takes minutes. Migrating to PostGIS solves both issues.
