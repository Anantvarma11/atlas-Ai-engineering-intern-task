import type { MatchStatus } from "../api/types";
import { MATCH_STATUS_LABEL } from "../lib/format";

const STYLES: Record<MatchStatus, string> = {
  matched: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  singleton: "bg-blue-50 text-blue-700 ring-blue-600/20",
};

const DOT: Record<MatchStatus, string> = {
  matched: "bg-emerald-500",
  singleton: "bg-blue-500",
};

export function MatchBadge({ status, className = "" }: { status: MatchStatus; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${STYLES[status]} ${className}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${DOT[status]}`} />
      {MATCH_STATUS_LABEL[status]}
    </span>
  );
}
