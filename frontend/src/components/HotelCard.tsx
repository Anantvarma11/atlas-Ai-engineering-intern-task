import { Link } from "react-router-dom";
import type { HotelSummary } from "../api/types";
import { MatchBadge } from "./MatchBadge";
import { ConfidenceRing } from "./ConfidenceRing";
import { firstImage, formatStars } from "../lib/format";

export function HotelCard({ hotel, index = 0 }: { hotel: HotelSummary; index?: number }) {
  const image = firstImage(hotel.image_urls);

  return (
    <Link
      to={`/hotels/${hotel.id}`}
      className="group animate-fade-up flex flex-col overflow-hidden rounded-2xl bg-white shadow-[var(--shadow-card)] ring-1 ring-ink-100 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[var(--shadow-card-hover)]"
      style={{ animationDelay: `${Math.min(index, 12) * 30}ms` }}
    >
      <div className="relative aspect-[4/3] w-full overflow-hidden bg-ink-100">
        {image ? (
          <img
            src={image}
            loading="lazy"
            alt={hotel.name}
            className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).style.display = "none";
            }}
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-ink-300">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h1m4 0h1m-6 4h1m4 0h1m-6 4h1m4 0h1" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
        )}
        <div className="absolute left-3 top-3">
          <MatchBadge status={hotel.match_status} className="bg-white/95 shadow-sm ring-0" />
        </div>
        <div className="absolute right-3 top-3 rounded-full bg-white/95 p-1 shadow-sm">
          <ConfidenceRing value={hotel.match_confidence} size={30} stroke={3} />
        </div>
        {hotel.stars !== null && (
          <div className="absolute bottom-3 left-3 rounded-full bg-ink-950/70 px-2 py-0.5 text-xs font-semibold text-white backdrop-blur-sm">
            {formatStars(hotel.stars)}
          </div>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-1.5 p-4">
        <h3 className="line-clamp-1 font-semibold text-ink-900" title={hotel.name}>
          {hotel.name}
        </h3>
        <p className="line-clamp-1 text-sm text-ink-500">{hotel.address || "Address unavailable"}</p>

        {hotel.amenities.length > 0 && (
          <div className="mt-1 flex flex-wrap gap-1">
            {hotel.amenities.slice(0, 3).map((a) => (
              <span key={a} className="rounded-md bg-ink-50 px-1.5 py-0.5 text-[11px] text-ink-500 ring-1 ring-inset ring-ink-100">
                {a}
              </span>
            ))}
            {hotel.amenities.length > 3 && (
              <span className="rounded-md px-1.5 py-0.5 text-[11px] text-ink-400">+{hotel.amenities.length - 3}</span>
            )}
          </div>
        )}

        <div className="mt-auto flex items-center justify-between pt-3 text-[11px] text-ink-400">
          <span className="font-mono">{hotel.id}</span>
          <span className="flex items-center gap-1">
            {hotel.supplier_a_id && <span className="rounded bg-blue-50 px-1.5 py-0.5 font-medium text-blue-600">A</span>}
            {hotel.supplier_b_id && <span className="rounded bg-violet-50 px-1.5 py-0.5 font-medium text-violet-600">B</span>}
          </span>
        </div>
      </div>
    </Link>
  );
}

export function HotelCardSkeleton() {
  return (
    <div className="flex flex-col overflow-hidden rounded-2xl bg-white ring-1 ring-ink-100">
      <div className="animate-shimmer aspect-[4/3] w-full" />
      <div className="flex flex-col gap-2 p-4">
        <div className="animate-shimmer h-4 w-3/4 rounded" />
        <div className="animate-shimmer h-3 w-full rounded" />
        <div className="animate-shimmer mt-2 h-3 w-1/2 rounded" />
      </div>
    </div>
  );
}
