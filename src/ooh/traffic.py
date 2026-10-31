"""Traffic volume per segment: TomTom when available, else the RTA-capacity fallback.

Fallback (methodology step 4)::

    vehicles/day = lanes x 2,000 vehicles/lane/hour x utilisation x 24

2,000 per lane matches RTA's 14,000 vehicles per hour for 7 lanes (VERIFIED basis).
The daily total is shaped into hours with an hourly profile, and every hour is capped at
lane capacity so the estimate can never exceed what the road can physically carry.
"""

from __future__ import annotations

import json
import hashlib
import logging
import math
from dataclasses import dataclass

import numpy as np
import requests

from .config import CACHE_DIR, AssumptionConfig, Params, Scenario, env_key

log = logging.getLogger(__name__)

TOMTOM_FLOW_URL = (
    "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
)


@dataclass
class Volume:
    """Vehicles per day in the travel direction, plus the 24 hourly values behind it."""

    daily: float
    hourly: np.ndarray
    capped_hours: int
    source: str
    label: str


def lanes_per_direction(lanes_osm: float | None, oneway: bool, highway: str,
                        cfg: AssumptionConfig) -> tuple[int, str]:
    """Lanes carrying traffic in one direction, and where the number came from.

    On a one-way OSM way (how Sheikh Zayed Road is mapped) the lanes tag is already per
    direction. On a two-way way it is the total, so it is halved.
    """
    if lanes_osm and lanes_osm > 0:
        lanes = lanes_osm if oneway else math.ceil(lanes_osm / 2)
        return max(1, int(round(lanes))), "OSM lanes tag"
    default = cfg.road_class(highway).lanes
    return default, f"default for {highway or 'unknown'} (ASSUMPTION)"


def segment_speed_kmh(maxspeed_osm: float | None, highway: str, params: Params) -> tuple[float, str]:
    """Average speed: OSM maxspeed x speed factor, else the road-class default."""
    if maxspeed_osm and maxspeed_osm > 0:
        return maxspeed_osm * params.base("speed_factor_of_maxspeed"), "OSM maxspeed x speed factor"
    return params.cfg.road_class(highway).speed_kmh, f"default for {highway or 'unknown'} (ASSUMPTION)"


def capacity_volume(lanes: int, highway: str, params: Params, scenario: Scenario = "base",
                    hourly_shares: list[float] | None = None) -> Volume:
    """RTA-capacity fallback, shaped by the hourly profile and capped per hour."""
    cfg = params.cfg
    per_lane_hour = params.base("vehicles_per_lane_per_hour")
    util = params.get("utilisation", scenario) * cfg.road_class(highway).utilisation_factor
    util = min(util, 1.0)
    daily_uncapped = lanes * per_lane_hour * util * 24
    shares = np.asarray(hourly_shares or cfg.hourly_profile.shares, dtype=float)
    hourly = daily_uncapped * shares / shares.sum()
    cap = lanes * per_lane_hour
    capped_hours = int((hourly > cap).sum())
    hourly = np.minimum(hourly, cap)
    return Volume(
        daily=float(hourly.sum()),
        hourly=hourly,
        capped_hours=capped_hours,
        source="RTA capacity fallback: lanes x 2,000 x utilisation x 24",
        label="ESTIMATE",
    )


# --------------------------------------------------------------------------- TomTom


def _cache_get(namespace: str, key: str) -> dict | None:
    path = CACHE_DIR / "api" / namespace / f"{hashlib.sha1(key.encode()).hexdigest()}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def _cache_put(namespace: str, key: str, value: dict) -> None:
    path = CACHE_DIR / "api" / namespace / f"{hashlib.sha1(key.encode()).hexdigest()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def tomtom_flow_speed(lat: float, lon: float) -> float | None:
    """Current free-flow-adjusted speed (km/h) at a point, from the TomTom Traffic Flow API.

    Returns None without a key or on any error. Responses are cached, so the same point is
    never requested twice.
    """
    key = env_key("TOMTOM_API_KEY")
    if not key:
        return None
    cache_key = f"{lat:.5f},{lon:.5f}"
    cached = _cache_get("tomtom_flow", cache_key)
    if cached is None:
        try:
            resp = requests.get(TOMTOM_FLOW_URL, params={"point": cache_key, "key": key, "unit": "KMPH"},
                                timeout=15)
            resp.raise_for_status()
            cached = resp.json()
            _cache_put("tomtom_flow", cache_key, cached)
        except requests.RequestException as exc:
            log.warning("TomTom flow request failed: %s", exc)
            return None
    speed = cached.get("flowSegmentData", {}).get("currentSpeed")
    return float(speed) if speed else None


def tomtom_volume(lat: float, lon: float) -> Volume | None:
    """TomTom Traffic Volume for a segment.

    UAE coverage of the TomTom Traffic Volume service is NOT confirmed (see the solution
    design doc). The service is contract-based and job-driven (Traffic Stats), so the MVP
    does not call it: this hook returns None and the capacity fallback is used. When a
    contract confirms UAE coverage, implement the job request here and return a Volume
    labelled ESTIMATE with source "TomTom Traffic Volume".
    """
    if not env_key("TOMTOM_API_KEY"):
        return None
    log.info("TomTom key set, but Traffic Volume coverage for the UAE is unconfirmed; using fallback")
    return None


def segment_volume(lat: float, lon: float, lanes: int, highway: str, params: Params,
                   scenario: Scenario = "base") -> Volume:
    """First source that works: TomTom Traffic Volume, then the capacity fallback."""
    return tomtom_volume(lat, lon) or capacity_volume(lanes, highway, params, scenario)
