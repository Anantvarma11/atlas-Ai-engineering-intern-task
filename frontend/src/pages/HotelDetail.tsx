import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, getHotel } from "../api/client";
import type { HotelDetail as HotelDetailType } from "../api/types";
import { MatchBadge } from "../components/MatchBadge";
import { ConfidenceRing } from "../components/ConfidenceRing";
import { Gallery } from "../components/Gallery";
import { ProvenancePanel } from "../components/ProvenancePanel";
import { RoomsList } from "../components/RoomsList";
import { NearMissList } from "../components/NearMissList";
import { MATCH_METHOD_LABEL, formatStars } from "../lib/format";

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <div className="mb-3">
        <h2 className="font-display text-xl font-semibold text-ink-900">{title}</h2>
        {subtitle && <p className="text-sm text-ink-500">{subtitle}</p>}
      </div>
      {children}
    </section>
  );
}

export function HotelDetail() {
  const { id } = useParams<{ id: string }>();
  const [hotel, setHotel] = useState<HotelDetailType | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getHotel(id)
      .then((res) => {
        if (!cancelled) setHotel(res);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          if (err instanceof ApiError) setError({ status: err.status, message: err.message });
          else setError({ status: 0, message: "Something went wrong." });
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
        <div className="animate-shimmer mb-6 h-4 w-32 rounded" />
        <div className="animate-shimmer aspect-[16/9] w-full rounded-2xl" />
        <div className="animate-shimmer mt-6 h-8 w-2/3 rounded" />
        <div className="animate-shimmer mt-3 h-4 w-1/2 rounded" />
      </div>
    );
  }

  if (error || !hotel) {
    return (
      <div className="mx-auto max-w-5xl px-4 py-20 text-center sm:px-6">
        <p className="text-4xl">{error?.status === 404 ? "🏨" : "⚠️"}</p>
        <h1 className="mt-4 text-xl font-semibold text-ink-900">
          {error?.status === 404 ? "Hotel not found" : "Couldn't load this hotel"}
        </h1>
        <p className="mt-2 text-sm text-ink-500">{error?.message}</p>
        <Link
          to="/"
          className="mt-6 inline-flex items-center gap-1.5 rounded-lg bg-ink-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-ink-800"
        >
          ← Back to search
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-4 pb-24 pt-6 sm:px-6">
      <Link to="/" className="mb-5 inline-flex items-center gap-1.5 text-sm font-medium text-ink-500 transition hover:text-ink-900">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M19 12H5m0 0 7 7m-7-7 7-7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Back to search
      </Link>

      <div className="animate-fade-up">
        <Gallery images={hotel.image_urls} name={hotel.name} />
      </div>

      <div className="mt-6 flex animate-fade-up flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-display text-2xl font-semibold text-ink-900 sm:text-3xl">{hotel.name}</h1>
            {hotel.stars !== null && (
              <span className="rounded-full bg-ember-50 px-2 py-0.5 text-sm font-semibold text-ember-600">
                {formatStars(hotel.stars)}
              </span>
            )}
          </div>
          <p className="mt-1 text-ink-500">{hotel.address || "Address unavailable"}</p>
          {hotel.lat !== null && hotel.lon !== null && (
            <p className="mt-0.5 font-mono text-xs text-ink-400">
              {hotel.lat.toFixed(5)}, {hotel.lon.toFixed(5)}
            </p>
          )}
        </div>

        <div className="flex flex-shrink-0 items-center gap-3 rounded-xl bg-white p-3 ring-1 ring-ink-100">
          <ConfidenceRing value={hotel.match_confidence} size={44} stroke={4} />
          <div className="flex flex-col gap-1">
            <MatchBadge status={hotel.match_status} />
            <span className="text-xs text-ink-400">{MATCH_METHOD_LABEL[hotel.match_method]}</span>
          </div>
        </div>
      </div>

      {hotel.match_note && (
        <div className="mt-4 flex animate-fade-up gap-2 rounded-xl bg-ember-50 p-3 text-sm text-ember-700 ring-1 ring-inset ring-ember-100">
          <span>🤖</span>
          <p>
            <strong className="font-semibold">LLM rationale:</strong> {hotel.match_note}
          </p>
        </div>
      )}

      {hotel.amenities.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-1.5">
          {hotel.amenities.map((a) => (
            <span key={a} className="rounded-lg bg-white px-2.5 py-1 text-xs font-medium text-ink-600 ring-1 ring-inset ring-ink-100">
              {a}
            </span>
          ))}
        </div>
      )}

      <Section title="Source provenance" subtitle="Verbatim records from each supplier, before merging.">
        <ProvenancePanel a={hotel.sources.supplier_a} b={hotel.sources.supplier_b} />
      </Section>

      <Section
        title="Rooms"
        subtitle={`${hotel.rooms.length} canonical room${hotel.rooms.length === 1 ? "" : "s"} with normalized attributes and per-match confidence.`}
      >
        <RoomsList rooms={hotel.rooms} />
      </Section>

      {hotel.near_misses.length > 0 && (
        <Section
          title="Near misses"
          subtitle="Candidates from the other supplier that were close but fell below the match threshold."
        >
          <NearMissList items={hotel.near_misses} />
        </Section>
      )}
    </div>
  );
}
