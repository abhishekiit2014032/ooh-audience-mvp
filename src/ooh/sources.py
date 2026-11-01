"""Registry of every data source, its live status and its confidence score.

One place for the Data sources page, its diagram, Check the data and the Assumptions page, so they never drift.
Status is derived locally (env keys present, cache dates, is_sample flags); nothing here calls
the network.

Confidence score (0-100) is a planning heuristic, labelled ASSUMPTION. It is separate from
the VERIFIED / ESTIMATE / ASSUMPTION / SAMPLE / CONCEPT labels on individual numbers::

    score     = 100 x status_factor x (0.40 provenance + 0.35 directness + 0.25 freshness)
    potential = the same with status_factor = 1 and freshness = 1 (once connected and live)

* provenance: who stands behind the data (official 1.0 ... placeholder 0.1)
* directness: how directly it measures what the model needs it for (0..1)
* freshness: live today 1.0, cached <= 30 days 0.85, static publication 0.6
* status_factor: live / cached / configured 1.0, sample 0.35, not connected 0
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from .config import CACHE_DIR, INPUT_DIR, env_key, load_placements

WEIGHTS = {"provenance": 0.40, "directness": 0.35, "freshness": 0.25}
STATUS_FACTOR = {"live": 1.0, "cached": 1.0, "configured": 1.0, "on demand": 1.0, "sample": 0.35,
                 "not connected": 0.0}

ENGINE = {
    "geo": "Geospatial reach model",
    "ai": "Claude: news reading, people numbers and narratives",
}

# Outcomes the knowledge layer feeds (same ids as config/knowledge.yaml "outcomes").
OUTPUTS = {
    "reach": "Everyone passing",
    "target": "Campaign audience",
    "value": "Value (audience per price level)",
    "fit": "Audience fit",
    "timing": "Crowd timing",
    "forecast": "Delivery forecast",
    "profile": "Audience profile",
}

# Outcomes each engine half produces. Claude only reads text (news, web pages); every number it
# returns is checked and converted by the geospatial model with config assumptions.
ENGINE_OUTPUTS = {
    "geo": ["reach", "target", "value", "fit", "timing", "forecast", "profile"],
    "ai": ["timing", "forecast"],
}
ENGINE_HANDOFF: dict[str, list[str]] = {}


@dataclass
class Source:
    id: str
    name: str
    provider: str
    what: str
    engine: str                 # "geo" or "ai"
    feeds: list[str]            # output ids
    label: str                  # label of the numbers it contributes
    status: str
    status_note: str
    provenance: float
    directness: float
    freshness: float
    upgrade: str
    url: str = ""
    context_only: bool = False  # feeds context, not the reach numbers
    phase: str = "MVP"
    breakdown: dict = field(default_factory=dict)

    @property
    def score(self) -> int:
        f = STATUS_FACTOR.get(self.status, 0.0)
        raw = (WEIGHTS["provenance"] * self.provenance + WEIGHTS["directness"] * self.directness
               + WEIGHTS["freshness"] * self.freshness)
        return round(100 * f * raw)

    @property
    def potential(self) -> int:
        raw = (WEIGHTS["provenance"] * self.provenance + WEIGHTS["directness"] * self.directness
               + WEIGHTS["freshness"] * 1.0)
        return round(100 * raw)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(score=self.score, potential=self.potential, feeds_names=[OUTPUTS[o] for o in self.feeds],
                 engine_name=ENGINE[self.engine])
        return d


# --------------------------------------------------------------------------- local status checks


def _days_since(iso: str) -> int:
    try:
        return (date.today() - datetime.fromisoformat(iso[:10]).date()).days
    except ValueError:
        return 9999


def _freshness(days: int) -> float:
    if days <= 1:
        return 1.0
    if days <= 30:
        return 0.85
    return 0.6


def _osm_status() -> tuple[str, str, float]:
    dates = []
    for p in load_placements().placements:
        meta = CACHE_DIR / f"osm_{p.id}.json"
        if meta.exists():
            dates.append(json.loads(meta.read_text())["fetched_at"][:10])
    if not dates:
        return "sample", "No cache: synthetic road fallback", 0.6
    oldest = min(dates)
    return "cached", f"Cached {len(dates)} of 4 placements, oldest {oldest}", _freshness(_days_since(oldest))


def _json_sample(name: str) -> bool:
    try:
        return bool(json.loads((INPUT_DIR / name).read_text()).get("is_sample", True))
    except (OSError, ValueError):
        return True


def _csv_sample(name: str) -> bool:
    try:
        with open(INPUT_DIR / name, newline="") as f:
            return any(str(r.get("is_sample", "true")).lower() == "true" for r in csv.DictReader(f))
    except OSError:
        return True


def _news_status() -> tuple[str, str, float]:
    from .signals import LEDGER_PATH

    if LEDGER_PATH.exists():
        data = json.loads(LEDGER_PATH.read_text())
        arts = data.get("articles", {}).values()
        kept = sum(1 for a in arts if a.get("status") == "applied")
        events = sum(1 for e in data.get("events", {}).values() if e.get("enabled"))
        updated = data.get("updated_at", "")[:10]
        return ("live" if _days_since(updated) <= 1 else "cached",
                f"Ledger {updated}: {len(data.get('articles', {}))} articles, {kept} kept, {events} events on",
                _freshness(_days_since(updated)))
    return "on demand", "Press 'Refresh signals' under Check the data → Road events to build the event ledger", 0.85


def _people_status() -> tuple[str, str, float]:
    from .footprint import PEOPLE_PATH

    if PEOPLE_PATH.exists():
        data = json.loads(PEOPLE_PATH.read_text())
        kept = sum(1 for f in data.get("facts", {}).values() if f.get("status") == "kept")
        updated = data.get("updated_at", "")[:10]
        return ("live" if _days_since(updated) <= 1 else "cached",
                f"Searched {updated}: {kept} sourced numbers kept", _freshness(_days_since(updated)))
    return "on demand", "Press 'Search for people numbers' under Check the data → Web-sourced numbers", 0.85


# --------------------------------------------------------------------------- registry


def registry() -> list[Source]:
    osm_status, osm_note, osm_fresh = _osm_status()
    tomtom = env_key("TOMTOM_API_KEY") is not None
    news_status, news_note, news_fresh = _news_status()

    def sample_or(status_if_real: str, is_sample: bool) -> str:
        return "sample" if is_sample else status_if_real

    sources = [
        Source("osm", "OpenStreetMap", "OSM contributors via Overpass / OSMnx",
               "Roads, lanes, one-way, speed limits, building footprints, points of interest, metro lines",
               "geo", ["reach", "target", "fit", "profile"], "VERIFIED",
               osm_status, osm_note, 0.75, 0.90, osm_fresh,
               "Refresh with scripts/fetch_osm.py; add building heights and Mapillary imagery in Phase 2",
               "https://www.openstreetmap.org"),
        Source("rta", "RTA lane capacity", "Roads and Transport Authority (via Time Out Dubai)",
               "Up to 14,000 vehicles per hour on 7 lanes: 2,000 per lane, the base of the volume estimate",
               "geo", ["reach", "target", "value", "fit", "timing", "profile"], "VERIFIED",
               "configured", "Published figure, used with a utilisation assumption", 1.0, 0.50, 0.6,
               "Request segment counts from RTA, or replace with TomTom / HERE modelled volumes",
               "https://www.timeoutdubai.com"),
        Source("tomtom_flow", "TomTom Traffic Flow", "TomTom",
               "Current speed per road segment, used for the dwell factor", "geo", ["reach"], "ESTIMATE",
               "live" if tomtom else "not connected",
               "Key set: speeds fetched once per face and cached" if tomtom else "Set TOMTOM_API_KEY in .env",
               0.85, 0.60, 1.0, "Use historical speed profiles from Traffic Stats instead of one live reading",
               "https://developer.tomtom.com"),
        Source("tomtom_stats", "TomTom Traffic Stats / Volume", "TomTom",
               "Historical speeds, probe sample counts and modelled vehicle volumes per segment and date range",
               "geo", ["reach", "forecast"], "ESTIMATE", "not connected",
               "No access on the free key (403 Forbidden, checked 2026-10-31); UAE volume coverage unconfirmed",
               0.85, 0.85, 1.0, "Request a Traffic Stats trial; would make planned vs actual real data",
               "https://developer.tomtom.com/traffic-stats/documentation/product-information/introduction"),
        Source("metro", "RTA metro ridership", "Dubai Pulse (rta_metro_ridership-open)",
               "Daily riders at the station nearest each face", "geo", ["reach", "fit", "profile"], "SAMPLE",
               sample_or("cached", _csv_sample("metro_ridership.csv")),
               "Placeholder values in data/inputs/metro_ridership.csv", 1.0, 0.40, 0.85,
               "Download the Dubai Pulse CSV (free) and set is_sample to false",
               "https://www.dubaipulse.gov.ae"),
        Source("meta", "Meta reach estimates", "Meta Ads Manager",
               "Audience size, age, gender and interest share for a pin plus radius. Interest share replaces the "
               "campaign assumption once real values are entered", "geo", ["profile"],
               "SAMPLE", sample_or("cached", _json_sample("meta_reach.json")),
               "Placeholder values in data/inputs/meta_reach.json", 0.70, 0.60, 0.85,
               "Copy the reach estimate for each face from Ads Manager (free) and set is_sample to false",
               "https://adsmanager.facebook.com"),
        Source("dsc", "Dubai Statistics Center", "Government of Dubai",
               "Population by area, age and gender: sanity check on the Meta mix", "geo", [], "SAMPLE",
               sample_or("cached", _json_sample("dsc_population.json")),
               "Placeholder values in data/inputs/dsc_population.json", 1.0, 0.40, 0.6,
               "Enter the latest DSC publication figures and set is_sample to false", "https://www.dsc.gov.ae",
               context_only=True),
        Source("playlog", "Media owner play log", "Media owner",
               "Planned vs actual plays per day for the digital faces", "geo", ["forecast"], "SAMPLE",
               sample_or("cached", _csv_sample("play_log.csv")),
               "Placeholder log in data/inputs/play_log.csv", 0.90, 0.90, 0.85,
               "Make the play log a contract deliverable and load it weekly"),
        Source("assumptions", "Model assumptions", "This model (config/assumptions.yaml)",
               "Utilisation, occupancy, pass frequency, cone, visibility weights: every lever in the sidebar",
               "geo", ["reach", "target", "value", "fit", "timing", "profile"], "ASSUMPTION", "configured",
               "Editable in the sidebar; frequency is the weakest input", 0.40, 0.50, 0.6,
               "Calibrate frequency and duplication with mobile panel data (Phase 2)"),
        Source("news", "Road events from news", "Google News RSS, GDELT DOC 2.0, Claude web search",
               "Recent headlines per corridor and area. Claude extracts dated closures, roadworks and events "
               "into an event ledger; the forecast applies them with effect sizes from config (not the plan)",
               "ai", ["forecast"], "ESTIMATE",
               news_status, news_note, 0.60, 0.45, news_fresh,
               "Licensed news API (NewsAPI, Factiva) plus RTA announcements; calibrate effect sizes in the pilot",
               "https://news.google.com"),
        Source("people_news", "People numbers from news", "Claude web search over news and official pages",
               "Event attendance, visitors, new homes, metro riders and traffic counts, each quoted from its page. "
               "Only dated crowds inside a campaign window become extra people (config shares)",
               "ai", ["timing"], "ESTIMATE", *_people_status(), 0.60, 0.50,
               "Licensed event calendars (DWTC, Dubai Calendar) and venue footfall feeds",
               "https://www.visitdubai.com"),
        Source("inventory", "Billboard inventory", "Media owner (config/placements.yaml)",
               "Location, facing, size, digital loop and share of voice, and our price-level rating (1-4) for each board",
               "geo", ["reach", "value", "forecast"], "VERIFIED", "configured",
               "Location and size checked on OSM; price level is our rating until quotes arrive (no prices used)", 0.90, 0.90, 0.85,
               "Replace the price-level rating with media-owner quotes"),
        Source("briefs", "Campaign briefs", "Marketing team (config/placements.yaml)",
               "Who each campaign is after, its share of passers-by, dates and how many boards",
               "geo", ["target", "timing", "forecast"], "ASSUMPTION", "configured",
               "Audience shares are assumptions until Meta values are entered", 0.70, 0.80, 0.85,
               "Enter Meta interest shares per board; confirm the number of boards"),
        Source("mapillary", "Mapillary street imagery", "Meta / Mapillary",
               "Street-level images to confirm line of sight with a vision model", "geo", ["reach"],
               "CONCEPT", "not connected", "Phase 2: needs MAPILLARY_TOKEN and the vision check", 0.75, 0.70, 0.85,
               "Add the token and the Claude vision line-of-sight check", "https://www.mapillary.com",
               phase="Phase 2"),
        Source("mobility", "Telco / mobility panel", "e&, du, Veraset, Azira, Blis",
               "Unique devices, repeat visits, true duplication, home/work origin, audience export",
               "geo", ["reach", "target", "fit"], "CONCEPT", "not connected",
               "Phase 2: paid licence, quote-only", 0.85, 0.95, 1.0,
               "Sign one vendor for Dubai; replaces the frequency and duplication assumptions",
               phase="Phase 2"),
    ]
    for s in sources:
        s.breakdown = {
            "provenance": s.provenance, "directness": s.directness, "freshness": s.freshness,
            "status_factor": STATUS_FACTOR.get(s.status, 0.0),
        }
    return sources


def engine_status() -> dict:
    claude = env_key("ANTHROPIC_API_KEY") is not None
    return {
        "geo": {"name": ENGINE["geo"], "status": "running",
                "note": "Counts every number: cones, visibility, traffic, reach, duplication, delivery"},
        "ai": {"name": ENGINE["ai"], "status": "active" if claude else "templates",
               "note": ("Claude API key set: writes narratives and sorts news from computed numbers and "
                        "fetched headlines only" if claude else
                        "No key: templates and keyword rules stand in")},
    }
