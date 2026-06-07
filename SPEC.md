# Sea Route Validator — Technical Specification

A microservice API that validates whether sea routes are navigable. It answers
one question: *can a ship sail this line without hitting land?*

This document covers library research, the chosen approach, the API contract,
and the demo web page. **No implementation code is written yet** — this is the
spec only.

---

## 1. Problem statement

The service validates user-drawn shipping routes.

- **`POST /leg`** — given a start `(lat, lon)` and end `(lat, lon)`, return
  whether the single leg is valid. A leg is **invalid** if:
  1. the start point is on land, **or**
  2. the end point is on land, **or**
  3. the straight line between them crosses land.
- **`POST /route`** — given an ordered list of ≥2 waypoints (a multi-leg
  journey), return whether the whole route is valid. The route is valid iff
  *every* leg is valid.

This is a **lightweight** validator, not a navigational tool. Realism is "good
enough to feel right on a world map," not safety-critical. That framing drives
several trade-offs below (e.g. we don't model territorial waters, canals, tides,
or ship draft).

---

## 2. Library & data research

### 2.1 Candidate libraries

| Library | What it does | Fit for us |
|---|---|---|
| [`searoute`](https://pypi.org/project/searoute/) ([repo](https://github.com/genthalili/searoute-py)) | Computes the **shortest** sea route between two points over a pre-built maritime graph. Returns GeoJSON. | **Not a validator.** It *finds* a route and snaps land points to the nearest sea node — it never reports "invalid." It also can't test whether an arbitrary straight line crosses land. Useful later for a "suggest a real route" feature, but wrong tool for validation. |
| [`global-land-mask`](https://pypi.org/project/global-land-mask/) ([repo](https://github.com/toddkarin/global-land-mask)) | `globe.is_land(lat, lon)` / `is_ocean(lat, lon)` against the GLOBE 1 km raster grid. Vectorised (NumPy), ~2.5 MB packaged, no network calls. | **Strong fit for point checks and line sampling.** Fast enough to test thousands of points along a line per request. Caveat: treats most **lakes as land** (fine — we want ocean-only) and is raster, so ~1 km coastal accuracy. |
| [`shapely`](https://shapely.readthedocs.io/) + land polygons | Vector geometry. `LineString(...).intersects(land)` gives an **exact** line-vs-land test, no sampling gaps. | **Strong fit for the line-crossing check.** Needs land polygons (below) and a spatial index for speed. |
| [Natural Earth](https://www.naturalearthdata.com/) land vectors (1:10m) | Public-domain land/coastline polygons at 10m/50m/110m scales. Ships as shapefile/GeoJSON. | **Recommended polygon source.** 1:10m is a good accuracy/size balance for this use case. |
| [GSHHG](https://www.soest.hawaii.edu/pwessel/gshhg/) | Higher-resolution, hierarchical shoreline DB used by oceanographers (via `cartopy.feature.GSHHSFeature`). | Higher fidelity than Natural Earth but heavier. Overkill here; keep as an upgrade path. |
| [`pyproj`](https://pyproj4.github.io/pyproj/stable/api/geod.html) (`Geod`) | Geodesic math — great-circle interpolation, true distances on the WGS84 ellipsoid. | Used to interpolate sample points along a great circle and to report leg distance. |
| [`cartopy`](https://scitools.org.uk/cartopy/) | Wraps Natural Earth + GSHHG feature access and plotting. | Convenient data accessor, but pulls a heavy plotting stack. We only need the polygons, so load them directly instead. |

### 2.2 Why not just use `searoute`?

`searoute` answers "what's a plausible route from A to B?" by routing over a
sparse sea graph and snapping endpoints to the nearest water. It has no concept
of "this leg is illegal because it cuts across Italy." This service needs to
*reject* invalid input, so we need a land-intersection test, not a
path-finder. We note `searoute` as a future feature ("auto-suggest a valid
route") but it is **not** part of this validator.

### 2.3 The "straight line" is ambiguous — decision

A "straight line" between two lat/lons is not unique:

- **Linear in lon/lat (equirectangular):** simplest; what you'd get treating
  coordinates as flat X/Y.
- **Rhumb line (constant bearing):** what a straight `L.polyline` *looks like*
  on a Leaflet (Web-Mercator) map.
- **Great circle (geodesic):** the actual shortest path on the globe; appears
  curved on a Mercator map.

**Decision:** the leg geometry is defined as the **great-circle (geodesic)
path**, sampled via `pyproj.Geod`. Rationale: it's the physically meaningful
"straight" path for shipping and avoids the equirectangular distortion that
makes high-latitude legs wrong. The demo map will draw legs with a geodesic
polyline so the visual matches the validation. (This is a config flag —
`GEOMETRY = "geodesic" | "rhumb" | "linear"` — so callers can change it without
touching logic.)

### 2.4 Antimeridian (±180° longitude)

A leg from `lon = 170` to `lon = -170` should cross the Pacific (20° of
longitude), not wrap the long way across Asia. The geodesic sampler handles this
naturally because it works in 3D/bearing space; for any linear/rhumb fallback we
normalise by choosing the shorter longitudinal direction and splitting the
LineString at the antimeridian before the land test.

---

## 3. Chosen approach

A **hybrid**: exact vector test as the source of truth, raster as a fast
pre-filter and sanity backstop.

### 3.1 Point-on-land check

1. Validate coordinate ranges (lat ∈ [-90, 90], lon ∈ [-180, 180]).
2. `shapely` point-in-polygon against the Natural Earth 1:10m land layer,
   accelerated with a prepared geometry + `STRtree` spatial index.
   - `global-land-mask.is_land()` is available as a faster approximate
     alternative (config flag `POINT_BACKEND`), useful for bulk/perf-sensitive
     paths.

### 3.2 Line-crosses-land check

1. Build the leg geometry per §2.3 (geodesic by default).
2. **Exact test (primary):** construct a `shapely.LineString` from the sampled
   geodesic vertices and test `line.intersects(land_union)` using the prepared
   land geometry + spatial index. A leg whose endpoints merely *touch* a coast
   but whose interior stays in water is still invalid if the interior
   intersects land.
3. Because the LineString is a polyline approximation of a curve, vertex spacing
   matters: sample at a fixed max spacing (e.g. **≤ 25 km**, configurable
   `SAMPLE_KM`) so we don't "jump over" a narrow isthmus or thin island between
   two vertices. Endpoints are always included.

This gives an exact intersection test against the polygon edges *between*
samples (not just at sample points), so the only residual error is the
piecewise-linear approximation of the great-circle curve, bounded by
`SAMPLE_KM`.

### 3.3 Navigable channel corridors (canals & narrow straits)

Major artificial canals and narrow natural straits (Suez, Panama, Bosphorus,
Kiel, etc.) are narrower than the 1:10m land resolution and would otherwise read
as "blocked." To allow ships through them:

- Maintain a small, hand-curated set of **navigable corridors** — thin polygons
  (or buffered centre-lines) tracing each passage — vendored as
  `app/data/channels.geojson`.
- The line-crossing test becomes: a leg is blocked **iff** it intersects land
  **and** that intersection is **not** wholly contained within a navigable
  corridor. Concretely: subtract the corridor polygons from the land geometry
  once at startup (`land_effective = land_union.difference(channels_union)`),
  then test against `land_effective`.
- Initial corridor set: **Suez, Panama, Bosphorus/Dardanelles, Kiel,
  Gibraltar, Strait of Malacca, Danish straits**. The list is data-driven, so
  operators can add corridors without code changes.
- Corridors are deliberately generous (a few km wide) — a ship "threading the
  needle" should succeed rather than fail on sub-pixel geometry.

### 3.4 Land data handling

- Load Natural Earth 1:10m land (+ minor islands) once at startup into a single
  unary-unioned, prepared `shapely` geometry with an `STRtree` index.
- Bundle the polygons with the service (vendored GeoJSON) so there are **no
  runtime downloads** and the service is deterministic and offline-capable.
- Known edge cases to document, not necessarily fix: inland seas (Caspian),
  large lakes (treated as land/ocean depending on dataset), and very small
  islands below the 1:10m capture threshold. For this service these are acceptable.

---

## 4. Tech stack

- **Python 3.11+**
- **[FastAPI](https://fastapi.tiangolo.com/)** + **Uvicorn** — async, automatic
  request validation via Pydantic, and free interactive OpenAPI docs at
  `/docs` (handy for API consumers).
- **Pydantic v2** — request/response models and coordinate validation.
- **shapely 2.x**, **pyproj**, optional **global-land-mask**.
- Static demo page served by FastAPI (`StaticFiles`) so everything runs from one
  process.

```
searoute-validator/
├── SPEC.md                     # this file
├── README.md
├── pyproject.toml
├── app/
│   ├── main.py                 # FastAPI app, routes, static mount
│   ├── models.py               # Pydantic request/response schemas
│   ├── validator.py            # core land / line-crossing logic
│   ├── geometry.py             # geodesic sampling, antimeridian handling
│   └── data/
│       ├── land_10m.geojson    # vendored Natural Earth land polygons
│       └── channels.geojson    # navigable canal/strait corridors (§3.3)
├── web/
│   ├── index.html              # Leaflet demo
│   ├── app.js
│   └── style.css
└── tests/
    └── test_validator.py
```

---

## 5. API contract

All endpoints accept and return JSON. Coordinates are **decimal degrees**,
WGS84, ordered as `[lon, lat]` in arrays where GeoJSON-style is used, but the
request bodies below use explicit named fields to avoid lon/lat confusion.

### 5.1 `POST /leg`

**Request**
```json
{
  "start": { "lat": 50.1, "lon": -1.4 },
  "end":   { "lat": 40.5, "lon": -3.7 }
}
```

**Response — 200**
```json
{
  "valid": false,
  "reason": "line_crosses_land",
  "detail": "The straight line between the points crosses land.",
  "checks": {
    "start_on_land": false,
    "end_on_land": false,
    "line_crosses_land": true
  },
  "distance_km": 1043.2,
  "geometry": {
    "type": "LineString",
    "coordinates": [[-1.4, 50.1], "…sampled geodesic vertices…", [-3.7, 40.5]]
  }
}
```

`reason` is `null` when valid, otherwise one of:
`start_on_land`, `end_on_land`, `line_crosses_land`.
(`checks` always reports all three booleans so the client can highlight the
exact problem; the first failure in start→end→line order sets `reason`.)

`geometry` echoes the sampled leg so the front-end can draw exactly what was
tested. It can be suppressed with `?geometry=false` for lighter responses.

### 5.2 `POST /route`

**Request**
```json
{
  "waypoints": [
    { "lat": 51.9, "lon": 4.5 },
    { "lat": 36.1, "lon": -5.4 },
    { "lat": 40.6, "lon": -74.0 }
  ]
}
```

**Response — 200**
```json
{
  "valid": false,
  "leg_count": 2,
  "first_invalid_leg": 0,
  "legs": [
    {
      "index": 0,
      "start": { "lat": 51.9, "lon": 4.5 },
      "end":   { "lat": 36.1, "lon": -5.4 },
      "valid": false,
      "reason": "line_crosses_land",
      "checks": { "start_on_land": false, "end_on_land": false, "line_crosses_land": true },
      "distance_km": 1810.4
    },
    {
      "index": 1,
      "start": { "lat": 36.1, "lon": -5.4 },
      "end":   { "lat": 40.6, "lon": -74.0 },
      "valid": true,
      "reason": null,
      "checks": { "start_on_land": false, "end_on_land": false, "line_crosses_land": false },
      "distance_km": 5701.9
    }
  ],
  "total_distance_km": 7512.3
}
```

- `valid` is `true` iff every leg is valid.
- `first_invalid_leg` is the index of the first failing leg, or `null`.
- Evaluation is **eager by default** (all legs computed so the UI can colour the
  whole route); a `?stop_on_first=true` flag short-circuits for speed.

### 5.3 Errors

| Status | When | Body |
|---|---|---|
| `422` | Malformed body / out-of-range coordinate (handled by Pydantic) | FastAPI validation error |
| `400` | `< 2` waypoints, or a leg with identical start/end | `{ "error": "route_needs_two_points" }` |
| `200` | Valid request, route simply invalid | normal response with `"valid": false` |

**Key semantic:** an *unnavigable route* is a **200 with `valid: false`**, not an
HTTP error. HTTP 4xx is reserved for malformed input. This keeps client logic
simple.

### 5.4 Other endpoints

- `GET /health` → `{ "status": "ok", "land_dataset": "natural_earth_10m" }`
- `GET /` → serves the Leaflet demo page.
- `GET /docs` → FastAPI interactive OpenAPI UI (free).

---

## 6. Demo web page (Leaflet)

A single minimal page demonstrating the API.

- **Map:** [Leaflet](https://leafletjs.com/) with an OpenStreetMap tile layer.
- **Interaction:**
  - Click once to set the **start** marker, click again to set the **end**
    marker (or keep clicking to append waypoints for the `/route` demo).
  - A "Validate" button POSTs to `/leg` (2 points) or `/route` (3+).
  - The returned `geometry` is drawn as a polyline: **green** if valid, **red**
    if invalid. For a route, each leg is coloured independently and the first
    invalid leg is emphasised.
  - A side panel shows the JSON response and a plain-English `detail`.
  - "Clear" resets markers and lines.
- **No build step:** plain `index.html` + `app.js` + `style.css`, Leaflet from
  CDN, `fetch()` to the local API. Served from the same FastAPI process, so CORS
  isn't needed for the demo (CORS middleware will still be enabled for external
  clients).

---

## 7. Validation rules summary (single source of truth)

A **leg** `(start, end)` is **valid** ⟺ all of:
1. `start` is **not** on land,
2. `end` is **not** on land,
3. the leg geometry (geodesic by default) does **not** intersect land.

A **route** `[w0, w1, …, wn]` is **valid** ⟺ every consecutive leg
`(w_i, w_{i+1})` is valid. Shared interior waypoints are checked once (the end of
one leg is the start of the next).

---

## 8. Open questions / future work

- **Canal/strait corridor coverage:** the initial corridor set (§3.3) covers the
  major passages; expect to extend it as more of the world is exercised (e.g.
  Corinth, Saint Lawrence Seaway, Torres Strait). The data-driven design makes
  this additive.
- **Minimum sea-lane width / ship draft:** not modelled. Could add a coastal
  buffer so routes can't hug the shore.
- **Auto-routing:** integrate `searoute` to *suggest* a valid path when the
  user's is rejected.
- **Higher fidelity:** swap Natural Earth 1:10m for GSHHG `full` resolution if
  coastal accuracy complaints arise.
- **Performance:** for very long routes, batch all legs' sample points into one
  vectorised land query; cache the prepared land geometry across workers.

---

## 9. Licensing

The data and tools the validator depends on are all usable in a commercial
product with no copyleft obligations.

| Asset | Licence | Obligation |
|---|---|---|
| **Natural Earth** 1:10m land/coastline (the validation data) | **Public domain** | **None.** "No permission is needed to use Natural Earth… Crediting the authors is unnecessary." Vendor it directly; no licence file or attribution required. |
| `shapely`, `pyproj`, `global-land-mask` | BSD-3-Clause / MIT-style | Permissive. Keep their licence text in your dependency notices (standard for any pip dependency). |
| `searoute` (only if used later for auto-routing) | Apache-2.0 | Permissive; include NOTICE if redistributed. |
| **OpenStreetMap tiles** — *demo basemap only, not validation data* | **ODbL** | **Attribution required**: display "© OpenStreetMap contributors" on the map. Leaflet's `attribution` option satisfies this in one line. Does **not** touch the API or the service's own data. |
| GSHHG (only if we upgrade fidelity later) | LGPL / public-domain mix per the dataset | Check the specific GSHHG release terms before bundling. |

**Bottom line:** the data that powers validation (Natural Earth) is public
domain with zero obligations. The only attribution requirement anywhere is the
OSM basemap in the *demo* page, which is cosmetic background imagery, not part of
the service's logic or data.

---

## 10. Sources

- searoute — <https://pypi.org/project/searoute/>, <https://github.com/genthalili/searoute-py>
- global-land-mask — <https://pypi.org/project/global-land-mask/>, <https://github.com/toddkarin/global-land-mask>
- Shapely — <https://shapely.readthedocs.io/en/stable/manual.html>
- pyproj `Geod` — <https://pyproj4.github.io/pyproj/stable/api/geod.html>
- Natural Earth — <https://www.naturalearthdata.com/>
- GSHHG — <https://www.soest.hawaii.edu/pwessel/gshhg/>
- cartopy feature interface — <https://scitools.org.uk/cartopy/docs/v0.14/matplotlib/feature_interface.html>
- Leaflet — <https://leafletjs.com/>
