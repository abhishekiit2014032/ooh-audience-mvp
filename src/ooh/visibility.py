"""Directed road segments around a face, and their 0..1 visibility score.

Two stages, so the dashboard stays fast:

1. :func:`build_segments` (slow, cached): cut every road within the largest possible cone
   radius into ~25 m directed segments and pre-compute distance, angles and line of sight.
2. :func:`score_segments` (fast, vectorised): apply the cone, heading filter and visibility
   factors for the current slider values.

Visibility per segment (methodology step 3)::

    V = D x A x O x S x T x SOV
    D = max(0, 1 - d / R)                 distance
    A = cos(theta), 0 outside half-angle  angle off the facing bearing
    O = 1, or obstruction factor          2D line of sight vs OSM buildings
    S = min(1, face area / 100 m2)        size
    T = min(1, viewing time / 3 s)        dwell
    SOV = slot / loop (digital), 1 static share of voice
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import geometry as geo
from .config import Params, Placement
from .roads import OsmArea, SnappedPlacement
from .traffic import lanes_per_direction, segment_speed_kmh, tomtom_flow_speed

MAX_RADIUS_M = 800  # largest cone radius the UI allows; segments are pre-cut to this


def _flow_key(label: str, highway: str, travel: float) -> str:
    """Group segments a vehicle drives through in one pass: same road, class and direction."""
    bucket = int(((travel + 22.5) % 360) // 45)
    return f"{label}|{highway}|{bucket}"


def _cut(lines: pd.DataFrame, seg_len: float, hx: float, hy: float) -> pd.DataFrame:
    rows = []
    for rec in lines.itertuples(index=False):
        for n, piece in enumerate(geo.split_line(rec.geometry, seg_len)):
            (x1, y1), (x2, y2) = piece.coords[0], piece.coords[-1]
            rows.append({**rec._asdict(), "geometry": piece, "piece": n, "x1": x1, "y1": y1,
                         "x2": x2, "y2": y2, "length_m": piece.length})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["mx"] = (df["x1"] + df["x2"]) / 2
    df["my"] = (df["y1"] + df["y2"]) / 2
    df["travel_bearing"] = geo.bearing_xy_np(df["x1"], df["y1"], df["x2"], df["y2"])
    df["dist_m"] = np.hypot(df["mx"] - hx, df["my"] - hy)
    df["bearing_from_face"] = geo.bearing_xy_np(hx, hy, df["mx"], df["my"])
    df["bearing_to_face"] = (df["bearing_from_face"] + 180) % 360
    return df


def build_segments(placement: Placement, snapped: SnappedPlacement, area: OsmArea,
                   params: Params) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cut roads and metro lines near the face into directed segments with geometry pre-computed.

    Returns (road_segments, metro_segments). Parameter-dependent filters are applied later.
    """
    hx, hy = snapped.x, snapped.y
    seg_len = params.base("segment_length_m")
    reach = MAX_RADIUS_M + seg_len

    edges = area.edges
    near = edges[edges.geometry.distance(geo.Point(hx, hy)) <= reach].copy()
    near["label"] = [n_en or n or r or h for n_en, n, r, h in
                     zip(near["name_en"], near["name"], near["ref"], near["highway"])]
    cols = ["edge_id", "label", "highway", "lanes_osm", "maxspeed_osm", "oneway", "geometry"]
    roads = _cut(near[cols], seg_len, hx, hy)
    if not roads.empty:
        roads = roads[roads["dist_m"] <= reach].reset_index(drop=True)
        roads["heading_diff"] = geo.angle_diff(roads["travel_bearing"], roads["bearing_to_face"])
        roads["flow"] = [_flow_key(l, h, t) for l, h, t in
                         zip(roads["label"], roads["highway"], roads["travel_bearing"])]
        roads["segment_id"] = [f"{e}#{n}" for e, n in zip(roads["edge_id"], roads["piece"])]
        roads["blocked"] = geo.line_of_sight_blocked(
            roads["mx"].to_numpy(), roads["my"].to_numpy(), hx, hy, list(area.buildings.geometry))

    metro = pd.DataFrame()
    if len(area.rail):
        rail = area.rail.copy()
        rail = rail[rail.geometry.distance(geo.Point(hx, hy)) <= reach].explode(index_parts=False)
        if len(rail):
            rail["label"] = rail["name"].fillna("metro") if "name" in rail.columns else "metro"
            metro = _cut(rail[["label", "geometry"]], seg_len, hx, hy)
            if not metro.empty:
                metro = metro[metro["dist_m"] <= reach].reset_index(drop=True)
                metro["blocked"] = geo.line_of_sight_blocked(
                    metro["mx"].to_numpy(), metro["my"].to_numpy(), hx, hy, list(area.buildings.geometry))
    return roads, metro


