# Write-up: Mini Hotels Layer

## Approach

### Hotel matching

Two suppliers ("A" and "B") each list Bangalore hotels independently — same
physical property, different internal ID, differently-worded name, a
slightly different GPS fix, its own amenity vocabulary. The pipeline is
written to generalize past exactly two suppliers (any number of
`{supplier}_hotels.csv` files in `data/` are picked up automatically), so the
matcher below is described in those terms even though this dataset only has
two.

**Candidate generation.** Every hotel, from every supplier, is embedded with
Qdrant's FastEmbed (`BAAI/bge-small-en-v1.5`), run fully in-process — no
external vector database to stand up, no network hop. For each hotel we query
for its nearest semantic neighbors, restricted to a 1.5 km geo radius, then
score candidates within a stricter 350 m hard cutoff (the 1.5 km radius only
matters for the rescue pass below).

Each surviving candidate pair is scored with three signals:

| Signal | Weight | Implementation |
|--------|--------|----------------|
| `geo_score` | 45 % | Exponential decay, half-life 150 m (`0.5^(d/0.15)`) |
| `name_score` | 45 % | FastEmbed cosine similarity on normalized names (OTA brand prefixes stripped: "Collection O", "FabHotel", etc.), stretched back to 0–1 since raw cosine similarity for short hotel-name strings is compressed into a narrow ~0.75–1.0 band |
| `stars_score` | 10 % | `1 − |Δstars| / 2`, acts as tie-breaker |

**Assignment.** Candidate pairs become edges in a graph; accepted edges
(eligible, weight ≥ 0.55) go through `networkx.max_weight_matching` — the
actual one-to-one bipartite assignment (an earlier draft's docstring claimed
this but the code underneath only took raw connected components, which could
silently merge two of A's hotels into one canonical record through a shared
B neighbor; that mismatch is fixed by construction now, and
`test_one_to_one_assignment` pins it down). Pairs that score above the
near-miss floor but lose the matching (either below threshold, vetoed, or
out-competed by a better edge on one of their two endpoints) are kept as
near-misses.

Two **accuracy guard-rails** protect against a subtle flaw in the weighted
score — perfect geo + equal stars already sums to 0.55, so co-located but
*different* hotels could match with zero name evidence:

1. **Minimum name evidence** — a pair is never accepted with
   `name_score < 0.45`; geography alone can't create a match.
2. **Property-number veto** — budget brands encode a unique property ID in
   the name ("OYO 16455 …" vs "OYO 436 …"). If both names carry numbers and
   the sets are disjoint, the pair is vetoed unless the rest of the name is
   near-identical.

A **rescue pass** then recovers false negatives from the 350 m hard cutoff:
unmatched hotels with near-identical names (similarity ≥ 0.95) within 1.5 km
are matched with an honestly lower, name-driven confidence
(`0.70·name + 0.20·relaxed-geo + 0.10·stars`) — this catches real pairs whose
supplier coordinates disagree (different GPS fixes on large properties).

**Result on this dataset:** 2,540 matched pairs from 3,409 A × 3,762 B hotels
→ 4,631 canonical hotels (2,091 singletons). Matching took ~340 s (see
"What this trades away" below for why, honestly).

Confidence distribution among matched pairs:

| Confidence range | Count |
|-----------------|-------|
| 1.00 | 963 |
| 0.90–0.99 | 853 |
| 0.80–0.89 | 388 |
| 0.70–0.79 | 177 |
| 0.55–0.69 | 159 |

The 159 edge-case matches (0.55–0.69) all carry real name evidence
(`name_score ≥ 0.45` by construction) — genuine but uncertain, and visible as
such through `match_confidence` rather than reported with false certainty.

### Room matching

Rooms can't use geo signals, but the problem is otherwise the same shape as
hotel matching, so it reuses the same machinery: an in-process FastEmbed
collection per hotel cluster, a bed-type conflict veto, and
`max_weight_matching` for one-to-one assignment across suppliers.

