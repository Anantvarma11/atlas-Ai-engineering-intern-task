import type { MatchMethod, MatchStatus } from "../api/types";

export function pct(n: number): string {
  return `${Math.round(n * 100)}%`;
}

export const MATCH_STATUS_LABEL: Record<MatchStatus, string> = {
  matched: "Matched",
  singleton: "Single source",
};

export const MATCH_METHOD_LABEL: Record<MatchMethod, string> = {
  geo_fuzzy: "Geo + fuzzy name",
  rescue: "Rescue pass",
  llm: "LLM adjudicated",
  singleton: "Single source",
};

export function formatStars(stars: number | null): string {
  if (stars === null) return "Unrated";
  return `${stars % 1 === 0 ? stars.toFixed(0) : stars.toFixed(1)}★`;
}

export function firstImage(urls: string[]): string | null {
  return urls.length > 0 ? urls[0] : null;
}
