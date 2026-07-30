import { Link } from "react-router-dom";

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="border border-zinc-800 rounded-lg px-4 py-3">
      <div className="font-mono text-xl text-zinc-100">{value}</div>
      <div className="mt-1 text-xs uppercase tracking-wide text-zinc-500">{label}</div>
    </div>
  );
}

function Section({
  index,
  title,
  children,
}: {
  index: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-zinc-800 py-14">
      <div className="flex items-baseline gap-3">
        <span className="font-mono text-sm text-cyan-500">{index}</span>
        <h2 className="font-display text-2xl text-zinc-100 sm:text-3xl">{title}</h2>
      </div>
      <div className="mt-6 max-w-3xl space-y-4 text-[15px] leading-relaxed text-zinc-400">
        {children}
      </div>
    </section>
  );
}

function Sub({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-8 max-w-3xl border-l-2 border-zinc-800 pl-5">
      <h3 className="font-mono text-sm uppercase tracking-wide text-zinc-200">{title}</h3>
      <div className="mt-2 space-y-3 text-[15px] leading-relaxed text-zinc-400">{children}</div>
    </div>
  );
}

function Kv({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-zinc-900 py-1.5 font-mono text-xs">
      <span className="text-zinc-500">{k}</span>
      <span className="text-zinc-300">{v}</span>
    </div>
  );
}

function Pill({ name, note }: { name: string; note: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 px-3 py-2.5">
      <div className="font-mono text-sm text-zinc-100">{name}</div>
      <div className="mt-0.5 text-xs text-zinc-500">{note}</div>
    </div>
  );
}

