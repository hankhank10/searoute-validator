"""FastAPI application: endpoints, static demo mount, and startup wiring
(SPEC §5, §6)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, validator
from .models import (
    Checks,
    Coordinate,
    LegRequest,
    LegResponse,
    RouteLeg,
    RouteRequest,
    RouteResponse,
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Shared 400 body for degenerate routes/legs (SPEC §5.3).
_ROUTE_NEEDS_TWO_POINTS = JSONResponse(
    status_code=400, content={"error": "route_needs_two_points"}
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the land polygons + spatial index once, before serving (SPEC §3.4).
    validator.load_land_index()
    yield


app = FastAPI(
    title="Sea Route Validator",
    description="Validates whether sea routes are navigable.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for external clients (the bundled demo is same-origin) (SPEC §6).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _same_point(a: Coordinate, b: Coordinate) -> bool:
    return a.lat == b.lat and a.lon == b.lon


def _checks(result: validator.LegResult) -> Checks:
    return Checks(
        start_on_land=result.start_on_land,
        end_on_land=result.end_on_land,
        line_crosses_land=result.line_crosses_land,
    )


@app.post("/leg", response_model=LegResponse)
def validate_leg(
    body: LegRequest,
    geometry: bool = Query(True, description="Include the sampled geometry."),
):
    """Validate a single leg between two points (SPEC §5.1)."""
    if _same_point(body.start, body.end):
        return _ROUTE_NEEDS_TWO_POINTS

    result = validator.validate_leg(body.start.as_lonlat(), body.end.as_lonlat())
    return LegResponse(
        valid=result.valid,
        reason=result.reason,
        detail=result.detail,
        checks=_checks(result),
        distance_km=result.distance_km,
        geometry=result.geometry() if geometry else None,
    )


@app.post("/route", response_model=RouteResponse)
def validate_route(
    body: RouteRequest,
    stop_on_first: bool = Query(
        False, description="Short-circuit at the first invalid leg."
    ),
):
    """Validate a multi-leg route (SPEC §5.2)."""
    waypoints = body.waypoints
    if len(waypoints) < 2:
        return _ROUTE_NEEDS_TWO_POINTS
    # Reject any degenerate (zero-length) leg.
    for a, b in zip(waypoints, waypoints[1:]):
        if _same_point(a, b):
            return _ROUTE_NEEDS_TWO_POINTS

    coords = [w.as_lonlat() for w in waypoints]
    results, first_invalid = validator.validate_route(coords, stop_on_first=stop_on_first)

    legs = [
        RouteLeg(
            index=i,
            start=waypoints[i],
            end=waypoints[i + 1],
            valid=r.valid,
            reason=r.reason,
            checks=_checks(r),
            distance_km=r.distance_km,
        )
        for i, r in enumerate(results)
    ]
    total = round(sum(r.distance_km for r in results), 1)
    # The route is valid iff every evaluated leg is valid AND we evaluated them
    # all (stop_on_first may leave later legs unchecked, but a route is only
    # "valid" when no invalid leg was found).
    valid = first_invalid is None

    return RouteResponse(
        valid=valid,
        leg_count=len(waypoints) - 1,
        first_invalid_leg=first_invalid,
        legs=legs,
        total_distance_km=total,
    )


@app.get("/health")
def health():
    return {"status": "ok", "land_dataset": config.LAND_DATASET}


# Serve the Leaflet demo (and its assets) from the same process. Mounted last
# so it doesn't shadow the API routes or /docs (SPEC §6).
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
