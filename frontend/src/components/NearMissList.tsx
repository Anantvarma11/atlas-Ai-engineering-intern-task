import type { NearMiss } from "../api/types";
import { pct } from "../lib/format";

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-16 flex-shrink-0 text-[11px] text-ink-400">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-100">
        <div className="h-full rounded-full bg-ink-400" style={{ width: pct(value) }} />
      </div>
      <span className="w-9 flex-shrink-0 text-right text-[11px] tabular-nums text-ink-500">{pct(value)}</span>
    </div>
  );
}

export function NearMissList({ items }: { items: NearMiss[] }) {
  if (items.length === 0) return null;

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {items.map((n) => (
        <div key={`${n.supplier}-${n.supplier_id}`} className="rounded-xl bg-white p-4 ring-1 ring-ink-100">
          <div className="mb-2 flex items-start justify-between gap-2">
            <div>
              <p className="text-sm font-medium text-ink-900">{n.name || <span className="italic text-ink-400">unnamed</span>}</p>
              <p className="text-xs text-ink-400">{n.address}</p>
            </div>
            <span
              className={`flex-shrink-0 rounded-full px-2 py-0.5 text-[11px] font-bold text-white ${
                n.supplier === "a" ? "bg-blue-500" : "bg-violet-500"
              }`}
            >
              {n.supplier.toUpperCase()}
            </span>
          </div>
          <div className="flex flex-col gap-1.5">
            <ScoreBar label="Overall" value={n.confidence} />
            <ScoreBar label="Geo" value={n.geo_score} />
            <ScoreBar label="Name" value={n.name_score} />
          </div>
        </div>
      ))}
    </div>
  );
}
