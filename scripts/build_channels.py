"""Generate app/data/channels.geojson — the navigable canal/strait corridors
(SPEC §3.3).

Each corridor is a hand-curated centre-line buffered into a thin polygon. The
corridors are subtracted from the land geometry at startup so ships can pass
through passages that are narrower than the 1:10m land resolution (Suez, Panama,
Kiel) or that we simply want to guarantee stay open (Gibraltar, Malacca, the
Danish and Turkish straits).

Corridors are deliberately a few km wide so "threading the needle" succeeds
rather than failing on sub-pixel geometry. Add new passages by appending to
CORRIDORS and re-running this script.

Run:  python -m scripts.build_channels
"""
from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, mapping

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "channels.geojson"

# (name, buffer in degrees (~111 km/deg), [(lon, lat), ...] centre-line)
CORRIDORS = [
    ("Suez Canal", 0.13, [
        (32.30, 31.60), (32.30, 31.26), (32.32, 30.85), (32.34, 30.59),
        (32.40, 30.33), (32.55, 29.97), (32.60, 29.60),
    ]),
    ("Panama Canal", 0.06, [
        (-79.92, 9.36), (-79.80, 9.12), (-79.68, 9.00), (-79.55, 8.88),
    ]),
    ("Bosphorus", 0.05, [
        (29.13, 41.22), (29.05, 41.10), (28.98, 41.02), (28.95, 40.97),
    ]),
    ("Dardanelles", 0.05, [
        (26.70, 40.42), (26.50, 40.30), (26.30, 40.15), (26.20, 40.00),
    ]),
    ("Kiel Canal", 0.10, [
        (8.90, 53.95), (9.14, 53.89), (9.50, 54.10), (9.90, 54.30),
        (10.15, 54.37), (10.40, 54.45),
    ]),
    ("Strait of Gibraltar", 0.08, [
        (-5.70, 35.95), (-5.45, 35.95), (-5.30, 36.00), (-5.15, 36.05),
    ]),
    ("Strait of Malacca", 0.10, [
        (98.50, 5.50), (100.00, 3.50), (102.00, 2.00), (103.80, 1.30),
    ]),
    ("Danish Straits (Oresund)", 0.06, [
        (12.60, 55.45), (12.70, 55.70), (12.65, 56.00),
    ]),
    ("Danish Straits (Great Belt)", 0.06, [
        (10.80, 55.00), (11.00, 55.30), (11.00, 55.60),
    ]),
]


def main() -> None:
    features = []
    for name, buf, line in CORRIDORS:
        poly = LineString(line).buffer(buf, cap_style="round", join_style="round")
        features.append({
            "type": "Feature",
            "properties": {"name": name},
            "geometry": mapping(poly),
        })
    fc = {"type": "FeatureCollection", "features": features}
    OUT.write_text(json.dumps(fc), encoding="utf-8")
    print(f"Wrote {len(features)} corridors to {OUT}")


if __name__ == "__main__":
    main()
