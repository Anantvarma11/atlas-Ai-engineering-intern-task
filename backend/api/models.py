"""Pydantic response models for the canonical hotels API."""

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────────
# Shared / nested
# ──────────────────────────────────────────────────────────────────────────────

class RawSupplierHotel(BaseModel):
    id: str
    name: str
    address: str
    lat: float | None
    lon: float | None
    stars: float | None
    amenities: list[str]
    image_urls: list[str]


class RawSupplierRoom(BaseModel):
    id: str
    name: str
    amenities: list[str]


class CanonicalRoom(BaseModel):
    id: str = Field(..., description="Canonical room ID (CAN-RM-XXXXXX)")
    name: str
    bed_type: str | None = Field(None, description="King / Queen / Twin / Double / Single / Suite")
    occupancy: str | None = Field(None, description="Single / Double / Triple / Family")
    meal_plan: str = Field("Room Only", description="Room Only / Breakfast / Half Board / Full Board")
    view: str | None = Field(None, description="City / Pool / Garden / Sea / Mountain / Courtyard")
    is_smoking: bool | None = None
    amenities: list[str]
    match_status: str = Field(..., description="matched | a_only | b_only")
    match_confidence: float = Field(..., ge=0.0, le=1.0)
    supplier_a_room: RawSupplierRoom | None = None
    supplier_b_room: RawSupplierRoom | None = None


class NearMiss(BaseModel):
    supplier: str = Field(..., description="Which supplier the candidate belongs to: 'a' or 'b'")
    supplier_id: str
    name: str
    address: str
    confidence: float
    geo_score: float
    name_score: float


# ──────────────────────────────────────────────────────────────────────────────
# List endpoint
# ──────────────────────────────────────────────────────────────────────────────

class HotelSummary(BaseModel):
    id: str = Field(..., description="Canonical hotel ID (CAN-XXXXX)")
    name: str
    address: str
    lat: float | None
    lon: float | None
    stars: float | None
    amenities: list[str]
    image_urls: list[str]
    match_status: str = Field(..., description="matched | a_only | b_only")
    match_confidence: float = Field(..., ge=0.0, le=1.0)
    match_method: str = Field(..., description="geo_fuzzy | rescue | llm | singleton")
    match_note: str | None = Field(None, description="LLM adjudication rationale, when match_method='llm'")
    supplier_a_id: str | None
    supplier_b_id: str | None


class HotelListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    has_more: bool
    hotels: list[HotelSummary]


# ──────────────────────────────────────────────────────────────────────────────
# Detail endpoint
# ──────────────────────────────────────────────────────────────────────────────

class HotelSources(BaseModel):
    supplier_a: RawSupplierHotel | None = None
    supplier_b: RawSupplierHotel | None = None


class HotelDetail(BaseModel):
    id: str
    name: str
    address: str
    lat: float | None
    lon: float | None
    stars: float | None
    amenities: list[str]
    image_urls: list[str]
    match_status: str
    match_confidence: float
    match_method: str
    match_note: str | None = None
    supplier_a_id: str | None
    supplier_b_id: str | None

    sources: HotelSources = Field(..., description="Verbatim source records from each supplier")
    rooms: list[CanonicalRoom] = Field(
        default_factory=list,
        description="Canonical rooms with matched/unmatched status and structured attributes",
    )
    near_misses: list[NearMiss] = Field(
        default_factory=list,
        description="Sub-threshold candidates from the other supplier that were considered but not matched",
    )