1. **Attribute extraction** from room name + amenities combined (Supplier A
   buries structured data like "Queen Bed", "3 Adults", "City view" in the
   amenities field rather than the name). Patterns cover numeric forms
   ("3 Bed", "2 Bedroom"), abbreviations ("Dbl", "Sgl"), and dorms/bunks.
   "Suite" is deliberately **not** a bed type — it's a room category, and
   treating it as a bed caused false conflicts.
2. **Name normalization** before similarity scoring: abbreviation expansion
   ("w/" → "with", "Dbl" → "double"), punctuation stripping.
3. **Bed-type conflict veto**: "Deluxe King" is never matched to
   "Deluxe Twin" no matter how similar the rest of the name is — verified at
   0 conflicts across all 1,711 matched room pairs in the committed DB.

Room attribute coverage out of 19,484 canonical rooms: bed type 58.0%
(11,307), occupancy 58.5% (11,406), view 17.3% (3,373), non-"Room Only" meal
plan effectively 0% (5 rooms) — a grep of both CSVs confirms meal-plan info
essentially doesn't exist in this data (Bangalore budget/mid-scale hotels
almost never bundle meals). The coverage numbers are honest: many rooms are
named "Run of House", "Standard", "Deluxe" with no attribute details — the
pipeline extracts what's there and doesn't fabricate the rest.

Only 1,711 of 19,484 canonical rooms (8.8%) ended up `matched`. That's a real
consequence of the underlying data, not a matching defect — Supplier B lists
~4.6 rooms/hotel on average against Supplier A's ~1.1, and a large share of
Supplier B's per-hotel room list is a single generic "Run of House" entry
with no real room-type detail to match against. Hand-checking hotels where
both sides *do* list comparable room tiers (e.g. "Deluxe Double Room" /
"Superior Double Room" / "Premium Double Room" present on both sides) shows
the matcher correctly pairs each tier to its true counterpart via
`max_weight_matching`, rather than cross-wiring tiers — see
`test_rooms_matched_across_suppliers_within_cluster`.

### LLM adjudication of genuinely hard cases (optional, opt-in)

The heuristic pipeline resolves 2,540 pairs at $0 with no LLM involvement. On
top of that, `pipeline/llm_adjudicate.py` adds a **bounded, targeted** pass
over the hardest residual near-misses — the ones where the geo+semantic
scorer is closest to a coin flip:

