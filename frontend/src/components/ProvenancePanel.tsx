import type { RawSupplierHotel } from "../api/types";
import { formatStars } from "../lib/format";

function SourceCard({ label, color, hotel }: { label: string; color: "blue" | "violet"; hotel: RawSupplierHotel | null }) {
  const theme =
    color === "blue"
      ? { ring: "ring-blue-100", chip: "bg-blue-500", head: "text-blue-700 bg-blue-50" }
      : { ring: "ring-violet-100", chip: "bg-violet-500", head: "text-violet-700 bg-violet-50" };

  if (!hotel) {
    return (
      <div className={`flex flex-1 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-ink-200 p-6 text-center`}>
        <span className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold text-white ${theme.chip}`}>
          {label}
        </span>
        <p className="text-sm text-ink-400">No record from this supplier</p>
      </div>
    );
  }

  return (
    <div className={`flex-1 rounded-xl bg-white p-4 ring-1 ring-inset ${theme.ring}`}>
      <div className="mb-3 flex items-center justify-between">
        <span className={`flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ${theme.head}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${theme.chip}`} />
          Supplier {label}
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

export function ProvenancePanel({ a, b }: { a: RawSupplierHotel | null; b: RawSupplierHotel | null }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row">
      <SourceCard label="A" color="blue" hotel={a} />
      <SourceCard label="B" color="violet" hotel={b} />
    </div>
  );
}
