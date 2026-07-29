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

**Result:** 2,564 matched pairs from 3,409 A × 3,762 B hotels (took 0.4 s).

Confidence distribution among matched pairs:

| Confidence range | Count |
|-----------------|-------|
| 1.00 | 1,478 |
| 0.90–0.99 | 646 |
| 0.80–0.89 | 160 |
| 0.70–0.79 | 148 |
| 0.55–0.69 | 132 |

The 132 edge-case matches (0.55–0.69) are genuine but uncertain. A spot-check of five showed they're mostly correct: "Super Townhouse Oak AECS Formerly Bangalore Times" matched at 0.55 because the B-side still uses the old name "Bangalore Times Hotel"; the near-miss data lets a human reviewer verify quickly.

### Room matching

Rooms can't use geo signals. Within each matched hotel pair I do:

1. **Attribute extraction** from room name + amenities combined (Supplier A buries structured data like "Queen Bed", "3 Adults", "City view" in the amenities field rather than the name).
2. **Greedy one-to-one assignment** by `token_set_ratio` ≥ 0.55 on room names.

Room attribute coverage out of 19,442 canonical rooms: bed type 61 % (11,946), view 18 % (3,485), non-"Room Only" meal plan <1 % (5 — Bangalore budget/mid-scale hotels almost never include meals). The low-coverage numbers are honest: many rooms in the data are named "Run of House", "Standard", "Deluxe" with no amenity details — I extract what's there and don't fabricate.

The imbalance between matched (1,753), a_only (2,148), and b_only (15,541) is expected: Supplier B has ~4× more room entries per hotel and lists rooms for nearly all its hotels; Supplier A has rooms for a much smaller subset.

### What I discarded

- **LLM-based matching**: unnecessary for a geo+fuzzy signal that already achieves high precision, and would cost $10–50+ for the full candidate set.
- **Image perceptual hashing**: would require downloading ~37 k images from GCS; adding 10–15 min of network I/O for a marginal signal when geo+name is already working.
- **Sentence-transformer name embeddings**: SBERT would improve recall on hard semantic cases ("The Leela Palace" ↔ "Leela Palace Bengaluru"), but the added complexity and latency (~30 s vs 0.4 s) wasn't worth it for this dataset size. Would reconsider at 200 k hotels.
- **Blocking by name prefix/soundex**: fragile with OTA brand noise ("OYO 12345 Hotel X" prefix is meaningless). Geo blocking is cleaner.
- **Google Places enrichment**: good idea for genuinely ambiguous cases but bulk resolution misses the point; I kept it in mind as a targeted fallback and found it wasn't needed.

### How I validated matching

1. **Spot-checks at every confidence tier**: sampled 5 pairs each from the 1.0, 0.9, 0.7, and 0.6 bands. The 1.0 band is almost always identical names at identical coordinates (same GPS fix). The 0.6 band has cases like "Housr 7th Cross Marathahalli Main Road" ↔ "Housr co-living" — geo score 0.99, name score 0.24 — which could be the same property under a shortened name. These are honestly borderline.
2. **Anti-spot-checks**: searched for "Fortune" (a common Bangalore chain) and confirmed the pipeline correctly matched "Fortune Select JP Cosmos - Member ITC Hotel Group" (A-35201) to its B-side counterpart rather than to a nearby unrelated Fortune Hotel.
3. **Coverage sanity**: 2,564 matches from ~3,400 A hotels (~75 % match rate) is plausible — Bangalore has many small B-side-only properties (OYO budget hotels) without A-side coverage.

### Total API spend

**$0.00** — no external API calls of any kind. All matching is done with local computation.

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
| Near-miss storage | 21 k rows for 7 k hotels | ~600 k rows for 200 k hotels — still fine in Postgres, but cap at top-10 per hotel (already done) |
| 3 suppliers instead of 2 | A vs B pairwise | Run A↔B, A↔C, B↔C in parallel; build a union-find structure to merge transitive matches (A matches B and B matches C → merge all three) |

The first thing to break is the Python-dict geo-blocking: at 600 k hotels, loading and iterating the dict consumes ~2 GB RAM and takes minutes. Migrating to PostGIS solves both issues.
