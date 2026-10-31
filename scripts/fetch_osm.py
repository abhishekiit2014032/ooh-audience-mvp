"""Download (or refresh) the OpenStreetMap cache for every placement.

    python scripts/fetch_osm.py           # fetch only placements without a valid cache
    python scripts/fetch_osm.py --force   # re-download everything

The GeoPackages in data/cache/ are committed so the app runs offline and on Streamlit Cloud.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ooh.config import load_placements  # noqa: E402
from ooh.roads import _cache_valid, download_area  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download even when a cache exists")
    parser.add_argument("ids", nargs="*", help="placement ids (default: all)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    for p in load_placements().placements:
        if args.ids and p.id not in args.ids:
            continue
        if _cache_valid(p) and not args.force:
            print(f"{p.id}: cache valid, skipping")
            continue
        download_area(p)
        print(f"{p.id}: downloaded")


if __name__ == "__main__":
    main()
