"""Knowledge layer: facts link sources to outcomes as the registry says, the campaign filter is
to the point, and location scores stay in 0-100."""

import pytest

from ooh import footprint, knowledge, pipeline
from ooh.config import Params, load_assumptions, load_placements
from ooh.sources import OUTPUTS, registry

KEYS = ["TOMTOM_API_KEY", "DUBAI_PULSE_KEY", "DUBAI_PULSE_SECRET", "MAPILLARY_TOKEN", "ANTHROPIC_API_KEY"]


@pytest.fixture(scope="module")
def world():
    mp = pytest.MonkeyPatch()
    mp.setenv("OOH_NO_DOTENV", "1")
    for k in KEYS:
        mp.delenv(k, raising=False)
    try:
        pcfg, params = load_placements(), Params(load_assumptions())
        res = pipeline.run(allow_download=False, write=False)
        yield res, pcfg, params, knowledge.build(res, pcfg, params)
    finally:
        mp.undo()


def test_every_fact_names_known_sources_topics_and_outcomes(world):
    _, _, _, facts = world
    reg = {s.id for s in registry()}
    R = knowledge.rules()
    assert len({f.id for f in facts}) == len(facts)
    for f in facts:
        assert f.sources and set(f.sources) <= reg, f.id
        assert f.topic in R["topics"], f.id
        assert set(f.feeds) <= set(OUTPUTS) == set(R["outcomes"]), f.id


def test_registry_links_match_the_facts(world):
    """What each connected source claims to feed is exactly what its facts feed."""
    _, _, _, facts = world
    derived: dict[str, set] = {}
    for f in facts:
        for s in f.sources:
            derived.setdefault(s, set()).update(f.feeds)
    for s in registry():
        if s.status == "not connected":
            assert s.id not in derived, s.id
            continue
        if s.id not in derived:      # connected but filed nothing (e.g. an empty optional input)
            continue
        assert derived[s.id] == set(s.feeds), (s.id, sorted(derived[s.id]), s.feeds)
        assert bool(s.context_only) == (not derived[s.id]), s.id


def test_campaign_filter_keeps_core_and_drops_other_campaigns(world):
    res, pcfg, _, facts = world
    for c in pcfg.campaign_options():
        picks = knowledge.select(facts, c)
        by = {p.fact.id: p for p in picks}
        thr = knowledge.rules()["relevance"]["threshold"]
        for p in picks:
            assert 0 <= p.score <= 1 and p.used == (p.score >= thr) and p.reason
            camp_tags = [t for t in p.fact.tags if t.startswith("campaign:")]
            if p.fact.core and not camp_tags:
                assert p.used, p.fact.id
            if camp_tags and f"campaign:{c.id}" not in camp_tags:
                assert not p.used, (c.id, p.fact.id)
        used = sum(p.used for p in picks)
        assert 0 < used < len(picks), c.id        # filtered, not everything
        assert any(by[i].used for i in by if i.endswith(":price"))


def test_location_filter_only_returns_that_location(world):
    res, pcfg, _, facts = world
    pid = next(iter(res.placements))
    for p in knowledge.select(facts, pcfg.campaign, pid):
        assert p.fact.location == pid or (p.fact.location == "all" and "people_news" not in p.fact.sources)


def test_scores_are_0_to_100_with_a_best_location(world):
    res, pcfg, params, facts = world
    for c in pcfg.campaign_options():
        p2 = pcfg.with_campaign(c.id)
        pulse = footprint.pulse_for_results(res, p2, c, params)
        sc = knowledge.score_locations(res, p2, c, facts, pulse)
        assert set(sc["criteria"]) == set(knowledge.rules()["criteria"])
        assert abs(sum(sc["weights"].values()) - 100) < 1e-6
        for k, per in sc["criteria"].items():
            vals = [v["score"] for v in per.values()]
            assert all(0 <= v <= 100 for v in vals), (c.id, k)
            assert all(v["why"] for v in per.values())
            if k in ("target", "value"):
                assert max(vals) == pytest.approx(100), (c.id, k)
        assert all(0 <= t <= 100 for t in sc["total"].values())
