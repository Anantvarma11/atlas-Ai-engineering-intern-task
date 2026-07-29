import { useState } from "react";
import type { CanonicalRoom } from "../api/types";
import { MatchBadge } from "./MatchBadge";
import { ConfidenceRing } from "./ConfidenceRing";

function Attr({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <span className="inline-flex items-center gap-1 rounded-md bg-ink-50 px-2 py-1 text-xs font-medium text-ink-600 ring-1 ring-inset ring-ink-100">
      <span className="text-ink-400">{label}</span>
      {value}
    </span>
  );
}

function RawRoomChip({ label, color, name }: { label: string; color: "blue" | "violet"; name: string | undefined }) {
  if (!name) return null;
  const cls = color === "blue" ? "bg-blue-50 text-blue-700" : "bg-violet-50 text-violet-700";
  return (
    <div className="flex items-start gap-1.5 text-xs">
      <span className={`mt-0.5 flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full text-[9px] font-bold ${cls}`}>
        {label}
      </span>
      <span className="text-ink-500">{name}</span>
    </div>
  );
}

function RoomRow({ room }: { room: CanonicalRoom }) {
  return (
    <div className="rounded-xl bg-white p-4 ring-1 ring-ink-100">
      <div className="mb-2.5 flex items-start justify-between gap-3">
        <div>
          <p className="font-medium text-ink-900">{room.name}</p>
          <p className="font-mono text-[11px] text-ink-400">{room.id}</p>
        </div>
        <div className="flex flex-shrink-0 items-center gap-2">
          <MatchBadge status={room.match_status} />
          <ConfidenceRing value={room.match_confidence} size={30} stroke={3} />
        </div>
      </div>

      <div className="mb-3 flex flex-wrap gap-1.5">
        <Attr label="Bed" value={room.bed_type} />
        <Attr label="Sleeps" value={room.occupancy} />
        <Attr label="Meal" value={room.meal_plan} />
        <Attr label="View" value={room.view} />
        {room.is_smoking !== null && <Attr label="" value={room.is_smoking ? "Smoking" : "Non-smoking"} />}
      </div>

      {(room.supplier_a_room || room.supplier_b_room) && (
        <div className="flex flex-col gap-1 border-t border-dashed border-ink-100 pt-2.5">
          <RawRoomChip label="A" color="blue" name={room.supplier_a_room?.name} />
          <RawRoomChip label="B" color="violet" name={room.supplier_b_room?.name} />
        </div>
      )}
    </div>
  );
}

export function RoomsList({ rooms }: { rooms: CanonicalRoom[] }) {
  const [filter, setFilter] = useState<"all" | "matched" | "unmatched">("all");

  if (rooms.length === 0) {
    return <p className="rounded-xl bg-white p-6 text-center text-sm text-ink-400 ring-1 ring-ink-100">No room data for this hotel.</p>;
  }

  const filtered = rooms.filter((r) => {
    if (filter === "all") return true;
    if (filter === "matched") return r.match_status === "matched";
    return r.match_status !== "matched";
  });

  const matchedCount = rooms.filter((r) => r.match_status === "matched").length;

  return (
    <div>
      <div className="mb-3 flex gap-1.5">
        {[
          { key: "all", label: `All (${rooms.length})` },
          { key: "matched", label: `Matched (${matchedCount})` },
          { key: "unmatched", label: `Unmatched (${rooms.length - matchedCount})` },
        ].map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key as typeof filter)}
            className={`rounded-full px-3 py-1 text-xs font-semibold transition ${
              filter === f.key ? "bg-ink-900 text-white" : "bg-white text-ink-500 ring-1 ring-inset ring-ink-100 hover:bg-ink-50"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {filtered.map((r) => (
          <RoomRow key={r.id} room={r} />
        ))}
      </div>
    </div>
  );
}
