export type MatchStatus = "matched" | "a_only" | "b_only";
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
  supplier_a_room: RawSupplierRoom | null;
  supplier_b_room: RawSupplierRoom | null;
}

export interface NearMiss {
  supplier: "a" | "b";
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
  supplier_a_id: string | null;
  supplier_b_id: string | null;
}

export interface HotelListResponse {
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  hotels: HotelSummary[];
}

export interface HotelSources {
  supplier_a: RawSupplierHotel | null;
  supplier_b: RawSupplierHotel | null;
}

export interface HotelDetail extends Omit<HotelSummary, never> {
  sources: HotelSources;
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
