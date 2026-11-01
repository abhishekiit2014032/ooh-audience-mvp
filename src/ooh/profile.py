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


# What a campaign's industry looks for around a board, and how Meta names its interests.
CATEGORY_PLACES = {"automotive": ("Car showrooms and services", "car showrooms, rentals and services"),
                   "real_estate": ("Offices and business", "offices and business places"),
                   "retail": ("Retail and malls", "shops and malls")}
INTEREST_LABELS = {"automobiles": "Automobiles", "suv": "SUVs", "luxury_vehicles": "Luxury vehicles",
                   "real_estate": "Real estate", "shopping": "Shopping"}
META_FILTERS = {"automotive": "Automobiles, SUVs, Luxury vehicles", "real_estate": "Real estate, Property investment",
                "retail": "Shopping, Shopping malls, Fashion"}


def category_key(brand_category: str) -> str:
    """'automotive_suv' -> 'automotive'; unknown categories fall back to automotive."""
    return next((k for k in CATEGORY_PLACES if brand_category.startswith(k)), "automotive")


def place_line(category: str, poi_counts: dict) -> str:
    cat, words = CATEGORY_PLACES[category_key(category)]
    return f"{poi_counts.get(cat, 0)} {words} within 1 km"


def build_profile(placement: Placement, pois: gpd.GeoDataFrame, unique: Metric,
                  impressions_month: Metric, params: Params, road_share: float,
                  interest_key: str | None = "automobiles", audience: str = "car-interest",
                  category: str = "automotive") -> Profile:
    meta_all = load_json_input("meta_reach.json")
    meta = meta_all["placements"].get(placement.id, {})
    meta_is_sample = bool(meta_all.get("is_sample", True)) or not meta
    dsc = load_json_input("dsc_population.json")
    poi_counts = count_pois(pois) if len(pois) else {k: 0 for k in POI_CATEGORIES}

    shares = np.asarray(params.cfg.hourly_profile.shares)
    commuter_share = float(shares[list(COMMUTER_HOURS)].sum())

    # Interest share: Meta when real values exist, else the assumption.
    if interest_key is None:
        interest = Metric(1.0, 1.0, 1.0, "ESTIMATE", "Campaign targets everyone who passes", "share")
    elif not meta_is_sample and "interest_share" in meta and interest_key in meta["interest_share"]:
        s = float(meta["interest_share"][interest_key])
        interest = Metric(s, s * 0.8, s * 1.2, "ESTIMATE",
                          f"Meta Ads Manager reach estimate, interest '{interest_key}'", "share")
    else:
        interest = Metric(params.base("interest_share"), params.get("interest_share", "low"),
                          params.get("interest_share", "high"), "ASSUMPTION",
                          f"Assumed share of {audience} until Meta values are entered", "share")

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
            place_line(category, poi_counts),
        ],
        "Interest": [
            f"{INTEREST_LABELS.get(interest_key or '', 'Everyone passing')}: {interest.value:.0%} of the audience "
            f"({interest.label})",
            f"Meta interest filters to use: {META_FILTERS.get(category_key(category), 'none (everyone passing)')}",
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


def tilt_interest(prof: Profile, unique: Metric, impressions_month: Metric, factor: float, fit: float) -> Profile:
    """Scale the campaign-audience share by a local-fit factor (mean 1 across boards, so the campaign's
    overall share is unchanged; only the split between boards moves). The result is an ASSUMPTION."""
    import dataclasses

    i = prof.interest_share
    v, lo, hi = (min(1.0, x * factor) for x in (i.value, i.low, i.high))
    interest = Metric(v, lo, hi, weakest(i.label, "ASSUMPTION"),
                      f"{i.source}; x {factor:.2f} for local fit {fit:.0%} (ASSUMPTION, fit_tilt)", i.unit)
    label = weakest(unique.label, interest.label)
    relevant = Metric(unique.value * v, unique.low * v, unique.high * v, label,
                      "Unique monthly audience x interest share (tilted by local fit)", "people/month")
    rel_imp = Metric(impressions_month.value * v, impressions_month.low * v, impressions_month.high * v, label,
                     "Monthly impressions x interest share (tilted by local fit)", "impressions/month")
    return dataclasses.replace(prof, interest_share=interest, relevant_reach=relevant,
                               relevant_impressions_month=rel_imp)
