"""Tests for the Sea Route Validator (SPEC §5, §7).

Geometry assertions use well-known ocean/land points so they exercise the real
vendored Natural Earth data and corridors.
"""
import math

import pytest
from fastapi.testclient import TestClient

from app import geometry, validator
from app.main import app

# Well-known points (lon, lat).
ATLANTIC_A = (-30.0, 40.0)
ATLANTIC_B = (-40.0, 30.0)
TYRRHENIAN = (11.0, 40.0)   # west of Italy
ADRIATIC = (17.0, 42.0)     # east of Italy
MADRID = (-3.70, 40.40)     # on land
SAHARA = (10.0, 25.0)       # on land
LONDON = (-0.13, 51.50)     # on land


@pytest.fixture(scope="module")
def index():
    validator._INDEX = None
    return validator.load_land_index()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# --- geometry -------------------------------------------------------------

def test_sample_leg_includes_endpoints():
    pts, dist = geometry.sample_leg(ATLANTIC_A, ATLANTIC_B)
    assert pts[0] == ATLANTIC_A
    assert pts[-1] == ATLANTIC_B
    assert dist > 0


def test_sample_spacing_respects_sample_km():
    from app import config
    pts, _ = geometry.sample_leg(ATLANTIC_A, ATLANTIC_B)
    for a, b in zip(pts, pts[1:]):
        step = geometry.geodesic_distance_km(a, b)
        # Allow a little slack for the final, evenly-divided segment.
        assert step <= config.SAMPLE_KM + 1.0


def test_distance_is_reasonable():
    # London-ish to New York-ish great circle is ~5570 km.
    d = geometry.geodesic_distance_km((-0.13, 51.5), (-74.0, 40.7))
    assert 5400 < d < 5700


def test_antimeridian_split():
    # A leg straddling +180/-180 must split into two continuous segments.
    pts = [(170.0, 0.0), (179.0, 0.0), (-179.0, 0.0), (-170.0, 0.0)]
    segs = geometry.split_antimeridian(pts)
    assert len(segs) == 2
    # Each segment is continuous (no >180 jump within it).
    for seg in segs:
        for a, b in zip(seg, seg[1:]):
            assert abs(a[0] - b[0]) <= 180


def test_no_split_when_not_crossing():
    pts = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    assert len(geometry.split_antimeridian(pts)) == 1


# --- point checks ---------------------------------------------------------

def test_ocean_points_not_land(index):
    assert index.is_on_land(*ATLANTIC_A) is False
    assert index.is_on_land(*ATLANTIC_B) is False


def test_land_points_on_land(index):
    assert index.is_on_land(*MADRID) is True
    assert index.is_on_land(*SAHARA) is True
    assert index.is_on_land(*LONDON) is True


# --- leg validation -------------------------------------------------------

def test_open_ocean_leg_valid():
    r = validator.validate_leg(ATLANTIC_A, ATLANTIC_B)
    assert r.valid
    assert r.reason is None


def test_leg_crossing_italy_invalid():
    r = validator.validate_leg(TYRRHENIAN, ADRIATIC)
    assert not r.valid
    assert r.reason == "line_crosses_land"
    assert r.line_crosses_land


def test_start_on_land():
    r = validator.validate_leg(MADRID, ATLANTIC_A)
    assert not r.valid
    assert r.reason == "start_on_land"
    assert r.start_on_land


def test_end_on_land():
    r = validator.validate_leg(ATLANTIC_A, MADRID)
    assert not r.valid
    assert r.reason == "end_on_land"
    assert r.end_on_land


def test_antimeridian_open_leg_valid():
    # Open Pacific around the dateline — must not be reported as crossing land.
    r = validator.validate_leg((170.0, 0.0), (-170.0, 0.0))
    assert r.valid


# --- canal/strait corridors (SPEC §3.3) -----------------------------------

def test_panama_corridor_open():
    r = validator.validate_leg((-79.92, 9.45), (-79.55, 8.80))
    assert r.valid, "Panama canal corridor should allow passage"


