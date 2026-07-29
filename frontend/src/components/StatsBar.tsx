import type { StatsResponse } from "../api/types";

function StatTile({
  label,
  value,
  sub,
  accent = "ink",
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: "ink" | "emerald" | "blue" | "violet" | "ember";
}) {
  const accentMap: Record<string, string> = {
    ink: "text-ink-900",
    emerald: "text-emerald-600",
    blue: "text-blue-600",
    violet: "text-violet-600",
    ember: "text-ember-600",
  };
  return (
    <div className="flex min-w-[130px] flex-1 flex-col gap-0.5 rounded-xl bg-white px-4 py-3 ring-1 ring-ink-100">
      <span className="text-[11px] font-medium uppercase tracking-wide text-ink-400">{label}</span>
      <span className={`text-xl font-bold tabular-nums ${accentMap[accent]}`}>{value}</span>
      {sub && <span className="text-xs text-ink-400">{sub}</span>}
    </div>
  );
}

export function StatsBar({ stats, loading }: { stats: StatsResponse | null; loading: boolean }) {
  if (loading || !stats) {
    return (
      <div className="flex flex-wrap gap-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="animate-shimmer h-[64px] min-w-[130px] flex-1 rounded-xl" />
        ))}
      </div>
    );
  }

  const totalHotels = Object.values(stats.hotels).reduce((a, b) => a + b, 0);
  const matched = stats.hotels.matched ?? 0;
  const matchRate = totalHotels ? matched / totalHotels : 0;
  const totalRooms = Object.values(stats.rooms).reduce((a, b) => a + b, 0);
  const spend = stats.llm_spend;

  return (
    <div className="flex flex-wrap gap-3">
      <StatTile label="Canonical hotels" value={totalHotels.toLocaleString()} sub={`${matched.toLocaleString()} matched`} />
      <StatTile label="Match rate" value={`${Math.round(matchRate * 100)}%`} accent="emerald" sub="both suppliers" />
      <StatTile label="Supplier A only" value={(stats.hotels.a_only ?? 0).toLocaleString()} accent="blue" />
      <StatTile label="Supplier B only" value={(stats.hotels.b_only ?? 0).toLocaleString()} accent="violet" />
      <StatTile label="Canonical rooms" value={totalRooms.toLocaleString()} sub={`${(stats.rooms.matched ?? 0).toLocaleString()} matched`} />
      <StatTile
        label="LLM spend"
        value={spend ? `$${spend.lifetime_cost_usd.toFixed(4)}` : "$0.00"}
        accent="ember"
        sub={spend ? `${spend.lifetime_pairs_adjudicated} pairs adjudicated` : "not run"}
      />
    </div>
  );
}
