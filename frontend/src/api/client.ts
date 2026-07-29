import type { HotelDetail, HotelListResponse, MatchStatus, StatsResponse } from "./types";

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`);
  } catch {
    throw new ApiError(0, "Can't reach the API. Is the backend running?");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore parse failure */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export interface ListHotelsParams {
  search?: string;
  limit?: number;
  offset?: number;
  match_status?: MatchStatus | "";
}

export function listHotels(params: ListHotelsParams): Promise<HotelListResponse> {
  const qs = new URLSearchParams();
  if (params.search) qs.set("search", params.search);
  qs.set("limit", String(params.limit ?? 20));
  qs.set("offset", String(params.offset ?? 0));
  if (params.match_status) qs.set("match_status", params.match_status);
  return request<HotelListResponse>(`/hotels?${qs.toString()}`);
}

export function getHotel(id: string): Promise<HotelDetail> {
  return request<HotelDetail>(`/hotels/${encodeURIComponent(id)}`);
}

export function getStats(): Promise<StatsResponse> {
  return request<StatsResponse>("/stats");
}

export { API_BASE };
