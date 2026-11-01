"""Audience duplication across placements and the greedy plan builder (methodology step 7).

MVP approximation:

* Exact overlap: if two cones share directed segments, that traffic is counted once.
* Corridor overlap: two faces on the same corridor and direction within 15 km share a
  through-traffic fraction tau = 0.5 of the smaller unique audience; any other pair
  shares tau = 0.1 (ASSUMPTIONS).
* Combined unique reach of a set = sum of uniques - sum of pairwise overlaps
  (first-order inclusion-exclusion), never below the largest single audience.

Phase 2 replaces this with device-level overlap from mobile data.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import geometry as geo
from .config import Params


@dataclass
class PlacementSummary:
    """What duplication needs to know about one placement."""

    id: str
    corridor: str
    lon: float
    lat: float
    travel_bearing: float
    unique: float                 # base unique monthly audience
    relevant: float               # base relevant reach
    interest_share: float
    price_level: int              # ASSUMPTION rating 1-4, shown next to the plan, never used to pick it
    segment_unique: dict[str, float]  # unique audience attributable to each included segment id


def pair_overlap(a: PlacementSummary, b: PlacementSummary, params: Params) -> tuple[float, str]:
    """Overlap in unique people between two placements, and which rule produced it."""
    shared = set(a.segment_unique) & set(b.segment_unique)
    exact = min(sum(a.segment_unique[s] for s in shared), sum(b.segment_unique[s] for s in shared))

    dist_km = geo.haversine_m(a.lon, a.lat, b.lon, b.lat) / 1000
    same_dir = geo.angle_diff(a.travel_bearing, b.travel_bearing) <= 45
    same = (a.corridor == b.corridor) and same_dir and dist_km <= params.base("corridor_max_km")
    tau = params.base("same_corridor_tau") if same else params.base("different_corridor_tau")
    corridor = tau * min(a.unique, b.unique)
    rule = (f"same corridor and direction, {dist_km:.1f} km apart: tau {tau:.2f}" if same
            else f"different corridor, direction or > {params.base('corridor_max_km'):.0f} km "
                 f"({dist_km:.1f} km): tau {tau:.2f}")
    if exact > corridor:
        return exact, f"shared road segments ({len(shared)})"
    return corridor, rule


def overlap_matrix(items: list[PlacementSummary], params: Params) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pairwise overlap in people (diagonal = each placement's own unique audience) and the rules."""
    ids = [p.id for p in items]
    mat = pd.DataFrame(0.0, index=ids, columns=ids)
    rules = pd.DataFrame("", index=ids, columns=ids)
    for i, a in enumerate(items):
        mat.loc[a.id, a.id] = a.unique
        rules.loc[a.id, a.id] = "own unique audience"
        for b in items[i + 1:]:
            ov, rule = pair_overlap(a, b, params)
            mat.loc[a.id, b.id] = mat.loc[b.id, a.id] = ov
            rules.loc[a.id, b.id] = rules.loc[b.id, a.id] = rule
    return mat, rules


def combined_unique(ids: list[str], uniques: dict[str, float], mat: pd.DataFrame) -> float:
    """First-order inclusion-exclusion, floored at the largest single audience."""
    if not ids:
        return 0.0
    total = sum(uniques[i] for i in ids)
    overlaps = sum(mat.loc[a, b] for k, a in enumerate(ids) for b in ids[k + 1:])
    return max(total - overlaps, max(uniques[i] for i in ids))


@dataclass
class PlanStep:
    step: int
    placement: str
    incremental_relevant: float     # new target people this board adds to the ones before it
    combined_relevant: float        # de-duplicated target people of the plan so far
    naive_relevant: float           # the same boards simply added up (counts shared people twice)


def combined_relevant(ids: list[str], items: list[PlacementSummary], mat: pd.DataFrame) -> float:
    """De-duplicated relevant reach of a set of placements (same rule as combined_unique, in relevant people)."""
    if not ids:
        return 0.0
    by_id = {p.id: p for p in items}
    total = sum(by_id[i].relevant for i in ids)
    ov = sum(mat.loc[a, b] * (by_id[a].interest_share + by_id[b].interest_share) / 2
             for k, a in enumerate(ids) for b in ids[k + 1:])
    return max(total - ov, max(by_id[i].relevant for i in ids))


def best_plan(items: list[PlacementSummary], mat: pd.DataFrame, boards: int) -> list[PlanStep]:
    """The mix of `boards` billboards that reaches the most target people (shared people counted once).

    Every mix is tried when there are few (4 boards = at most 6 mixes); with many boards it falls back
    to adding, one at a time, the board that adds the most new target people. Steps are listed in
    the order that adds the most first, so "what each extra board adds" reads top to bottom.
    """
    from itertools import combinations
    from math import comb

    ids = [p.id for p in items]
    k = max(0, min(boards, len(ids)))
    rel = {p.id: p.relevant for p in items}

    def combined_rel(sel: list[str]) -> float:
        return combined_relevant(sel, items, mat)

    if k and comb(len(ids), k) <= 5000:
        pick = list(max(combinations(ids, k), key=lambda c: (combined_rel(list(c)), tuple(-ids.index(i) for i in c))))
    else:
        pick = ids
    chosen: list[str] = []
    steps: list[PlanStep] = []
    pool = [i for i in ids if i in pick]
    while len(chosen) < k:
        current = combined_rel(chosen)
        gains = {i: combined_rel(chosen + [i]) - current for i in pool if i not in chosen}
        if not gains:
            break
        i = max(gains, key=lambda x: (gains[x], -ids.index(x)))
        chosen.append(i)
        steps.append(PlanStep(len(steps) + 1, i, gains[i], combined_rel(chosen), sum(rel[j] for j in chosen)))
    return steps


def segment_unique_shares(scored: pd.DataFrame, flows: pd.DataFrame, unique: float) -> dict[str, float]:
    """Spread a placement's unique audience over its included segments, by impression weight."""
    if scored.empty or flows.empty or unique <= 0:
        return {}
    inc = scored[scored["included"]]
    flow_imp = flows.set_index("flow")["impressions_day"]
    total = float(flow_imp.sum())
    if total <= 0:
        return {}
    out: dict[str, float] = {}
    for flow, g in inc.groupby("flow"):
        share = float(flow_imp.get(flow, 0.0)) / total
        if len(g):
            per_seg = unique * share / len(g)
            for sid in g["segment_id"]:
                out[sid] = per_seg
    return out


def uniques_dict(items: list[PlacementSummary]) -> dict[str, float]:
    return {p.id: p.unique for p in items}


def naive_sum(items: list[PlacementSummary]) -> float:
    return float(np.sum([p.unique for p in items]))
