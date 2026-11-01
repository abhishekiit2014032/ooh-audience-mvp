"""Refresh online signals: collect headlines, extract dated events with Claude, rebuild the ledger.

    python scripts/refresh_signals.py            # all placements
    python scripts/refresh_signals.py --no-gdelt # Google News only (faster on slow links)

Writes data/signals/ledger.json. The dashboard only reads that file, so sliders stay fast.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ooh.config import Params, load_assumptions, load_placements  # noqa: E402
from ooh.signals import refresh  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-gdelt", action="store_true", help="skip GDELT (rate-limited on some networks)")
    parser.add_argument("--enrich", type=int, default=4, help="max undated events to look up with web search")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    ledger = refresh(load_placements(), Params(load_assumptions()), use_gdelt=not args.no_gdelt,
                     enrich_limit=args.enrich)
    print("articles:", ledger.counts())
    for ev in ledger.events.values():
        hours = f"{ev['start_hour']}-{ev['end_hour']}h" if ev.get("start_hour") is not None else "default hours"
        print(f"- {'ON ' if ev['enabled'] else 'off'} {ev['date']} {ev['type']:15} "
              f"{ev.get('corridor') or ', '.join(ev.get('areas', []))} ({hours}), "
              f"{len(ev['articles'])} articles, confidence {ev['confidence']:.2f}")


if __name__ == "__main__":
    main()