- **Selection**: near-miss pairs with `geo_score ≥ 0.45` (physically
  plausible, ≲170 m) AND `0.30 ≤ name_score < 0.85` (ambiguous — not so low
  the heuristic is already confident it's a different hotel, not so high the
  property-number veto's own escape hatch already resolves it), excluding
  either side of a pair already claimed by a heuristic match. Capped at 200
  pairs per run, prioritized by closeness to the 0.5 "coin flip" zone.
- **Model**: `gpt-oss-120b` on Cerebras's free tier — chosen for cost; this
  is exactly the kind of judgment call where a cheap model with the raw
  name/address/stars/distance in front of it beats more string-matching
  cleverness, and the task (binary same/different + short rationale) doesn't
  need a stronger model.
- **Batching**: 20 pairs per request to amortize the fixed prompt overhead.
- **Caching**: every request/response is keyed by the pair and written to
  `pipeline/cache/llm_adjudications.json`, which is committed. Re-running the
  pipeline — or grading it without a key — reproduces the same output at $0;
  only genuinely new pairs would trigger a call.
- **One-to-one**: LLM-confirmed matches are folded into the existing
  component graph (`apply_llm_matches`), so an LLM call can't double-claim a
  hotel another pass already has, or that a higher-confidence LLM verdict
  also wants — `test_adjudicate_one_to_one_among_llm_matches` and
  `test_three_way_cluster_via_llm_promotion` pin this down.
- **Fail-soft by design**: no key and no cache → the pipeline logs a message
  and continues at $0, identical to the baseline. A malformed/failed model
  response for a batch is skipped (logged), never crashes the pipeline or
  silently fabricates a match.
- **Provenance**: an LLM-confirmed match is tagged `match_method: "llm"` with
  `match_note` set to the model's one-line rationale, distinguishable from a
  `geo_fuzzy` or `rescue` match everywhere in the API and in
  `canonical_hotels.json`.

**Actual run, this submission**: `CEREBRAS_API_KEY` was set for the committed
build. 97 near-miss pairs were considered, all 97 required a fresh API call
(no prior cache), and 15 were promoted to matches (`match_method: "llm"`,
each with its rationale in `match_note`) — visible in `GET /stats` →
`hotels_by_match_method.llm: 15` and `llm_spend`. Actual token usage:
11,413 prompt / 17,685 completion tokens, **$0.00** at Cerebras's free-tier
pricing. `pipeline/cache/llm_adjudications.json` and `llm_spend.json` are
committed, so re-running the pipeline reproduces the same 15 promotions from
cache without spending anything or needing a key.

### What this trades away (and why it's still the right call)

Switching hotel- and room-name similarity from RapidFuzz string matching to
FastEmbed sentence embeddings buys real recall on semantic variants a string
metric can't see (a legal name vs. a trade name, reordered words, a
transliteration) — worthwhile for a matcher meant to generalize past exactly
two known suppliers with exactly this dataset's naming quirks. It has a real
cost: running Qdrant in its embedded, in-process mode (no server to stand
up, so `docker compose up` needs nothing extra) means every geo-filtered
candidate query is a brute-force scan rather than an indexed lookup. On
7,171 hotels that's ~340 s of hotel matching and ~530 s end-to-end — a real
regression from a pure-heuristic pass, which would run in under a second on
this dataset size. This is a one-time, offline batch cost (the API never
recomputes a match at request time, and `canonical.db` is committed so a
grader doesn't have to re-run the pipeline at all to see the result) and
still finishes in one `docker compose up`-free command, so the trade felt
worth taking here; see "Scaling" below for what changes at real volume.

### What I discarded

- **Bulk LLM matching over all candidates**: unnecessary given the combined
  embedding and geo scorer already achieves high precision on the
  overwhelming majority of pairs, and would cost far more than the targeted
  pass above for no real accuracy gain on the easy cases.
- **Image perceptual hashing for hotel matching**: would require downloading
  tens of thousands of images from GCS for a marginal signal when geo+name
  is already working (it's still used, cheaply, for *photo de-duplication*
  within an already-merged hotel — see `pipeline/image_dedupe.py`).
- **A networked Qdrant server** (with a real HNSW payload index instead of
  brute-force local scanning): would fix the ~9 minute pipeline runtime, but
  adds a service `docker compose up` would need to provision and wait to be
  healthy before the pipeline can run — for a take-home graded on
  correctness and one-command reproducibility, the slower-but-dependency-free
  embedded mode won out. Documented as the first thing to change at scale.
- **Blocking by name prefix/soundex**: fragile with OTA brand noise ("OYO
  12345 Hotel X" prefix is meaningless). Geo blocking is cleaner.
- **Google Places enrichment**: good idea for genuinely ambiguous cases but
  bulk resolution misses the point; the LLM adjudication pass above serves
  the same "targeted use on hard cases" role without a second external key.
- **Re-weighting the core geo/name/stars scorer to add an address-similarity
  term**: the address field is loaded but unused directly in scoring.
  Address text is handed to the LLM adjudication pass as extra context for
  exactly the pairs where it might tip a genuinely ambiguous call — upside
  without reopening a scoring formula that already passed its own
  adversarial audit.

### How I validated matching

1. **Adversarial error audit**: queried matched pairs with low confidence and
   eyeballed name pairs. This is what motivated `MIN_NAME_SCORE` (a
   geography-only false-positive class: co-located but unrelated hotel
   names) and the property-number veto (disjoint OYO/property IDs).
2. **False-negative audit**: cross-checked singleton hotels for near-exact
   name matches within 1 km — this motivated the rescue pass.
3. **Bed-conflict audit on rooms**: 0 of 1,711 matched room pairs carry
   conflicting bed types.
4. **Real-data spot-check on room matching**: hand-verified a hotel (see
   `WRITEUP.md`'s room-matching section) where both suppliers list multiple
   comparable room tiers, confirming `max_weight_matching` pairs each tier
   with its true counterpart rather than cross-wiring.
5. **Automated test suite**: 62 pytest tests encode these guarantees as
   regression tests — geo-only pair rejected, property-number veto, rescue
   pass, bed-conflict veto, one-to-one assignment (including a 3-way cluster
   formed via LLM promotion), attribute extraction cases, near-miss
   provenance for singleton hotels, LLM adjudication selection/caching/
   one-to-one behavior, plus full API contract tests (`pytest tests/`).
6. **Coverage sanity**: 2,540 matches from 3,409 A hotels (~74% match rate)
   is plausible — Bangalore has many small B-side-only properties (OYO
   budget hotels) without A-side coverage.
7. **Near-miss coverage**: near-misses are attached to every hotel with a
   plausible-but-rejected candidate, not only to hotels that ended up
   matched. 1,470 of 2,091 (70.3%) singleton hotels surface a real near-miss
   candidate — exactly the case ("why didn't this match?") a reviewer most
   wants visibility into.

### Total API spend

**$0.00 for this submission.** The core pipeline (semantic hotel matching,
geo scoring, rescue pass, room matching, attribute extraction) makes zero
external calls. The optional Cerebras adjudication pass did run for this
build (97 pairs, 15 promoted) and cost $0.00 because Cerebras's free tier
covers `gpt-oss-120b` at zero price per token — the real usage
(11,413 prompt + 17,685 completion tokens) is in
`pipeline/cache/llm_spend.json` and surfaced live at `GET /stats`, not
estimated.

---

## Scaling to 200,000 hotels × 3 suppliers

At this scale the current design breaks in several places:

| Bottleneck | Current solution | Fix at scale |
|------------|-----------------|-------------|
| Brute-force vector search (embedded, in-process Qdrant) | Linear scan per hotel query, ~340 s for 7 k hotels | A **networked Qdrant (or pgvector) server with a real HNSW index** — sub-linear candidate lookup, the difference between minutes and hours at 200k |
| Geo filtering done inside the vector query | Geo-radius filter per query, no spatial index in local mode | **PostGIS** `ST_DWithin` with a spatial index, or a proper geo payload index on a real Qdrant server |
| Room/hotel graph construction & matching in one Python process | `networkx` in memory | **Parallelize** by geographic shard (city/region) — matching only ever needs candidates within ~1.5 km, so shards are independent |
| SQLite | Fine for single-node read | **PostgreSQL** with JSONB columns + `pg_trgm` for name similarity; FTS via `tsvector` |
| canonical.db as a file | ~23 MB for 4.6 k hotels | Would be ~1 GB+ for 200k × 3; split into partitioned tables, serve from a read replica |
| Pipeline is batch (not streaming) | Single Python process | Move to **Apache Beam / Spark** for parallel processing; incremental update when a supplier sends a delta feed |
| Near-miss storage | 26.5 k rows for 4.6 k hotels | Scales roughly linearly — still fine in Postgres, cap near-misses per hotel if it grows unbounded |
| N-way merging beyond pairs | `max_weight_matching` gives pairs; a 3-way real match needs two rounds (heuristic pair + LLM-promoted third) | A proper **union-find over all accepted edges**, or iterative matching rounds, so an N-way cluster forms in one pass instead of relying on LLM promotion to bridge it |
| LLM adjudication cap (≤200 pairs/run) | Fine — a few hundred genuinely ambiguous pairs out of ~4.6 k hotels | At 200k hotels the ambiguous residue scales roughly linearly (tens of thousands of pairs); the per-run cap would need to become a per-region or per-priority budget, not a single global constant |
| In-memory rate limiter / request log | Fine for one process | Move to a shared store (Redis) or an edge-level limiter (API gateway) once running more than one API replica |
| SQLite WAL, per-request connection | Fine for single-node read replicas | Postgres connection pooling (pgbouncer) once concurrent write/read separation matters |

The first thing to break is the embedded vector search: at 200k hotels,
brute-force geo-filtered similarity search over the full collection for
every hotel would take hours, not minutes. Migrating to a real indexed
vector store (or PostGIS + `pg_trgm`) solves that directly.