def _common_factors(df: pd.DataFrame, placement: Placement, snapped: SnappedPlacement,
                    params: Params, radius: float) -> pd.DataFrame:
    half_angle = params.base("half_angle_deg")
    theta = geo.angle_diff(df["bearing_from_face"], snapped.facing_bearing_deg)
    df["theta"] = theta
    df["in_cone"] = (df["dist_m"] <= radius) & (theta <= half_angle)
    df["D"] = np.clip(1 - df["dist_m"] / radius, 0, 1)
    df["A"] = np.where(theta <= half_angle, np.cos(np.radians(theta)), 0.0)
    df["O"] = np.where(df["blocked"], params.base("obstruction_factor"), 1.0)
    df["S"] = min(1.0, placement.face_area_m2 / params.base("full_size_area_m2"))
    return df


def score_segments(roads: pd.DataFrame, placement: Placement, snapped: SnappedPlacement,
                   params: Params, sov: float = 1.0) -> pd.DataFrame:
    """Apply the cone, heading filter and visibility factors. Returns all segments with flags.

    Dwell T uses the viewing time of the whole visible approach on that flow (visible length
    / speed), not the length of one 25 m piece: a driver sees the face for the full approach,
    and per-piece time would make T depend on how finely the road was cut.
    """
    if roads.empty:
        return roads
    radius = params.base("cone_radius_m")
    df = _common_factors(roads.copy(), placement, snapped, params, radius)
    lanes = [lanes_per_direction(lo, ow, hw, params.cfg) for lo, ow, hw in
             zip(df["lanes_osm"], df["oneway"], df["highway"])]
    df["lanes"] = [n for n, _ in lanes]
    df["lanes_source"] = [s for _, s in lanes]
    df["heading_ok"] = df["heading_diff"] <= params.base("heading_tolerance_deg")
    df["included"] = df["in_cone"] & df["heading_ok"]

    speeds = [segment_speed_kmh(m, h, params) for m, h in zip(df["maxspeed_osm"], df["highway"])]
    df["speed_kmh"] = [s for s, _ in speeds]
    df["speed_source"] = [s for _, s in speeds]
    tt = tomtom_flow_speed(placement.lat, placement.lon)
    if tt:
        main = df["highway"].isin(["motorway", "trunk"])
        df.loc[main, "speed_kmh"] = tt
        df.loc[main, "speed_source"] = "TomTom Traffic Flow"

    inc = df[df["included"]]
    visible_len = inc.groupby("flow")["length_m"].sum()
    flow_speed = inc.groupby("flow")["speed_kmh"].median()
    view_s = (visible_len / (flow_speed / 3.6)).rename("view_s")
    df = df.merge(view_s, left_on="flow", right_index=True, how="left")
    df["view_s"] = df["view_s"].fillna(0.0)
    df["T"] = np.clip(df["view_s"] / params.base("full_dwell_seconds"), 0, 1)
    df["SOV"] = sov
    df["V"] = np.where(df["included"], df["D"] * df["A"] * df["O"] * df["S"] * df["T"] * df["SOV"], 0.0)
    return df


def score_metro(metro: pd.DataFrame, placement: Placement, snapped: SnappedPlacement,
                params: Params, sov: float = 1.0) -> pd.DataFrame:
    """Visibility for metro track segments. Riders face both ways, so no heading filter."""
    if metro.empty:
        return metro
    radius = params.base("cone_radius_m")
    df = _common_factors(metro.copy(), placement, snapped, params, radius)
    df["included"] = df["in_cone"]
    visible_len = df.loc[df["included"], "length_m"].sum()
    view_s = visible_len / (params.base("metro_speed_kmh") / 3.6)
    df["T"] = min(1.0, view_s / params.base("full_dwell_seconds"))
    df["SOV"] = sov
    df["V"] = np.where(df["included"], df["D"] * df["A"] * df["O"] * df["S"] * df["T"] * df["SOV"], 0.0)
    return df
