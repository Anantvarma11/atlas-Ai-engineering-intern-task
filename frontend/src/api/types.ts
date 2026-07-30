export type MatchStatus = "matched" | "singleton";
export type MatchMethod = "geo_fuzzy" | "rescue" | "llm" | "singleton";

export interface RawSupplierHotel {
  id: string;
  name: string;
  address: string;
  lat: number | null;
  lon: number | null;
  stars: number | null;
  amenities: string[];
  image_urls: string[];
}

export interface RawSupplierRoom {
  id: string;
  name: string;
  amenities: string[];
}

export interface CanonicalRoom {
  id: string;
  name: string;
  bed_type: string | null;
  occupancy: string | null;
  meal_plan: string;
  view: string | null;
  is_smoking: boolean | null;
  amenities: string[];
  match_status: MatchStatus;
  match_confidence: number;
  sources: Record<string, RawSupplierRoom>;
}

export interface NearMiss {
  supplier: string;
  supplier_id: string;
  name: string;
  address: string;
  confidence: number;
  geo_score: number;
  name_score: number;
}

export interface HotelSummary {
  id: string;
  name: string;
  address: string;
  lat: number | null;
  lon: number | null;
  stars: number | null;
  amenities: string[];
  image_urls: string[];
  match_status: MatchStatus;
  match_confidence: number;
  match_method: MatchMethod;
  match_note: string | null;
  source_ids: Record<string, string>;
}

export interface HotelListResponse {
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  hotels: HotelSummary[];
}

export interface HotelDetail extends Omit<HotelSummary, never> {
  sources: Record<string, RawSupplierHotel>;
  rooms: CanonicalRoom[];
  near_misses: NearMiss[];
}

export interface StatsResponse {
  hotels: Record<string, number>;
  hotels_by_match_method: Record<string, number>;
  rooms: Record<string, number>;
  near_misses: number;
  llm_spend: {
    lifetime_pairs_adjudicated: number;
    lifetime_prompt_tokens: number;
    lifetime_completion_tokens: number;
    lifetime_cost_usd: number;
  } | null;
}
