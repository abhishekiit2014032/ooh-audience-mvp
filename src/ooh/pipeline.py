"""Run every step for all placements and write the outputs.

Two stages, matching the dashboard's caching:

* :func:`prepare` (slow, parameter-independent): load OSM, snap faces to the road, cut
  directed segments, test line of sight. Cached by the app.
* :func:`compute` (fast): visibility, reach, profile, duplication, plan, delivery and
  activation for the current parameter values.

Run from the command line::

    python -m ooh.pipeline            # writes data/outputs/
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import activation, delivery, duplication, narrative, profile as profile_mod, reach as reach_mod
from . import geometry as geo
from .config import (OUTPUT_DIR, AssumptionConfig, Params, Placement, PlacementConfig, load_assumptions,
                     load_placements)
from .metrics import Metric
from .roads import OsmArea, SnappedPlacement, load_area, snap_placement
from .visibility import build_segments, score_metro, score_segments

log = logging.getLogger(__name__)


@dataclass
class GeoPrep:
    placement: Placement
    snapped: SnappedPlacement
    area_source: str
    area_is_sample: bool
    roads: pd.DataFrame
    metro: pd.DataFrame
    metro_input: reach_mod.MetroInput | None
    pois: object  # GeoDataFrame


@dataclass
class PlacementResult:
    prep: GeoPrep
    scored: pd.DataFrame
    metro_scored: pd.DataFrame
    reach: reach_mod.PlacementReach
    profile: profile_mod.Profile
    facts: dict

    @property
    def id(self) -> str:
        return self.prep.placement.id

    @property
    def metrics(self) -> dict[str, Metric]:
        return self.reach.metrics


@dataclass
class Results:
    placements: dict[str, PlacementResult]
    overlap: pd.DataFrame
    overlap_rules: pd.DataFrame
    plan: list[duplication.PlanStep]
    naive_unique: float
    combined_unique_all: float
    delivery: pd.DataFrame
    delivery_label: str
    zones_geojson: str
    radius_csv: str
    snap_log: list[dict] = field(default_factory=list)
    narratives: dict[str, dict] = field(default_factory=dict)


# --------------------------------------------------------------------------- stage 1


def prepare(pcfg: PlacementConfig, params: Params, allow_download: bool = True) -> dict[str, GeoPrep]:
    preps: dict[str, GeoPrep] = {}
    for p in pcfg.placements:
        area: OsmArea = load_area(p, allow_download=allow_download)
        snapped = snap_placement(p, area)
        log.info("%s snapped: %s", p.id, snapped.to_dict())
        roads, metro = build_segments(p, snapped, area, params)
        metro_input = reach_mod.nearest_station_riders(snapped, area) if not metro.empty else None
        preps[p.id] = GeoPrep(p, snapped, area.source, area.is_sample, roads, metro, metro_input, area.pois)
    return preps


# --------------------------------------------------------------------------- stage 2


def compute_placement(prep: GeoPrep, params: Params, brand: str) -> PlacementResult:
    p, s = prep.placement, prep.snapped
    scored = score_segments(prep.roads, p, s, params, sov=1.0)
    metro_scored = score_metro(prep.metro, p, s, params, sov=1.0)
    r = reach_mod.compute_reach(scored, metro_scored, p, prep.metro_input, params, prep.area_is_sample)
    base = r.scenarios["base"]
    road_share = base.road_impressions_day / base.impressions_day if base.impressions_day else 1.0
    prof = profile_mod.build_profile(p, prep.pois, r.metrics["unique_month"], r.metrics["impressions_month"],
                                     params, road_share)
    facts = narrative.facts_for(p, r.metrics, prof)
    return PlacementResult(prep, scored, metro_scored, r, prof, facts)


def unique_only(prep: GeoPrep, params: Params) -> float:
    """Base unique monthly audience for one placement (used by the sensitivity chart)."""
    p, s = prep.placement, prep.snapped
    scored = score_segments(prep.roads, p, s, params)
    metro_scored = score_metro(prep.metro, p, s, params)
    r = reach_mod.compute_reach(scored, metro_scored, p, prep.metro_input, params, prep.area_is_sample)
    return r.metrics["unique_month"].value


def compute(preps: dict[str, GeoPrep], pcfg: PlacementConfig, params: Params) -> Results:
    brand = pcfg.campaign.brand
    results = {pid: compute_placement(prep, params, brand) for pid, prep in preps.items()}

    # Duplication and plan
    items = []
    for pid, res in results.items():
        base = res.reach.scenarios["base"]
        seg_u = duplication.segment_unique_shares(res.scored, base.flows, base.unique_month)
        s = res.prep.snapped
        items.append(duplication.PlacementSummary(
            id=pid, corridor=res.prep.placement.corridor, lon=s.lon, lat=s.lat,
            travel_bearing=s.travel_bearing_deg, unique=base.unique_month,
            relevant=res.profile.relevant_reach.value, interest_share=res.profile.interest_share.value,
            cost_aed=res.prep.placement.cost_per_month_aed, segment_unique=seg_u))
    mat, rules = duplication.overlap_matrix(items, params)
    plan = duplication.greedy_plan(items, mat, pcfg.campaign.budget_aed)
    uniques = duplication.uniques_dict(items)
    combined_all = duplication.combined_unique(list(uniques), uniques, mat)

    # Delivery
    adv_daily = {pid: r.metrics["advertiser_impressions_day"].value for pid, r in results.items()}
    deliv, deliv_label = delivery.delivery_table([r.prep.placement for r in results.values()], adv_daily,
                                                 pcfg.campaign, params)

    # Activation
    radius = params.base("cone_radius_m")
    half = params.base("half_angle_deg")
    feats, rows = [], []
    for res in results.values():
        s, p = res.prep.snapped, res.prep.placement
        feats.append(activation.zone_feature(p.id, p.name, s.lon, s.lat, s.facing_bearing_deg, radius, half))
        rows.append(activation.radius_row(p.id, p.name, s.lon, s.lat, s.facing_bearing_deg, radius, half))

    return Results(
        placements=results, overlap=mat, overlap_rules=rules, plan=plan,
        naive_unique=duplication.naive_sum(items), combined_unique_all=combined_all,
        delivery=deliv, delivery_label=deliv_label,
        zones_geojson=activation.zones_geojson(feats), radius_csv=activation.radius_csv(rows),
        snap_log=[res.prep.snapped.to_dict() | {"configured_lat": res.prep.placement.lat,
                                                 "configured_lon": res.prep.placement.lon,
                                                 "configured_facing_deg": res.prep.placement.facing_bearing_deg,
                                                 "osm_source": res.prep.area_source}
                  for res in results.values()],
    )


# --------------------------------------------------------------------------- sensitivity

TORNADO_PARAMS = ["utilisation", "occupancy", "monthly_frequency", "vehicles_per_lane_per_hour",
                  "cone_radius_m", "half_angle_deg", "heading_tolerance_deg", "obstruction_factor",
                  "full_dwell_seconds", "speed_factor_of_maxspeed", "metro_window_factor"]


def sensitivity(prep: GeoPrep, params: Params, keys: list[str] | None = None) -> pd.DataFrame:
    """Unique monthly audience with each parameter at its low and high value, others at base.

    Low / high come from the configured range when there is one, else base +/- 25 %.
    """
    base_value = unique_only(prep, params)
    rows = []
    for key in keys or TORNADO_PARAMS:
        p = params.cfg.parameters[key]
        base = params.base(key)
        if p.low is not None and p.high is not None:
            lo, hi = params.get(key, "low"), params.get(key, "high")
        else:
            lo, hi = base * 0.75, base * 1.25
        lo, hi = float(np.clip(lo, p.min, p.max)), float(np.clip(hi, p.min, p.max))
        u_lo = unique_only(prep, params.with_override(key, lo))
        u_hi = unique_only(prep, params.with_override(key, hi))
        rows.append({"parameter": key, "low_value": lo, "base_value": base, "high_value": hi,
                     "unique_at_low": u_lo, "unique_at_high": u_hi, "base_unique": base_value,
                     "swing": abs(u_hi - u_lo), "label": p.label})
    return pd.DataFrame(rows).sort_values("swing", ascending=True).reset_index(drop=True)


# --------------------------------------------------------------------------- outputs


def _segments_geojson(res: PlacementResult) -> dict:
    df = res.scored
    feats = []
    if not df.empty:
        inc = df[df["included"]]
        for row in inc.itertuples():
            coords = [list(geo.to_wgs(x, y)) for x, y in row.geometry.coords]
            feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                          "properties": {"segment_id": row.segment_id, "road": row.label,
                                         "highway": row.highway, "lanes": int(row.lanes),
                                         "flow": row.flow, "dist_m": round(row.dist_m, 1),
                                         "D": round(row.D, 3), "A": round(row.A, 3), "O": round(row.O, 3),
                                         "S": round(row.S, 3), "T": round(row.T, 3), "V": round(row.V, 4),
                                         "blocked": bool(row.blocked)}})
    return {"type": "FeatureCollection", "features": feats}


def results_dict(results: Results) -> dict:
    out = {"placements": {}, "duplication": {}, "plan": [], "delivery": {}, "snap_log": results.snap_log}
    for pid, res in results.placements.items():
        out["placements"][pid] = {
            "name": res.prep.placement.name,
            "snapped": res.prep.snapped.to_dict(),
            "osm_source": res.prep.area_source,
            "metrics": {k: v.to_dict() for k, v in res.metrics.items()},
            "profile": res.profile.to_dict(),
            "narrative": results.narratives.get(pid),
            "flows": res.reach.scenarios["base"].flows.to_dict(orient="records"),
        }
    out["duplication"] = {
        "overlap_people": results.overlap.round(0).to_dict(),
        "rules": results.overlap_rules.to_dict(),
        "naive_sum_unique": Metric(results.naive_unique, results.naive_unique, results.naive_unique,
                                   "ESTIMATE", "Sum of base unique audiences").to_dict(),
        "combined_unique_all": Metric(results.combined_unique_all, results.combined_unique_all,
                                      results.combined_unique_all, "ESTIMATE",
                                      "First-order inclusion-exclusion over all placements").to_dict(),
    }
    out["plan"] = [s.__dict__ for s in results.plan]
    out["delivery"] = {"label": results.delivery_label, "weeks": results.delivery.to_dict(orient="records")}
    return out


def write_outputs(results: Results) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "results.json").write_text(json.dumps(results_dict(results), indent=2, default=str))
    (OUTPUT_DIR / "snap_log.json").write_text(json.dumps(results.snap_log, indent=2))
    (OUTPUT_DIR / "zones.geojson").write_text(results.zones_geojson)
    (OUTPUT_DIR / "zones_radius.csv").write_text(results.radius_csv)
    for pid, res in results.placements.items():
        (OUTPUT_DIR / f"segments_{pid}.geojson").write_text(json.dumps(_segments_geojson(res)))


def run(overrides: dict[str, float] | None = None, allow_download: bool = True,
        write: bool = True) -> Results:
    pcfg: PlacementConfig = load_placements()
    acfg: AssumptionConfig = load_assumptions()
    params = Params(acfg, overrides)
    preps = prepare(pcfg, params, allow_download=allow_download)
    results = compute(preps, pcfg, params)
    for pid, res in results.placements.items():
        text, source = narrative.narrative(res.facts, pcfg.campaign.brand)
        results.narratives[pid] = {"text": text, "source": source}
    if write:
        write_outputs(results)
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    results = run()
    for pid, res in results.placements.items():
        u = res.metrics["unique_month"]
        print(f"{pid}: {res.metrics['impressions_day'].value:,.0f} impressions/day, "
              f"unique/month {u.value:,.0f} ({u.low:,.0f}-{u.high:,.0f}) [{u.label}], "
              f"relevant {res.profile.relevant_reach.value:,.0f}, source: {res.prep.area_source}")
    print(f"Combined unique (all 4): {results.combined_unique_all:,.0f} vs naive {results.naive_unique:,.0f}")
    print("Plan:", " -> ".join(s.placement for s in results.plan))
    print(f"Outputs written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
