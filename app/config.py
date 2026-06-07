"""Runtime configuration for the Sea Route Validator.

Every value is a sensible default that can be overridden with an environment
variable, so behaviour can be retuned without touching logic
(see SPEC §2.3, §3.1, §3.2).
"""
from __future__ import annotations

import os
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

# Path to the vendored Natural Earth land polygons and the navigable corridors.
LAND_GEOJSON = Path(os.getenv("LAND_GEOJSON", DATA_DIR / "land_10m.geojson"))
CHANNELS_GEOJSON = Path(os.getenv("CHANNELS_GEOJSON", DATA_DIR / "channels.geojson"))

# Human-readable name reported by /health.
LAND_DATASET = os.getenv("LAND_DATASET", "natural_earth_10m")

# How the "straight line" between two points is interpreted (SPEC §2.3).
#   geodesic -> great-circle path on the WGS84 ellipsoid (default, recommended)
#   rhumb    -> constant-bearing line (looks straight on a Mercator map)
#   linear   -> naive equirectangular interpolation in lon/lat space
GEOMETRY = os.getenv("GEOMETRY", "geodesic").lower()

# Maximum spacing between sampled vertices along a leg, in kilometres
# (SPEC §3.2). Smaller = more accurate, more points per request.
SAMPLE_KM = float(os.getenv("SAMPLE_KM", "25"))

# Backend for the point-on-land check (SPEC §3.1).
#   shapely  -> exact point-in-polygon against the vendored land data (default)
#   landmask -> global-land-mask raster lookup (faster, approximate)
POINT_BACKEND = os.getenv("POINT_BACKEND", "shapely").lower()
