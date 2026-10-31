"""Audience profile: four public signals -> segments -> relevant reach.

Signals (group level only, never individual data):

* Demographics: Meta Ads Manager reach estimate for a pin + radius (data/inputs/meta_reach.json).
* Place context: OSM points of interest within 1 km of the face.
* Time pattern: the hourly traffic profile (commuter peaks vs off-peak).
* Population check: Dubai Statistics Center figures (data/inputs/dsc_population.json).

Relevant reach = unique monthly audience x interest share. The interest share comes from
Meta once real values are entered; until then it is the slider ASSUMPTION.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np

from .config import INPUT_DIR, Params, Placement
from .metrics import Metric, weakest

POI_CATEGORIES: dict[str, dict[str, set[str] | bool]] = {
    "Offices and business": {"office": True, "amenity": {"bank", "coworking_space", "conference_centre"}},
    "Retail and malls": {"shop": True, "amenity": {"marketplace"}},
    "Hotels and tourism": {"tourism": {"hotel", "apartment", "guest_house", "hostel", "attraction", "museum"}},
    "Food and leisure": {"amenity": {"restaurant", "cafe", "bar", "fast_food", "pub", "cinema"}, "leisure": True},
    "Car showrooms and services": {"shop": {"car", "car_repair", "car_parts", "tyres"},
                                   "amenity": {"car_rental", "car_wash", "fuel"}},
}

COMMUTER_HOURS = (7, 8, 9, 17, 18, 19)


@dataclass
class Profile:
    placement_id: str
    meta: dict
    meta_is_sample: bool
    poi_counts: dict[str, int]
    commuter_share: float
    dsc: dict
    segments: dict[str, list[str]]
    interest_share: Metric
    relevant_reach: Metric
    relevant_impressions_month: Metric
    triangulation: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "placement_id": self.placement_id,
            "meta": self.meta,
            "meta_is_sample": self.meta_is_sample,
            "poi_counts": self.poi_counts,
            "commuter_share": self.commuter_share,
            "segments": self.segments,
            "interest_share": self.interest_share.to_dict(),
            "relevant_reach": self.relevant_reach.to_dict(),
            "relevant_impressions_month": self.relevant_impressions_month.to_dict(),
            "triangulation": self.triangulation,
        }


def load_json_input(name: str) -> dict:
    return json.loads((INPUT_DIR / name).read_text())


def count_pois(pois: gpd.GeoDataFrame) -> dict[str, int]:
    """Count OSM points of interest per category. A POI counts in every category it matches."""
    counts = {}
    for cat, rules in POI_CATEGORIES.items():
        mask = np.zeros(len(pois), dtype=bool)
        for col, allowed in rules.items():
            if col not in pois.columns:
                continue
            values = pois[col].fillna("")
            if allowed is True:
                hit = values != ""
                if col == "shop":  # car shops belong to their own category
                    hit &= ~values.isin(["car", "car_repair", "car_parts", "tyres"])
            else:
                hit = values.isin(allowed)
            mask |= hit.to_numpy()
        counts[cat] = int(mask.sum())
    return counts


def _age_share(age: dict[str, float], bands: tuple[str, ...]) -> float:
    return float(sum(v for k, v in age.items() if k in bands))


def build_profile(placement: Placement, pois: gpd.GeoDataFrame, unique: Metric,
                  impressions_month: Metric, params: Params, road_share: float) -> Profile:
    meta_all = load_json_input("meta_reach.json")
    meta = meta_all["placements"].get(placement.id, {})
    meta_is_sample = bool(meta_all.get("is_sample", True)) or not meta
    dsc = load_json_input("dsc_population.json")
    poi_counts = count_pois(pois) if len(pois) else {k: 0 for k in POI_CATEGORIES}

    shares = np.asarray(params.cfg.hourly_profile.shares)
    commuter_share = float(shares[list(COMMUTER_HOURS)].sum())

    # Interest share: Meta when real values exist, else the assumption.
    if not meta_is_sample and "interest_share" in meta:
        s = float(meta["interest_share"].get("automobiles", params.base("interest_share")))
        interest = Metric(s, s * 0.8, s * 1.2, "ESTIMATE",
                          "Meta Ads Manager reach estimate, interest 'Automobiles'", "share")
    else:
        interest = Metric(params.base("interest_share"), params.get("interest_share", "low"),
                          params.get("interest_share", "high"), "ASSUMPTION",
                          "Assumed car-interest share until Meta values are entered", "share")

    rr_label = weakest(unique.label, interest.label)
    relevant = Metric(unique.value * interest.value, unique.low * interest.value, unique.high * interest.value,
                      rr_label, "Unique monthly audience x interest share", "people/month")
    relevant_imp = Metric(impressions_month.value * interest.value, impressions_month.low * interest.value,
                          impressions_month.high * interest.value, rr_label,
                          "Monthly impressions x interest share", "impressions/month")

    age = meta.get("age", {})
    gender = meta.get("gender", {})
    core_age = _age_share(age, ("25-34", "35-44", "45-54"))
    premium = placement.area.split("/")[0].strip() in {"DIFC", "Downtown", "Dubai Marina"}
    segments = {
        "Demographic": [
            f"Age 25 to 54: {core_age:.0%} of the Meta audience" if age else "Age mix: enter Meta values",
            f"Gender: {gender.get('male', 0):.0%} male / {gender.get('female', 0):.0%} female" if gender
            else "Gender split: enter Meta values",
            "Income signal: premium area (DIFC, Downtown, Marina; ASSUMPTION)" if premium
            else "Income signal: mixed-income area (ASSUMPTION)",
        ],
        "Behavioural": [
            f"Daily drivers: {road_share:.0%} of impressions come from road traffic",
            f"Commuter pattern: {commuter_share:.0%} of daily traffic in 7-10 am and 5-8 pm peaks",
            f"{poi_counts.get('Car showrooms and services', 0)} car showrooms, rentals and services within 1 km",
        ],
        "Interest": [
            f"Automobiles / SUVs: {interest.value:.0%} of the audience ({interest.label})",
            "Meta interest filters to use: Automobiles, SUVs, Luxury vehicles",
        ],
    }

    triangulation = {}
    if meta.get("audience_size_low") and meta.get("audience_size_high"):
        meta_mid = (meta["audience_size_low"] + meta["audience_size_high"]) / 2
        ratio = unique.value / meta_mid if meta_mid else float("nan")
        limit = params.base("triangulation_flag_ratio")
        triangulation = {
            "meta_audience": meta_mid,
            "computed_unique": unique.value,
            "ratio": ratio,
            "flag": bool(ratio > limit or ratio < 1 / limit),
            "limit": limit,
            "label": "SAMPLE" if meta_is_sample else "ESTIMATE",
        }

    return Profile(placement.id, meta, meta_is_sample, poi_counts, commuter_share, dsc, segments,
                   interest, relevant, relevant_imp, triangulation)