def test_suez_corridor_open():
    r = validator.validate_leg((32.30, 31.50), (32.60, 29.70))
    assert r.valid, "Suez canal corridor should allow passage"


def test_gibraltar_corridor_open():
    r = validator.validate_leg((-6.50, 35.90), (-3.00, 36.20))
    assert r.valid


# --- route validation -----------------------------------------------------

def test_route_all_valid():
    results, first = validator.validate_route([ATLANTIC_A, ATLANTIC_B, (-50.0, 25.0)])
    assert first is None
    assert all(r.valid for r in results)


def test_route_first_invalid():
    results, first = validator.validate_route([TYRRHENIAN, ADRIATIC, ATLANTIC_A])
    assert first == 0


# --- API ------------------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "land_dataset": "natural_earth_10m"}


def test_api_leg_valid(client):
    r = client.post("/leg", json={
        "start": {"lat": 40.0, "lon": -30.0},
        "end": {"lat": 30.0, "lon": -40.0},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is True
    assert body["reason"] is None
    assert body["geometry"]["type"] == "LineString"
    assert body["checks"] == {
        "start_on_land": False, "end_on_land": False, "line_crosses_land": False
    }


def test_api_leg_invalid(client):
    r = client.post("/leg", json={
        "start": {"lat": 40.0, "lon": 11.0},
        "end": {"lat": 42.0, "lon": 17.0},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["valid"] is False
    assert body["reason"] == "line_crosses_land"


def test_api_leg_geometry_suppressed(client):
    r = client.post("/leg?geometry=false", json={
        "start": {"lat": 40.0, "lon": -30.0},
        "end": {"lat": 30.0, "lon": -40.0},
    })
    assert r.json()["geometry"] is None


def test_api_leg_identical_points_400(client):
    r = client.post("/leg", json={
        "start": {"lat": 40.0, "lon": -30.0},
        "end": {"lat": 40.0, "lon": -30.0},
    })
    assert r.status_code == 400
    assert r.json() == {"error": "route_needs_two_points"}


def test_api_leg_out_of_range_422(client):
    r = client.post("/leg", json={
        "start": {"lat": 100.0, "lon": -30.0},
        "end": {"lat": 30.0, "lon": -40.0},
    })
    assert r.status_code == 422


def test_api_route_eager(client):
    r = client.post("/route", json={"waypoints": [
        {"lat": 40.0, "lon": 11.0},
        {"lat": 42.0, "lon": 17.0},
        {"lat": 40.0, "lon": -30.0},
    ]})
    assert r.status_code == 200
    body = r.json()
    assert body["leg_count"] == 2
    assert body["first_invalid_leg"] == 0
    assert body["valid"] is False
    assert len(body["legs"]) == 2  # eager: all legs evaluated


def test_api_route_stop_on_first(client):
    r = client.post("/route?stop_on_first=true", json={"waypoints": [
        {"lat": 40.0, "lon": 11.0},
        {"lat": 42.0, "lon": 17.0},
        {"lat": 40.0, "lon": -30.0},
    ]})
    body = r.json()
    assert body["leg_count"] == 2  # route still has 2 legs
    assert len(body["legs"]) == 1  # but only the first was evaluated


def test_api_route_too_few_waypoints_400(client):
    r = client.post("/route", json={"waypoints": [{"lat": 40.0, "lon": -30.0}]})
    assert r.status_code == 400
    assert r.json() == {"error": "route_needs_two_points"}


def test_api_route_total_distance(client):
    r = client.post("/route", json={"waypoints": [
        {"lat": 40.0, "lon": -30.0},
        {"lat": 30.0, "lon": -40.0},
        {"lat": 25.0, "lon": -50.0},
    ]})
    body = r.json()
    expected = sum(leg["distance_km"] for leg in body["legs"])
    assert math.isclose(body["total_distance_km"], round(expected, 1), abs_tol=0.2)
