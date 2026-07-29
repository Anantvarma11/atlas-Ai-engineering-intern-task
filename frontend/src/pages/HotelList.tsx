import { useEffect, useState } from "react";
import { ApiError, getStats, listHotels } from "../api/client";
import type { HotelListResponse, MatchStatus, StatsResponse } from "../api/types";
import { StatsBar } from "../components/StatsBar";
import { SearchControls } from "../components/SearchControls";
import { HotelCard, HotelCardSkeleton } from "../components/HotelCard";
import { Pagination } from "../components/Pagination";

const LIMIT = 24;

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

export function HotelList() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<MatchStatus | "">("");
  const [offset, setOffset] = useState(0);

  const debouncedQuery = useDebounced(query, 300);

  const [data, setData] = useState<HotelListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);

  useEffect(() => {
    setOffset(0);
  }, [debouncedQuery, status]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listHotels({ search: debouncedQuery, limit: LIMIT, offset, match_status: status })
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Something went wrong.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery, status, offset]);

  useEffect(() => {
    getStats()
      .then(setStats)
      .catch(() => setStats(null))
      .finally(() => setStatsLoading(false));
  }, []);

  function handleStatusChange(next: MatchStatus | "") {
    setStatus(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function handleOffsetChange(next: number) {
    setOffset(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <div className="mx-auto max-w-6xl px-4 pb-20 pt-8 sm:px-6">
      <div className="mb-8 animate-fade-up">
        <h1 className="font-display text-3xl font-semibold text-ink-900 sm:text-4xl">
          One record per hotel,<span className="text-ember-500"> stitched from two suppliers.</span>
        </h1>
        <p className="mt-2 max-w-2xl text-[15px] text-ink-500">
          Browse the canonical layer: merged hotel content, full source provenance, and honest match confidence — no
          duplicates, no silent guesses.
        </p>
      </div>

      <div className="mb-6">
        <StatsBar stats={stats} loading={statsLoading} />
      </div>

      <div className="sticky top-[65px] z-10 -mx-4 mb-6 bg-ink-50/95 px-4 py-3 backdrop-blur-md sm:mx-0 sm:rounded-2xl sm:px-4">
        <SearchControls query={query} onQueryChange={setQuery} status={status} onStatusChange={handleStatusChange} />
      </div>

      {error && (
        <div className="mb-6 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-200">
          <strong className="font-semibold">Couldn't load hotels.</strong> {error}
        </div>
      )}

      {!error && data && !loading && data.hotels.length === 0 && (
        <div className="flex flex-col items-center gap-2 rounded-2xl bg-white py-20 text-center ring-1 ring-ink-100">
          <span className="text-3xl">🔍</span>
          <p className="font-medium text-ink-700">No hotels match your search.</p>
          <p className="text-sm text-ink-400">Try a different name, address fragment, or filter.</p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {loading
          ? Array.from({ length: LIMIT }).map((_, i) => <HotelCardSkeleton key={i} />)
          : data?.hotels.map((h, i) => <HotelCard key={h.id} hotel={h} index={i} />)}
      </div>

      {!loading && data && data.total > 0 && (
        <div className="mt-8">
          <Pagination offset={offset} limit={LIMIT} total={data.total} onChange={handleOffsetChange} />
        </div>
      )}
    </div>
  );
}
