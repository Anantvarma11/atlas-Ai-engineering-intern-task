import type { MatchStatus } from "../api/types";

const FILTERS: { value: MatchStatus | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "matched", label: "Matched" },
  { value: "singleton", label: "Single source" },
];

export function SearchControls({
  query,
  onQueryChange,
  status,
  onStatusChange,
}: {
  query: string;
  onQueryChange: (v: string) => void;
  status: MatchStatus | "";
  onStatusChange: (v: MatchStatus | "") => void;
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="relative w-full sm:max-w-md">
        <svg
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400"
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
        >
          <circle cx="11" cy="11" r="7" />
          <path d="m21 21-4.35-4.35" strokeLinecap="round" />
        </svg>
        <input
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Search by hotel name or address…"
          className="w-full rounded-xl border-0 bg-white py-2.5 pl-10 pr-4 text-sm text-ink-900 shadow-[var(--shadow-card)] ring-1 ring-ink-100 outline-none transition placeholder:text-ink-400 focus:ring-2 focus:ring-ember-400"
        />
      </div>

      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => onStatusChange(f.value)}
            className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${
              status === f.value
                ? "bg-ink-900 text-white shadow-sm"
                : "bg-white text-ink-500 ring-1 ring-inset ring-ink-100 hover:bg-ink-50"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>
    </div>
  );
}
