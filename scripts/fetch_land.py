"""Download the Natural Earth 1:10m land polygons into app/data/.

The land data is vendored (committed) so the service needs no runtime
downloads (SPEC §3.4). Use this script only to (re)fetch or update the file.

Natural Earth is public domain — no attribution or licence file required
(SPEC §9).

Run:  python -m scripts.fetch_land
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_10m_land.geojson"
)
OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "land_10m.geojson"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {URL}")
    urllib.request.urlretrieve(URL, OUT)
    print(f"Saved {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
