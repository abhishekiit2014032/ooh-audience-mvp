import json

import pytest

from ooh import pipeline

KEYS = ["TOMTOM_API_KEY", "DUBAI_PULSE_KEY", "DUBAI_PULSE_SECRET", "MAPILLARY_TOKEN", "ANTHROPIC_API_KEY"]


@pytest.fixture(scope="module")
def results():
    mp = pytest.MonkeyPatch()
    mp.setenv("OOH_NO_DOTENV", "1")
    for k in KEYS:
        mp.delenv(k, raising=False)
    try:
        yield pipeline.run(allow_download=False, write=False)
    finally:
        mp.undo()


def test_pipeline_runs_with_all_keys_unset(results):
    assert set(results.placements) == {"H1", "H2", "H3", "H4"}
    for res in results.placements.values():
        u = res.metrics["unique_month"]
        assert u.value > 0
        assert u.low <= u.value <= u.high


def test_every_metric_is_labelled(results):
    out = pipeline.results_dict(results)
    json.dumps(out, default=str)  # serialisable
    for pid, p in out["placements"].items():
        for name, m in p["metrics"].items():
            assert set(m) >= {"value", "low", "high", "label", "source"}, (pid, name)


def test_duplication_reduces_combined_reach(results):
    assert results.combined_unique_all <= results.naive_unique
    assert results.plan, "plan builder picks at least one placement within budget"
    spent = results.plan[-1].cumulative_cost_aed
    assert spent <= 400_000


def test_delivery_and_activation_outputs(results):
    assert len(results.delivery) > 0
    assert results.delivery_label.startswith("SAMPLE")
    zones = json.loads(results.zones_geojson)
    assert len(zones["features"]) == 4
    assert results.radius_csv.count("\n") == 5
