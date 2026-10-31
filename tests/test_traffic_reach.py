import numpy as np
import pytest

from ooh.reach import compute_reach
from ooh.traffic import capacity_volume
from ooh.visibility import build_segments, score_metro, score_segments


@pytest.mark.parametrize("scenario", ["low", "base", "high"])
@pytest.mark.parametrize("lanes", [1, 3, 6])
def test_hourly_volume_never_exceeds_capacity(params, scenario, lanes):
    vol = capacity_volume(lanes, "motorway", params, scenario)
    assert (vol.hourly <= lanes * 2000 + 1e-9).all()


def test_capacity_cap_fires_at_extreme_utilisation(params):
    vol = capacity_volume(4, "motorway", params.with_override("utilisation", 0.95), "high")
    assert vol.capped_hours > 0
    assert np.max(vol.hourly) == pytest.approx(4 * 2000)


def test_worked_example_h1_volume(params):
    # 6 lanes x 2,000 x 0.40 x 24 = 115,200 vehicles per day (solution design doc, Step 5)
    assert capacity_volume(6, "motorway", params).daily == pytest.approx(115_200)


def _unique(placement, snapped, area, params):
    roads, metro = build_segments(placement, snapped, area, params)
    scored = score_segments(roads, placement, snapped, params)
    ms = score_metro(metro, placement, snapped, params)
    return compute_reach(scored, ms, placement, None, params, False)


def test_unique_audience_falls_when_frequency_rises(placement, snapped, area, params):
    low_f = _unique(placement, snapped, area, params.with_override("monthly_frequency", 4))
    high_f = _unique(placement, snapped, area, params.with_override("monthly_frequency", 12))
    assert high_f.metrics["unique_month"].value < low_f.metrics["unique_month"].value
    # impressions do not depend on frequency
    assert high_f.metrics["impressions_day"].value == pytest.approx(low_f.metrics["impressions_day"].value)


def test_ranges_are_ordered(placement, snapped, area, params):
    r = _unique(placement, snapped, area, params)
    for key in ["vehicles_day", "impressions_day", "impressions_month", "unique_month"]:
        m = r.metrics[key]
        assert m.low <= m.value <= m.high, key
        assert m.label in {"VERIFIED", "ESTIMATE", "ASSUMPTION", "SAMPLE", "CONCEPT"}
