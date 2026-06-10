"""Core validation logic: load land data once, then answer point-on-land and
line-crosses-land questions (SPEC §3, §7).

The source of truth is an exact shapely vector test against Natural Earth land
polygons, with navigable canal/strait corridors subtracted so ships can pass
through Suez, Panama, etc. (SPEC §3.3). An ``STRtree`` spatial index keeps the
per-request work small even though the land geometry has many polygons.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional, Tuple

import shapely
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

from . import config, geometry
from .geometry import Point as LonLat

# Plain-English detail strings keyed by the machine reason (SPEC §5.1).
DETAILS = {
    "start_on_land": "The start point is on land.",
    "end_on_land": "The end point is on land.",
    "line_crosses_land": "The straight line between the points crosses land.",
    None: "Leg is navigable.",
}


@dataclass
class LegResult:
    """Outcome of validating one leg, before serialisation."""

    start: LonLat  # (lon, lat)
    end: LonLat
    start_on_land: bool
    end_on_land: bool
    line_crosses_land: bool
    distance_km: float
    points: List[LonLat]  # sampled leg vertices

    @property
    def valid(self) -> bool:
        return not (self.start_on_land or self.end_on_land or self.line_crosses_land)

    @property
    def reason(self) -> Optional[str]:
        # First failure in start -> end -> line order sets the reason.
        if self.start_on_land:
            return "start_on_land"
        if self.end_on_land:
            return "end_on_land"
        if self.line_crosses_land:
            return "line_crosses_land"
        return None

    @property
    def detail(self) -> str:
        return DETAILS[self.reason]

    def geometry(self) -> dict:
        return {
            "type": "LineString",
            "coordinates": [[lon, lat] for lon, lat in self.points],
        }


class LandIndex:
    """Holds the prepared land geometry and spatial index (SPEC §3.4)."""

    def __init__(self, parts: List, landmask_globe=None):
        # ``parts`` is the list of individual land polygons that make up the
        # effective (corridor-subtracted) land geometry.
        self._parts = parts
        self._tree = STRtree(parts)
        self._globe = landmask_globe  # optional global-land-mask backend

    # -- point check (SPEC §3.1) -------------------------------------------
    def is_on_land(self, lon: float, lat: float) -> bool:
        if config.POINT_BACKEND == "landmask" and self._globe is not None:
            return bool(self._globe.is_land(lat, lon))
        pt = Point(lon, lat)
        return self._tree.query(pt, predicate="intersects").size > 0

    # -- line check (SPEC §3.2) --------------------------------------------
    def line_crosses_land(self, points: List[LonLat]) -> bool:
        # Split at the antimeridian so no segment wraps the globe (SPEC §2.4).
        for segment in geometry.split_antimeridian(points):
            if len(segment) < 2:
                continue
            line = LineString(segment)
            if self._tree.query(line, predicate="intersects").size > 0:
                return True
        return False


# Module-level singleton, populated by load_land_index() at startup.
_INDEX: Optional[LandIndex] = None


def load_land_index() -> LandIndex:
    """Build the land index from the vendored GeoJSON. Idempotent."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX

    land_geoms = _load_geometries(config.LAND_GEOJSON)
    land_union = unary_union(land_geoms)

    if config.CHANNELS_GEOJSON.exists():
        channel_geoms = _load_geometries(config.CHANNELS_GEOJSON)
        if channel_geoms:
            channels_union = unary_union(channel_geoms)
            # Subtract navigable corridors from land once at startup (SPEC §3.3).
            land_union = land_union.difference(channels_union)

    parts = _explode(land_union)

    globe = None
    if config.POINT_BACKEND == "landmask":
        try:
            from global_land_mask import globe as globe  # type: ignore
        except ImportError:
            globe = None

    _INDEX = LandIndex(parts, landmask_globe=globe)
    return _INDEX


def get_index() -> LandIndex:
    if _INDEX is None:
        return load_land_index()
    return _INDEX


def _load_geometries(path) -> List:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    geoms = []
    if data.get("type") == "FeatureCollection":
        for feature in data["features"]:
            geom = feature.get("geometry")
            if geom is not None:
                geoms.append(shape(geom))
    elif data.get("type") == "Feature":
        geoms.append(shape(data["geometry"]))
    else:  # bare geometry
        geoms.append(shape(data))
    return geoms


def _explode(geom) -> List:
    """Flatten a (possibly Multi) geometry into a list of simple polygons."""
    if geom.is_empty:
        return []
    if geom.geom_type.startswith("Multi") or geom.geom_type == "GeometryCollection":
        return [g for g in geom.geoms if not g.is_empty]
    return [geom]


# -- public API ------------------------------------------------------------

def validate_leg(start: LonLat, end: LonLat) -> LegResult:
    """Validate a single leg given ``(lon, lat)`` endpoints (SPEC §7)."""
    index = get_index()
    points, distance_km = geometry.sample_leg(start, end)

    # All three checks always run so `checks` reports every boolean (SPEC §5.1).
    start_on_land = index.is_on_land(*start)
    end_on_land = index.is_on_land(*end)
    line_crosses = index.line_crosses_land(points)

    return LegResult(
        start=start,
        end=end,
        start_on_land=start_on_land,
        end_on_land=end_on_land,
        line_crosses_land=line_crosses,
        distance_km=round(distance_km, 1),
        points=points,
    )


def validate_route(
    waypoints: List[LonLat], stop_on_first: bool = False
) -> Tuple[List[LegResult], Optional[int]]:
    """Validate consecutive legs of a route (SPEC §5.2).

    Returns ``(leg_results, first_invalid_index)``. Evaluation is eager unless
    ``stop_on_first`` is set, in which case it short-circuits at the first
    invalid leg.
    """
    results: List[LegResult] = []
    first_invalid: Optional[int] = None
    for i in range(len(waypoints) - 1):
        result = validate_leg(waypoints[i], waypoints[i + 1])
        results.append(result)
        if not result.valid and first_invalid is None:
            first_invalid = i
            if stop_on_first:
                break
    return results, first_invalid
