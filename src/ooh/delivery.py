"""Planned versus actual delivery (methodology step 8).

* Plan: advertiser impressions forecast from the baseline period (the same weeks of a prior
  period, here the capacity fallback because no TomTom history is available).
* Actual: the same calculation on campaign-period traffic. For digital faces it is also
  multiplied by actual / planned plays from the media owner's play log.
* Delivery index = actual / planned, per week and per placement.

Without a TomTom key there is no campaign-period traffic, so "actual" traffic is simulated as
baseline x a random factor between 0.85 and 1.10 with a fixed seed, and labelled SAMPLE.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from .config import INPUT_DIR, Campaign, Params, Placement, env_key

SEED = 42


def load_play_log() -> pd.DataFrame:
    df = pd.read_csv(INPUT_DIR / "play_log.csv", parse_dates=["date"])
    df["is_sample"] = df["is_sample"].astype(str).str.lower() == "true"
    return df


def campaign_weeks(campaign: Campaign) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """7-day blocks from plan start to plan end (the last block may be shorter)."""
    weeks = []
    start = campaign.plan_start
    while start <= campaign.plan_end:
        end = min(start + timedelta(days=6), campaign.plan_end)
        weeks.append((pd.Timestamp(start), pd.Timestamp(end)))
        start = end + timedelta(days=1)
    return weeks


def delivery_table(placements: list[Placement], advertiser_daily: dict[str, float],
                   campaign: Campaign, params: Params) -> tuple[pd.DataFrame, str]:
    """Weekly planned vs actual advertiser impressions per placement, and the label of 'actual'."""
    rng = np.random.default_rng(SEED)
    lo, hi = params.base("sample_actual_min"), params.base("sample_actual_max")
    play_log = load_play_log()
    has_tomtom = env_key("TOMTOM_API_KEY") is not None
    rows = []
    for p in placements:
        daily = advertiser_daily.get(p.id, 0.0)
        log = play_log[play_log["placement_id"] == p.id]
        for w, (start, end) in enumerate(campaign_weeks(campaign), start=1):
            days = (end - start).days + 1
            planned = daily * days
            traffic_factor = float(rng.uniform(lo, hi))  # drawn for every week so the seed is stable
            play_factor, play_label = 1.0, "n/a (static face)"
            if p.type == "digital":
                wk = log[(log["date"] >= start) & (log["date"] <= end)]
                if len(wk) and wk["planned_plays"].sum() > 0:
                    play_factor = wk["actual_plays"].sum() / wk["planned_plays"].sum()
                    play_label = "SAMPLE" if wk["is_sample"].any() else "VERIFIED"
                else:
                    play_label = "no play log rows"
            actual = planned * traffic_factor * play_factor
            rows.append({
                "placement": p.id, "week": w, "week_start": start.date().isoformat(),
                "week_end": end.date().isoformat(), "days": days, "planned": planned,
                "traffic_factor": traffic_factor, "play_factor": play_factor, "play_log": play_label,
                "actual": actual, "delivery_index": actual / planned if planned else np.nan,
            })
    # TomTom campaign-period history is not wired in the MVP, so actual stays SAMPLE either way.
    label = "SAMPLE"
    note = ("Simulated campaign traffic (seeded factor {:.2f} to {:.2f})".format(lo, hi)
            + ("; TomTom key found but campaign-period history is a Phase 2 job" if has_tomtom else ""))
    return pd.DataFrame(rows), f"{label}: {note}"
