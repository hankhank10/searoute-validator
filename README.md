# Sea Route Validator

A FastAPI microservice that validates whether sea routes are navigable. It answers one question: **can a ship sail this line without hitting land?**

Validation uses exact Shapely vector geometry against vendored [Natural Earth 1:10m](https://www.naturalearthdata.com/) land polygons. Legs are traced as great-circle (geodesic) paths via pyproj. Hand-curated navigable corridors for Suez, Panama, Bosphorus/Dardanelles, Kiel, Gibraltar, Malacca, and the Danish straits are subtracted from the land layer so ships can transit them.

---

## Install & run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"        # runtime only: pip install -e ".[server]"
uvicorn searoute_validator.main:app --reload
```

| URL | What |
|-----|------|
| http://127.0.0.1:8000/ | Interactive Leaflet demo map |
| http://127.0.0.1:8000/docs | OpenAPI docs (FastAPI auto-generated) |
| http://127.0.0.1:8000/health | Health check |

## Tests

```bash
pytest
```

27 tests.

---

## API

**Key semantic:** an unnavigable route returns **HTTP 200 with `"valid": false`** — not an HTTP error. 4xx is reserved for malformed input (422 for bad body / out-of-range coordinates; 400 `{"error":"route_needs_two_points"}` for fewer than 2 waypoints or identical adjacent points).

### POST /leg

Validate a single leg between two points.

```bash
curl -s localhost:8000/leg -H 'content-type: application/json' \
  -d '{"start":{"lat":40,"lon":-30},"end":{"lat":30,"lon":-40}}'
```

**Request body**

```json
{
  "start": { "lat": 40, "lon": -30 },
  "end":   { "lat": 30, "lon": -40 }
}
```

**Response**

```json
{
  "valid": true,
  "reason": null,
  "detail": "The route is valid.",
  "checks": {
    "start_on_land": false,
    "end_on_land": false,
    "line_crosses_land": false
  },
  "distance_km": 1372.5,
  "geometry": {
    "type": "LineString",
    "coordinates": [[-30, 40], "…sampled geodesic vertices…", [-40, 30]]
  }
}
```

`reason` is `null` when valid, otherwise the first failing check: `start_on_land`, `end_on_land`, or `line_crosses_land`. `checks` always reports all three. Add `?geometry=false` to omit the `geometry` field.

### POST /route

Validate an ordered list of 2+ waypoints.

```bash
curl -s localhost:8000/route -H 'content-type: application/json' \
  -d '{"waypoints":[{"lat":51.9,"lon":4.5},{"lat":36.1,"lon":-5.4},{"lat":40.6,"lon":-74.0}]}'
```

**Request body**

```json
{
  "waypoints": [
    { "lat": 51.9, "lon":   4.5 },
    { "lat": 36.1, "lon":  -5.4 },
    { "lat": 40.6, "lon": -74.0 }
  ]
}
```

**Response**

```json
{
  "valid": false,
  "leg_count": 2,
  "first_invalid_leg": 0,
  "legs": [ "…per-leg objects identical to /leg responses…" ],
  "total_distance_km": 7512.3
}
```

All legs are evaluated by default so the UI can colour the whole route. Add `?stop_on_first=true` to short-circuit after the first invalid leg.

### GET /health

```bash
curl -s localhost:8000/health
# {"status":"ok","land_dataset":"natural_earth_10m"}
```

---

## Configuration

All options are environment variables; everything has a sensible default.

| Variable | Default | Description |
|----------|---------|-------------|
| `GEOMETRY` | `geodesic` | How the leg line is interpreted: `geodesic` (great circle), `rhumb`, or `linear`. |
| `SAMPLE_KM` | `25` | Maximum vertex spacing (km) along a sampled leg. Smaller = more accurate at narrow passages. |
| `POINT_BACKEND` | `shapely` | `shapely` for exact vector checks; `landmask` for faster approximate raster checks (requires `pip install -e ".[landmask]"`). |
| `LAND_GEOJSON` | *(bundled)* | Path to an alternative land polygon GeoJSON. |
| `CHANNELS_GEOJSON` | *(bundled)* | Path to an alternative channels GeoJSON. |
| `LAND_DATASET` | `natural_earth_10m` | Name reported by `/health`. |

---

## Project layout

```
app/
  main.py           FastAPI app, routes, static mount
  models.py         Pydantic request/response schemas
  validator.py      core land / line-crossing logic + land-data loading
  geometry.py       geodesic sampling, antimeridian handling
  config.py         env-var-driven config
  data/
    land_10m.geojson    vendored Natural Earth land (~10 MB, committed)
    channels.geojson    navigable corridors
scripts/
  fetch_land.py         (re)download the land GeoJSON
  build_channels.py     regenerate channels.geojson from curated centre-lines
web/
  index.html            Leaflet demo (all-in-one, no build step)
tests/
  test_validator.py
pyproject.toml
```

To add or adjust a canal/strait corridor, edit `scripts/build_channels.py` and run:

```bash
python -m scripts.build_channels
```

---

## Data & licensing

- **Natural Earth 1:10m land** — public domain; no attribution required.
- **OpenStreetMap tiles** (demo basemap only) — ODbL; "© OpenStreetMap contributors" attribution is shown on the map.
- **shapely**, **pyproj** — BSD/MIT; permissive.

---

## Limitations

- Approximate accuracy, not navigation-grade. Coastal precision is roughly 1 km (bounded by the 1:10m source data).
- Some large inland water bodies (Caspian Sea, large lakes) may read as land depending on the dataset layer.
- Canal corridors only open a passage when the leg's straight line actually runs through them. For tight canals, add the canal entrance/exit as an explicit waypoint rather than trying to thread it in one long leg.
