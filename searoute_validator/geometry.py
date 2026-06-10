"""Leg geometry: sampling a leg into vertices, measuring distance, and
handling the antimeridian (SPEC §2.3, §2.4, §3.2).

The public entry point is :func:`sample_leg`, which turns two ``(lon, lat)``
endpoints into a densely sampled polyline that approximates the configured
"straight line" (geodesic by default). :func:`split_antimeridian` then breaks
that polyline wherever it jumps across ±180° so the downstream shapely land
test never draws a segment the wrong way around the globe.
"""
from __future__ import annotations

import math
from typing import List, Tuple

from pyproj import Geod

from . import config

Point = Tuple[float, float]  # (lon, lat)

_GEOD = Geod(ellps="WGS84")


def geodesic_distance_km(start: Point, end: Point) -> float:
    """Great-circle distance between two ``(lon, lat)`` points, in kilometres."""
    lon1, lat1 = start
    lon2, lat2 = end
    _, _, dist_m = _GEOD.inv(lon1, lat1, lon2, lat2)
    return dist_m / 1000.0


def _n_segments(distance_km: float, sample_km: float) -> int:
    """Number of segments needed so no segment exceeds ``sample_km``."""
    if distance_km <= 0 or sample_km <= 0:
        return 1
    return max(1, math.ceil(distance_km / sample_km))


def _sample_geodesic(start: Point, end: Point, n_segments: int) -> List[Point]:
    """Vertices along the great circle, endpoints included."""
    lon1, lat1 = start
    lon2, lat2 = end
    points: List[Point] = [(lon1, lat1)]
    if n_segments > 1:
        # npts returns only the intermediate points (excludes both endpoints).
        inter = _GEOD.npts(lon1, lat1, lon2, lat2, n_segments - 1)
        points.extend((lon, lat) for lon, lat in inter)
    points.append((lon2, lat2))
    return points


def _normalise_lon_delta(lon1: float, lon2: float) -> float:
    """Return lon2 adjusted so the step from lon1 takes the short way round.

    Keeps a rhumb/linear leg from wrapping the long way across the globe when
    it crosses the antimeridian (SPEC §2.4).
    """
    delta = lon2 - lon1
    if delta > 180:
        delta -= 360
    elif delta < -180:
        delta += 360
    return lon1 + delta


def _sample_linear(start: Point, end: Point, n_segments: int) -> List[Point]:
    """Equirectangular interpolation in lon/lat space (antimeridian-aware)."""
    lon1, lat1 = start
    lon2, lat2 = end
    lon2_adj = _normalise_lon_delta(lon1, lon2)
    points: List[Point] = []
    for i in range(n_segments + 1):
        t = i / n_segments
        lon = lon1 + (lon2_adj - lon1) * t
        lat = lat1 + (lat2 - lat1) * t
        points.append((_wrap_lon(lon), lat))
    return points


def _sample_rhumb(start: Point, end: Point, n_segments: int) -> List[Point]:
    """Constant-bearing (rhumb) line sampled at equal distance steps.

    Uses pyproj to walk along a fixed azimuth so the result matches what a
    straight ``L.polyline`` looks like on a Web-Mercator map (SPEC §2.3).
    """
    lon1, lat1 = start
    lon2, lat2 = end
    # Mercator-projected latitudes give the constant rhumb bearing.
    psi1 = _merc_lat(lat1)
    psi2 = _merc_lat(lat2)
    dlon = math.radians(_normalise_lon_delta(lon1, lon2) - lon1)
    bearing = math.atan2(dlon, psi2 - psi1)

    total_km = _rhumb_distance_km(start, end)
    points: List[Point] = []
    for i in range(n_segments + 1):
        d_km = total_km * (i / n_segments)
        points.append(_rhumb_point(lon1, lat1, bearing, d_km))
    return points


def _merc_lat(lat_deg: float) -> float:
    lat = math.radians(lat_deg)
    lat = max(min(lat, math.radians(89.9)), math.radians(-89.9))
    return math.log(math.tan(math.pi / 4 + lat / 2))


def _rhumb_distance_km(start: Point, end: Point) -> float:
    lon1, lat1 = start
    lon2, lat2 = end
    r = 6371.0088  # mean Earth radius, km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlon = math.radians(_normalise_lon_delta(lon1, lon2) - lon1)
    dpsi = _merc_lat(lat2) - _merc_lat(lat1)
    q = dphi / dpsi if abs(dpsi) > 1e-12 else math.cos(phi1)
    return math.hypot(dphi, q * dlon) * r


def _rhumb_point(lon: float, lat: float, bearing: float, dist_km: float) -> Point:
    r = 6371.0088
    delta = dist_km / r
    phi1 = math.radians(lat)
    dphi = delta * math.cos(bearing)
    phi2 = phi1 + dphi
    dpsi = math.log(math.tan(math.pi / 4 + phi2 / 2) / math.tan(math.pi / 4 + phi1 / 2))
    q = dphi / dpsi if abs(dpsi) > 1e-12 else math.cos(phi1)
    dlon = delta * math.sin(bearing) / q
    lon2 = lon + math.degrees(dlon)
    return (_wrap_lon(lon2), math.degrees(phi2))


def _wrap_lon(lon: float) -> float:
    """Normalise a longitude into [-180, 180]."""
    return ((lon + 180) % 360) - 180


def sample_leg(start: Point, end: Point):
    """Sample a leg into a polyline of ``(lon, lat)`` vertices.

    Returns ``(points, distance_km)``. ``points`` always includes both
    endpoints and respects ``config.SAMPLE_KM`` spacing. The geometry mode is
    taken from ``config.GEOMETRY``.
    """
    distance_km = geodesic_distance_km(start, end)
    n = _n_segments(distance_km, config.SAMPLE_KM)

    mode = config.GEOMETRY
    if mode == "linear":
        points = _sample_linear(start, end, n)
    elif mode == "rhumb":
        points = _sample_rhumb(start, end, n)
        distance_km = _rhumb_distance_km(start, end)
    else:  # geodesic (default)
        points = _sample_geodesic(start, end, n)

    return points, distance_km


def split_antimeridian(points: List[Point]) -> List[List[Point]]:
    """Split a polyline wherever consecutive vertices jump across ±180°.

    A crossing vertex pair (longitude step > 180°) is split into two segments,
    inserting the interpolated crossing point at the ±180° boundary on both
    sides so each resulting segment is geometrically continuous in lon/lat
    space (SPEC §2.4).
    """
    if len(points) < 2:
        return [points] if points else []

    segments: List[List[Point]] = []
    current: List[Point] = [points[0]]

    for (lon1, lat1), (lon2, lat2) in zip(points, points[1:]):
        if abs(lon2 - lon1) > 180:
            # Crossing the antimeridian. Find the latitude at ±180.
            # Unwrap lon2 to be continuous with lon1, interpolate to the edge.
            lon2_unwrapped = lon2 + (360 if lon2 < lon1 else -360)
            edge = 180.0 if lon2_unwrapped > lon1 else -180.0
            t = (edge - lon1) / (lon2_unwrapped - lon1)
            lat_edge = lat1 + (lat2 - lat1) * t
            current.append((edge, lat_edge))
            segments.append(current)
            # Start the next segment on the opposite edge.
            current = [(-edge, lat_edge), (lon2, lat2)]
        else:
            current.append((lon2, lat2))

    segments.append(current)
    return segments
