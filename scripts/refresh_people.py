"""Collect sourced people numbers (event crowds, visitors, new homes, metro riders) per location.

    python scripts/refresh_people.py              # every location, once a day
    python scripts/refresh_people.py --force      # search again today
    python scripts/refresh_people.py --only H3    # one location (or "cars" for car events)

Uses Claude with web search (needs ANTHROPIC_API_KEY). Writes data/signals/people.json; the
dashboard only reads that file.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ooh.config import load_placements  # noqa: E402
from ooh.footprint import KINDS, refresh  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="search again even if searched today")
    parser.add_argument("--only", nargs="*", help="placement ids (or 'cars') to search")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    store = refresh(load_placements(), force=args.force, only=args.only)
    print("facts:", store.counts())
    for f in sorted(store.facts.values(), key=lambda f: (f["status"], f["kind"])):
        mark = "KEPT" if f["status"] == "kept" else "drop"
        when = f.get("event_start") or f.get("figure_year") or ""
        print(f"- {mark} {KINDS[f['kind']]['icon']} {f['what']} @ {f.get('place')} -> {f['value']:,.0f} {f['unit']}"
              f"/{f['period']} {when} {f['tags']} {f['placements']} {f['reason']}")


if __name__ == "__main__":
    main()
