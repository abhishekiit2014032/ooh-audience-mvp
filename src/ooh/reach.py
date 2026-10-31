"""Impressions and unique audience, with low / base / high (methodology steps 5 and 6).

::

    I_day        = sum over flows (Vol_flow x occ x mean V_flow) + Metro_day x m x V_metro
    I_month      = I_day x 30
    Unique_month = I_month / f

A flow is the set of segments one vehicle drives through in a single pass (same road,
class and direction). Each vehicle on a flow is one potential impression, weighted by the
average visibility along its visible approach, so segment counts never multiply traffic.

Scenarios move together: low = low utilisation, low occupancy and high frequency (f = 12);
high = high utilisation, high occupancy and low frequency (f = 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import geometry as geo
from .config import INPUT_DIR, SCENARIOS, Params, Placement, Scenario
from .metrics import Metric, weakest
from .roads import OsmArea, SnappedPlacement
from .traffic import capacity_volume, tomtom_volume


@dataclass
class MetroInput:
    station: str
    daily_riders: float
    label: str
    source: str


@dataclass
class ScenarioReach:
    flows: pd.DataFrame
    hourly_impressions: np.ndarray
    vehicles_day: float
    people_day: float
    road_impressions_day: float
    metro_impressions_day: float
    impressions_day: float
    impressions_month: float
    unique_month: float
    capped_hours: int


@dataclass
class PlacementReach:
    scenarios: dict[str, ScenarioReach]
    metro: MetroInput | None
    mean_visibility: float
    volume_source: str
    volume_label: str
    metrics: dict[str, Metric] = field(default_factory=dict)


def load_metro_ridership() -> pd.DataFrame:
    path = INPUT_DIR / "metro_ridership.csv"
    df = pd.read_csv(path)
    df["station_norm"] = df["station"].str.lower().str.replace(r"[^a-z0-9 ]", "", regex=True)
    return df


def nearest_station_riders(snapped: SnappedPlacement, area: OsmArea) -> MetroInput | None:
    """Daily riders at the metro station nearest the face (Dubai Pulse CSV; SAMPLE fallback)."""
    stations = area.stations
    if stations is None or len(stations) == 0:
        return None
    st = stations.copy()
    if "station" in st.columns:
        sub = st[st["station"].fillna("").str.contains("subway|light_rail", regex=True)]
        st = sub if len(sub) else st
    st["d"] = st.geometry.distance(geo.Point(snapped.x, snapped.y))
    row = st.sort_values("d").iloc[0]
    name = str(row.get("name:en") or row.get("name") or "unknown station")
    table = load_metro_ridership()
    key = name.lower()
    match = table[table["station_norm"].apply(lambda s: s in key or key.startswith(s))]
    if len(match):
        rec = match.iloc[0]
        label = "SAMPLE" if bool(rec["is_sample"]) else "VERIFIED"
        return MetroInput(name, float(rec["daily_riders"]), label, str(rec["source"]))
    default = table[table["station"] == "_default"].iloc[0]
    return MetroInput(name, float(default["daily_riders"]), "SAMPLE", "Default station ridership (SAMPLE)")


def _scenario(scored: pd.DataFrame, metro_scored: pd.DataFrame, placement: Placement,
              metro: MetroInput | None, params: Params, scenario: Scenario) -> ScenarioReach:
    occ = params.get("occupancy", scenario)
    f = params.get("monthly_frequency", scenario)
    days = params.base("days_per_month")
    shares = np.asarray(params.cfg.hourly_profile.shares)

    inc = scored[scored["included"]] if not scored.empty else scored
    rows = []
    hourly = np.zeros(24)
    capped = 0
    if not inc.empty:
        for flow, g in inc.groupby("flow"):
            lanes = int(g["lanes"].median())
            highway = g["highway"].iloc[0]
            vol = tomtom_volume(placement.lat, placement.lon) or capacity_volume(lanes, highway, params, scenario)
            mean_v = float(g["V"].mean())
            capped += vol.capped_hours
            hourly += vol.hourly * occ * mean_v
            rows.append({
                "flow": flow, "road": g["label"].iloc[0], "highway": highway, "lanes": lanes,
                "lanes_source": g["lanes_source"].iloc[0], "segments": len(g),
                "visible_length_m": float(g["length_m"].sum()), "speed_kmh": float(g["speed_kmh"].median()),
                "mean_V": mean_v, "vehicles_day": vol.daily, "people_day": vol.daily * occ,
                "impressions_day": vol.daily * occ * mean_v, "volume_source": vol.source,
            })
    flows = pd.DataFrame(rows)
    if not flows.empty:
        flows = flows.sort_values("impressions_day", ascending=False).reset_index(drop=True)

    metro_imp = 0.0
    if metro is not None and not metro_scored.empty and metro_scored["included"].any():
        v_metro = float(metro_scored.loc[metro_scored["included"], "V"].mean())
        metro_imp = metro.daily_riders * params.base("metro_window_factor") * v_metro
        hourly += metro_imp * shares

    road_imp = float(flows["impressions_day"].sum()) if not flows.empty else 0.0
    i_day = road_imp + metro_imp
    i_month = i_day * days
    return ScenarioReach(
        flows=flows,
        hourly_impressions=hourly,
        vehicles_day=float(flows["vehicles_day"].sum()) if not flows.empty else 0.0,
        people_day=float(flows["people_day"].sum()) if not flows.empty else 0.0,
        road_impressions_day=road_imp,
        metro_impressions_day=metro_imp,
        impressions_day=i_day,
        impressions_month=i_month,
        unique_month=i_month / f if f > 0 else 0.0,
        capped_hours=capped,
    )


def compute_reach(scored: pd.DataFrame, metro_scored: pd.DataFrame, placement: Placement,
                  metro: MetroInput | None, params: Params, osm_is_sample: bool) -> PlacementReach:
    """Run the three scenarios and wrap the headline numbers as labelled metrics."""
    sc = {s: _scenario(scored, metro_scored, placement, metro, params, s) for s in SCENARIOS}
    inc = scored[scored["included"]] if not scored.empty else scored
    mean_v = float(inc["V"].mean()) if len(inc) else 0.0
    base_flows = sc["base"].flows
    vol_source = base_flows["volume_source"].iloc[0] if len(base_flows) else "no visible road segments"

    traffic_label = "SAMPLE" if osm_is_sample else "ESTIMATE"
    metro_label = metro.label if (metro and sc["base"].metro_impressions_day > 0) else "ESTIMATE"
    imp_label = weakest(traffic_label, metro_label)
    sov = placement.share_of_voice

    def m(attr: str, label: str, source: str, unit: str) -> Metric:
        return Metric(getattr(sc["base"], attr), getattr(sc["low"], attr), getattr(sc["high"], attr),
                      label, source, unit)

    metrics = {
        "vehicles_day": m("vehicles_day", traffic_label, vol_source + " (sum over visible flows)", "vehicles/day"),
        "people_day": m("people_day", traffic_label, "Vehicles x occupancy", "people/day"),
        "impressions_day": m("impressions_day", imp_label,
                             "Sum of flow volume x occupancy x mean visibility (+ metro)", "impressions/day"),
        "impressions_month": m("impressions_month", imp_label, "Daily impressions x days per month",
                               "impressions/month"),
        "unique_month": m("unique_month", imp_label, "Monthly impressions / monthly pass frequency f",
                          "people/month"),
        "metro_impressions_day": m("metro_impressions_day", metro_label,
                                   metro.source if metro else "No metro track in the cone", "impressions/day"),
    }
    metrics["advertiser_impressions_day"] = metrics["impressions_day"].scaled(
        sov, f"Placement impressions x share of voice ({sov:.2f})")
    metrics["advertiser_impressions_month"] = metrics["impressions_month"].scaled(
        sov, f"Placement impressions x share of voice ({sov:.2f})")
    metrics["mean_visibility"] = Metric(mean_v, mean_v, mean_v, "ESTIMATE",
                                        "Mean V over visible segments (SOV = 1)", "0..1")
    return PlacementReach(sc, metro, mean_v, vol_source, traffic_label, metrics)
