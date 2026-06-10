"""Pydantic v2 request/response models and coordinate validation
(SPEC §5)."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# The three failure reasons, in the order they are evaluated (SPEC §5.1).
Reason = Literal["start_on_land", "end_on_land", "line_crosses_land"]


class Coordinate(BaseModel):
    """A WGS84 decimal-degree coordinate. Out-of-range values raise 422."""

    lat: float = Field(..., ge=-90, le=90, description="Latitude in [-90, 90]")
    lon: float = Field(..., ge=-180, le=180, description="Longitude in [-180, 180]")

    def as_lonlat(self) -> tuple[float, float]:
        return (self.lon, self.lat)


class Checks(BaseModel):
    """All three boolean checks, always reported so a client can highlight the
    exact problem (SPEC §5.1)."""

    start_on_land: bool
    end_on_land: bool
    line_crosses_land: bool


class LegRequest(BaseModel):
    start: Coordinate
    end: Coordinate


class LegResponse(BaseModel):
    valid: bool
    reason: Optional[Reason] = None
    detail: str
    checks: Checks
    distance_km: float
    # GeoJSON LineString of the sampled leg; suppressed with ?geometry=false.
    geometry: Optional[dict] = None


class RouteRequest(BaseModel):
    # NB: the >= 2 length rule is enforced in the handler so it returns 400
    # (not Pydantic's 422), per SPEC §5.3.
    waypoints: List[Coordinate]


class RouteLeg(BaseModel):
    index: int
    start: Coordinate
    end: Coordinate
    valid: bool
    reason: Optional[Reason] = None
    checks: Checks
    distance_km: float


class RouteResponse(BaseModel):
    valid: bool
    leg_count: int
    first_invalid_leg: Optional[int] = None
    legs: List[RouteLeg]
    total_distance_km: float
