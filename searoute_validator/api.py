"""High-level Python API for the Sea Route Validator.

Import this module for direct use without running the HTTP server::

    from app.api import validate_leg, validate_route, is_on_land

Coordinates are always ``(lat, lon)`` named arguments — the same order as
every map library and the HTTP request bodies.  The land index is loaded
lazily on first call and reused for the lifetime of the process.

Examples
--------
>>> from app.api import validate_leg, validate_route, is_on_land
>>> validate_leg(lat1=40, lon1=-30, lat2=30, lon2=-40)
LegResult(valid=True, reason=None, distance_km=1434.6, ...)
>>> is_on_land(lat=51.5, lon=-0.13)
True
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from . import validator
from .validator import LegResult  # re-exported for callers


def is_on_land(*, lat: float, lon: float) -> bool:
    """Return ``True`` if the point is on land.

    Parameters
    ----------
    lat:
        Latitude in decimal degrees, WGS84 (−90 … 90).
    lon:
        Longitude in decimal degrees, WGS84 (−180 … 180).
    """
    return validator.get_index().is_on_land(lon, lat)


def validate_leg(
    *,
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> LegResult:
    """Validate a single leg between two points.

    A leg is invalid if the start is on land, the end is on land, or the
    straight line between them crosses land.

    Parameters
    ----------
    lat1, lon1:
        Start point in decimal degrees, WGS84.
    lat2, lon2:
        End point in decimal degrees, WGS84.

    Returns
    -------
    :class:`~app.validator.LegResult`
        ``result.valid`` is ``True`` iff the leg is navigable.
        ``result.reason`` is one of ``"start_on_land"``, ``"end_on_land"``,
        ``"line_crosses_land"``, or ``None`` when valid.
        ``result.distance_km`` is the geodesic distance.
        ``result.points`` is the list of ``(lon, lat)`` sampled vertices.
    """
    return validator.validate_leg((lon1, lat1), (lon2, lat2))


def validate_route(
    waypoints: List[Tuple[float, float]],
    *,
    stop_on_first: bool = False,
) -> Tuple[List[LegResult], Optional[int]]:
    """Validate consecutive legs of a multi-point route.

    Parameters
    ----------
    waypoints:
        Ordered list of ``(lat, lon)`` tuples.  Must contain at least 2 points.
    stop_on_first:
        If ``True``, stop evaluating after the first invalid leg.

    Returns
    -------
    legs : list of :class:`~app.validator.LegResult`
        One entry per evaluated leg.
    first_invalid : int or None
        Index of the first failing leg, or ``None`` if the route is valid.

    Examples
    --------
    >>> legs, first_invalid = validate_route([(51.9, 4.5), (36.1, -5.4), (40.6, -74.0)])
    >>> first_invalid
    0
    """
    # Convert (lat, lon) → internal (lon, lat) convention.
    coords = [(lon, lat) for lat, lon in waypoints]
    return validator.validate_route(coords, stop_on_first=stop_on_first)
