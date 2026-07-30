import type { RawSupplierHotel } from "../api/types";
import { formatStars } from "../lib/format";

// A small color palette generator for dynamic suppliers
const COLORS = [
  { ring: "ring-blue-100", chip: "bg-blue-500", head: "text-blue-700 bg-blue-50" },
  { ring: "ring-violet-100", chip: "bg-violet-500", head: "text-violet-700 bg-violet-50" },
  { ring: "ring-emerald-100", chip: "bg-emerald-500", head: "text-emerald-700 bg-emerald-50" },
  { ring: "ring-amber-100", chip: "bg-amber-500", head: "text-amber-700 bg-amber-50" },
  { ring: "ring-rose-100", chip: "bg-rose-500", head: "text-rose-700 bg-rose-50" },
];

function SourceCard({ label, hotel, index }: { label: string; hotel: RawSupplierHotel; index: number }) {
  const theme = COLORS[index % COLORS.length];

  return (
    <div className={`flex-1 rounded-xl bg-white p-4 ring-1 ring-inset ${theme.ring} min-w-[280px]`}>
      <div className="mb-3 flex items-center justify-between">
        <span className={`flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ${theme.head}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${theme.chip}`} />
          {label}
        </span>
        <span className="font-mono text-[11px] text-ink-400">{hotel.id}</span>
      </div>
      <p className="mb-1 font-medium text-ink-900">{hotel.name || <span className="italic text-ink-400">no name</span>}</p>
      <p className="mb-2 text-sm text-ink-500">{hotel.address || <span className="italic text-ink-400">no address</span>}</p>
      <div className="mb-2 flex flex-wrap gap-3 text-xs text-ink-500">
        <span>{formatStars(hotel.stars)}</span>
        {hotel.lat !== null && hotel.lon !== null && (
          <span className="font-mono">
            {hotel.lat.toFixed(4)}, {hotel.lon.toFixed(4)}
          </span>
        )}
        <span>{hotel.image_urls.length} photo{hotel.image_urls.length === 1 ? "" : "s"}</span>
      </div>
      {hotel.amenities.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {hotel.amenities.slice(0, 6).map((a) => (
            <span key={a} className="rounded-md bg-ink-50 px-1.5 py-0.5 text-[11px] text-ink-500 ring-1 ring-inset ring-ink-100">
              {a}
            </span>
          ))}
          {hotel.amenities.length > 6 && <span className="text-[11px] text-ink-400">+{hotel.amenities.length - 6} more</span>}
        </div>
      )}
    </div>
  );
}

export function ProvenancePanel({ sources }: { sources: Record<string, RawSupplierHotel> }) {
  const entries = Object.entries(sources);
  if (entries.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-ink-200 p-6 text-center text-sm text-ink-500">
        No provenance records found.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 sm:flex-row overflow-x-auto pb-4">
      {entries.map(([supp, hotel], i) => (
        <SourceCard key={supp} label={supp} hotel={hotel} index={i} />
      ))}
    </div>
  );
}
