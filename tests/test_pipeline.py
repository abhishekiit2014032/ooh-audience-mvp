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



def test_combined_relevant_matches_plan(results):
    """The executive plan builder prices any mix with the same rule the greedy plan uses."""
    from ooh import duplication

    ids = [s.placement for s in results.plan]
    assert ids
    got = duplication.combined_relevant(ids, results.plan_items, results.overlap)
    assert abs(got - results.plan[-1].combined_relevant) < 1e-6


def test_no_crowds_leaves_the_plan_unchanged(results, params):
    from ooh import footprint as fp
    from ooh.config import load_placements

    pcfg = load_placements()
    pulse = fp.campaign_pulse([], pcfg, pcfg.campaign, params, {}, {})
    plan, _ = fp.plan_with_crowds(results, pulse, pcfg.campaign.budget_aed)
    assert [s.placement for s in plan] == [s.placement for s in results.plan]