export function Landing() {
  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-300">
      <header className="border-b border-zinc-800">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-5">
          <span className="font-mono text-xs uppercase tracking-[0.2em] text-zinc-500">
            Away · Engineering Case Study
          </span>
          <Link
            to="/app"
            className="group inline-flex items-center gap-1.5 rounded-full bg-cyan-400 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-cyan-300"
          >
            Try it out
            <span className="transition-transform group-hover:translate-x-0.5">→</span>
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-6">
        <div className="py-16 sm:py-24">
          <p className="font-mono text-sm text-cyan-500">Take-home submission — hotel entity resolution</p>
          <h1 className="mt-4 max-w-2xl font-display text-4xl leading-tight text-zinc-50 sm:text-5xl">
            Two supplier feeds. One clean record per hotel.
          </h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-zinc-400">
            This page walks through what was asked, exactly how the pipeline cleans and
            resolves the raw data, and how each layer of the system actually works —
            before you click through to the running product.
          </p>

          <div className="mt-10 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat value="4,631" label="Canonical hotels" />
            <Stat value="19,484" label="Canonical rooms" />
            <Stat value="62" label="Passing tests" />
            <Stat value="$0.00" label="Total spend" />
          </div>
        </div>

        <Section index="01" title="The brief">
          <p>
            Away sources hotel inventory from third-party suppliers. Two of them — call
            them <strong className="text-zinc-200">A</strong> and{" "}
            <strong className="text-zinc-200">B</strong> — independently list overlapping
            hotels in Bangalore. The same physical property shows up in both feeds, but
            under a different internal ID, a differently-worded name
            ("OYO 16455 Comfort Inn" vs. "Comfort Inn Residency"), a slightly different
            address and GPS fix, its own amenity vocabulary, its own re-uploaded photo
            set, and its own room list, named however that supplier's catalog team felt
            like naming it that day.
          </p>
          <p>
            Before a traveler can see one clean page per hotel — or compare price across
            suppliers — something has to decide "these two listings are the same
            real-world hotel," merge them into a single canonical record with confidence
            and provenance attached, and do the same one level down for rooms. That
            resolution-and-merge problem, at hotel level and then room level, is the
            actual assignment. The API and the UI exist to expose that merged layer.
          </p>
        </Section>

        <Section index="02" title="Cleaning the raw feeds">
          <p>
            Each supplier ships two CSVs: a hotel file
            (<code className="text-zinc-300">id, name, address, lat, lon, stars,
            amenities, image_urls</code>) and a room file
            (<code className="text-zinc-300">hotel_id, room_id, name, amenities</code>).
            Nothing downstream touches a raw string until it's passed through the same
            cleaning path, regardless of which supplier it came from.
          </p>
          <Sub title="load.py — parsing">
            <p>
              <code className="text-zinc-300">amenities</code> and{" "}
              <code className="text-zinc-300">image_urls</code> arrive as pipe-separated
              strings ("Swimming pool|Bar|Gym"). Each is split, trimmed, and
              de-duplicated case-insensitively while preserving first-seen casing, so
              "Wifi" and "WIFI" collapse to one entry instead of showing twice.
            </p>
            <p>
              HTML entities in name/address (<code className="text-zinc-300">&amp;#39;</code>,
              etc.) are unescaped. <code className="text-zinc-300">lat</code>,{" "}
              <code className="text-zinc-300">lon</code>, and{" "}
              <code className="text-zinc-300">stars</code> are coerced to numeric,
              non-numeric values become <code className="text-zinc-300">NaN</code> rather
              than crashing the load.
            </p>
            <p>
              Rows missing <code className="text-zinc-300">lat</code>/
              <code className="text-zinc-300">lon</code> are dropped before matching even
              starts — a hotel that can't be placed on a map can't be geo-matched, and the
              pipeline logs exactly how many rows were dropped rather than silently
              losing data.
            </p>
          </Sub>
          <Sub title="Name normalization">
            <p>
              Before any similarity comparison, hotel names are lowercased and a known
              list of OTA/aggregator prefixes is stripped ("OYO", "FabHotel", "Treebo
              Trend", "SpotOn", "Collection O", "Zostel", "The Hosteller", …) — otherwise
              two genuinely identical hotels score as dissimilar purely because one
              supplier prefixes the brand and the other doesn't.
            </p>
            <p>
              Room names go through a second, room-specific pass: abbreviations are
              expanded ("w/" → "with", "dbl" → "double", "ac" → "air conditioned", "sgl" →
              "single", …) and punctuation is stripped, so notation differences alone
              don't depress a similarity score between two otherwise-identical room
              names.
            </p>
          </Sub>
        </Section>

        <Section index="03" title="Hotel matching engine">
          <p>
            <code className="text-zinc-300">pipeline/match_hotels.py</code> turns the
            cleaned rows into canonical clusters in four steps.
          </p>
          <Sub title="1 · Embed + candidate search">
            <p>
              Every hotel's normalized name is embedded with Qdrant's FastEmbed
              (<code className="text-zinc-300">BAAI/bge-small-en-v1.5</code>), run
              in-process — no external vector database to stand up or wait on health
              checks for. Embeddings and metadata (supplier, id, stars, lat/lon) go into
              one in-memory collection. For each hotel, a query returns up to 50 nearest
              semantic neighbors, restricted to a 1.5&nbsp;km geo-radius filter — this is
              what keeps ~7,000 hotels from becoming an ~13M-pair brute-force comparison.
            </p>
          </Sub>
          <Sub title="2 · Score every candidate">
            <p>
              Candidates within the 350&nbsp;m hard cutoff get a weighted combined score:
            </p>
            <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
              <Kv k="geo_score" v="0.5 ^ (distance_km / 0.15)  — half-life 150 m" />
              <Kv k="name_score" v="stretched FastEmbed cosine similarity" />
              <Kv k="stars_score" v="1 − |Δstars| / 2" />
              <Kv k="combined" v="0.45·geo + 0.45·name + 0.10·stars" />
            </div>
            <p>
              Candidates between 350&nbsp;m and 1.5&nbsp;km with near-identical names
              (similarity ≥ 0.95) go through a separate "rescue" formula instead —
              <code className="text-zinc-300"> 0.70·name + 0.20·relaxed_geo + 0.10·stars</code>,
              relaxed_geo using a 750&nbsp;m half-life — to recover real pairs whose two
              suppliers simply disagree on GPS by more than the strict cutoff.
            </p>
          </Sub>
          <Sub title="3 · Guard-rails">
            <p>
              Two rules exist specifically because an adversarial audit found real
              failure modes in the raw weighted score: perfect geo + equal stars alone
              already sums to 0.55, which would clear the match threshold with{" "}
              <em>zero</em> name evidence.
            </p>
            <p>
              <strong className="text-zinc-200">Minimum name evidence</strong> —
              name_score must be ≥ 0.45; geography can never create a match on its own.{" "}
              <strong className="text-zinc-200">Property-number veto</strong> — budget
              brands encode a unique ID in the name ("OYO 16455…" vs. "OYO 436…"); if both
              names carry numbers and the sets are disjoint, the pair is vetoed unless the
              rest of the name is near-identical (≥ 0.85).
            </p>
          </Sub>
          <Sub title="4 · One-to-one assignment">
            <p>
              Every edge that survives (eligible, combined ≥ 0.55) goes into a graph.
              <code className="text-zinc-300"> networkx.max_weight_matching</code> then
              computes the actual globally-optimal one-to-one pairing — not a greedy
              first-match — so a hotel can never be silently claimed by two different
              counterparts at once. Edges that scored ≥ 0.30 but lost the matching (below
              threshold, vetoed, or out-competed on a shared endpoint) are kept as
              near-misses instead of discarded, visible on every hotel that had one.
            </p>
          </Sub>
        </Section>

        <Section index="04" title="Room matching">
          <p>
            <code className="text-zinc-300">pipeline/match_rooms.py</code> re-runs
            almost the same machinery one level down, inside each already-resolved
            hotel cluster.
          </p>
          <Sub title="Attribute extraction">
            <p>
              Regex pattern tables pull <code className="text-zinc-300">bed_type</code>{" "}
              (King / Queen / Twin / Double / Single / Bunk / Dormitory / Sofa Bed /
              Multiple Beds), <code className="text-zinc-300">meal_plan</code>{" "}
              (Room Only / Breakfast / Half Board / Full Board),{" "}
              <code className="text-zinc-300">view</code> (City / Pool / Garden / Sea /
              Mountain / Courtyard), and{" "}
              <code className="text-zinc-300">is_smoking</code> from the room name{" "}
              <em>and</em> the amenities list combined — Supplier A frequently buries
              "Queen Bed" or "3 Adults" in amenities rather than the name.{" "}
              <strong className="text-zinc-200">"Suite" is deliberately not a bed
              type</strong> — it's a room category, and treating it as one caused false
              bed conflicts between suppliers.
            </p>
          </Sub>
          <Sub title="Cross-supplier matching">
            <p>
              A throwaway, in-memory FastEmbed collection is built per hotel cluster from
              every room name across every supplier present. Candidate room pairs across
              (never within) suppliers are scored the same stretched-cosine way as hotel
              names, then vetoed if their extracted bed types conflict —{" "}
              <strong className="text-zinc-200">"Deluxe King" is never matched to
              "Deluxe Twin"</strong> no matter how similar the rest of the name reads. The
              survivors go through the same <code className="text-zinc-300">
              max_weight_matching</code> one-to-one assignment as hotels.
            </p>
            <p>
              Matched pairs merge into a single canonical room (longest name wins,
              amenities unioned, attributes re-extracted from the merged text). Rooms
              with no cross-supplier partner become their own canonical room rather than
              being dropped — a hotel page should show every real room, matched or not.
            </p>
          </Sub>
        </Section>

        <Section index="05" title="Optional LLM adjudication">
          <p>
            The heuristic passes above resolve the overwhelming majority of pairs at $0.
            <code className="text-zinc-300"> pipeline/llm_adjudicate.py</code> adds a
            narrow, opt-in pass over only the genuinely ambiguous residue.
          </p>
          <Sub title="Selection & cost discipline">
            <p>
              A near-miss qualifies only if it's geographically plausible
              (geo_score ≥ 0.45) <em>and</em> ambiguous on name evidence
              (0.30 ≤ name_score &lt; 0.85) — not so low the heuristic is already
              confident it's a different hotel, not so high the property-number veto's
              own escape hatch already resolved it. Capped at 200 pairs per run,
              prioritized by closeness to the 0.5 "coin flip" zone, batched 20-per-request
              against <code className="text-zinc-300">gpt-oss-120b</code> on Cerebras's
              free tier (OpenAI-API-compatible, so the standard <code className="text-zinc-300">
              openai</code> SDK talks to it directly).
            </p>
          </Sub>
          <Sub title="Caching, fail-soft, provenance">
            <p>
              Every request/response is cached by pair in{" "}
              <code className="text-zinc-300">pipeline/cache/llm_adjudications.json</code>
              , committed to the repo — a re-run, or grading this without a key at all,
              reproduces the exact same result at $0. No key and no cache means the
              pipeline logs a message and continues at $0; a malformed model response for
              one batch is skipped, never crashes the run or fabricates a match.
              Confirmed matches are folded back into the existing hotel graph and tagged{" "}
              <code className="text-zinc-300">match_method: "llm"</code> with the model's
              one-line rationale stored alongside it, auditable everywhere in the API.
            </p>
            <p>
              For this build: 97 near-miss pairs considered, 15 promoted, 11,413 prompt +
              17,685 completion tokens, real cost <strong className="text-zinc-200">
              $0.00</strong> (free-tier pricing) — computed from actual token usage, not
              estimated.
            </p>
          </Sub>
        </Section>

        <Section index="06" title="Persistence & the API">
          <Sub title="Storage">
            <p>
              Everything lands in one SQLite file (<code className="text-zinc-300">
              canonical.db</code>): <code className="text-zinc-300">raw_hotels</code>/
              <code className="text-zinc-300">raw_rooms</code> keep the verbatim,
              per-supplier records for provenance;{" "}
              <code className="text-zinc-300">canonical_hotels</code>/
              <code className="text-zinc-300">canonical_rooms</code> hold the merged
              output with match status, confidence, method, and a JSON map of which
              supplier IDs fed each record; <code className="text-zinc-300">
              near_misses</code> keeps every rejected-but-plausible candidate; an FTS5
              virtual table indexes hotel name + address for full-text search. A parallel{" "}
              <code className="text-zinc-300">canonical_hotels.json</code> mirrors the
              same data nested, for anyone who wants the whole dataset without touching
              SQL.
            </p>
          </Sub>
          <Sub title="Serving">
            <p>
              FastAPI serves that database <strong className="text-zinc-200">
              read-only</strong> (connections opened <code className="text-zinc-300">
              mode=ro</code>) — it never recomputes a match at request time, so every
              response is fast and deterministic, and a missing DB fails fast with a 503
              instead of silently creating an empty one. Every response carries an{" "}
              <code className="text-zinc-300">X-Request-ID</code> header for tracing,
              unhandled errors return a clean generic 500 (never leaking internals or a
              stack trace to the client), and a basic per-IP rate limiter and CORS
              allow-list are both environment-configurable.
            </p>
          </Sub>
        </Section>

        <Section index="07" title="Frontend & admin panel">
          <p>
            The UI is a thin, read-only client of that API — no matching logic runs in
            the browser. It lists and searches canonical hotels, and a detail page shows
            the merged record, the verbatim source record from each supplier side by
            side, every room with its extracted attributes and match status, and the
            near-miss candidates the matcher considered but rejected for that hotel.
          </p>
          <p>
            An optional admin panel (gated behind a server-checked API key, disabled
            entirely — not defaulted to a guessable password — until one is configured)
            lets you upload a new supplier's CSV or XLSX, see the currently staged data
            files, and trigger a full pipeline re-run, without touching a terminal.
          </p>
        </Section>

        <Section index="08" title="Built on">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <Pill name="Python 3.12 · pandas" note="CSV loading + cleaning" />
            <Pill name="Qdrant + FastEmbed" note="in-process semantic search" />
            <Pill name="NetworkX" note="one-to-one graph matching" />
            <Pill name="Cerebras (gpt-oss-120b)" note="bounded, cached adjudication" />
            <Pill name="FastAPI" note="read-only JSON API" />
            <Pill name="SQLite + FTS5" note="canonical storage + search" />
            <Pill name="React + TypeScript" note="UI, Vite + Tailwind v4" />
          </div>
        </Section>

        <Section index="09" title="Why these choices">
          <p>
            <strong className="text-zinc-200">Honesty over false confidence.</strong>{" "}
            Every hotel and room carries a real match confidence and a method
            (geo-matched, rescued, LLM-adjudicated, or single-source) — nothing is
            reported as matched without evidence, and rejected candidates are kept as
            visible near-misses instead of silently discarded.
          </p>
          <p>
            <strong className="text-zinc-200">Cost discipline.</strong> The default
            pipeline run costs $0 — no LLM calls at all. The optional adjudication pass
            is deliberately narrow: a few hundred pairs where a cheap model with the raw
            evidence in front of it beats more string-matching cleverness, not a bulk
            pass over everything.
          </p>
          <p>
            <strong className="text-zinc-200">Correctness over cleverness.</strong> A
            few real bugs surfaced along the way — a matching step that claimed a
            stronger guarantee than the code actually enforced, a room-matching module
            that was built but never wired in — and got fixed rather than shipped
            quietly. The full reasoning, real numbers, and what would change at 200,000
            hotels are in the repo's <code className="text-zinc-300">WRITEUP.md</code>.
          </p>
        </Section>

        <footer className="flex flex-col items-start gap-4 border-t border-zinc-800 py-14 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-zinc-500">Ready to look at the actual canonical layer?</p>
          <Link
            to="/app"
            className="group inline-flex items-center gap-1.5 rounded-full bg-cyan-400 px-4 py-2 text-sm font-semibold text-zinc-950 transition hover:bg-cyan-300"
          >
            Try it out
            <span className="transition-transform group-hover:translate-x-0.5">→</span>
          </Link>
        </footer>
      </main>
    </div>
  );
}
