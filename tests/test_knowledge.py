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


def test_three_industries_read_different_facts(world):
    """Car, property and retail campaigns must not be the same filter with a new name."""
    _, pcfg, _, facts = world
    used = {c.id: {p.fact.id for p in knowledge.select(facts, c) if p.used} for c in pcfg.campaign_options()}
    cats = {c.brand_category.split("_")[0] for c in pcfg.campaign_options()}
    assert len(cats) == 3, cats
    ids = list(used)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            assert used[a] ^ used[b], (a, b)          # each pair differs in what it uses
    by = {f.id: f for f in facts}
    assert any("shopping" in by[i].tags for i in used["retail_festival"])
    assert any("property" in by[i].tags or "premium" in by[i].tags for i in used["property_launch"])


def test_fit_tilt_keeps_the_average_share_and_moves_the_plan(world):
    """Local fit moves each board's campaign-audience share, not the campaign's overall share."""
    from ooh.pipeline import compute, prepare

    _, pall, params, _ = world
    preps = prepare(pall, params, allow_download=False)
    plans = {}
    for c in pall.campaign_options():
        pcfg = pall.with_campaign(c.id)
        flat = Params(load_assumptions(), {"interest_share": c.interest_share, "fit_tilt": 0.0})
        tilted = Params(load_assumptions())                        # the campaign's own share and tilt
        r0, r1 = compute(preps, pcfg, flat), compute(preps, pcfg, tilted)
        s0 = [r.profile.interest_share.value for r in r0.placements.values()]
        s1 = [r.profile.interest_share.value for r in r1.placements.values()]
        assert len(set(s0)) == 1                                   # flat without the tilt
        assert sum(s1) / len(s1) == pytest.approx(s0[0], rel=1e-6)  # same average with it
        assert len(set(round(x, 6) for x in s1)) == (1 if not c.fit_tilt else len(s1))  # SUV: the brief's flat share
        assert all(r.profile.interest_share.label == "ASSUMPTION" for r in r1.placements.values())
        plans[c.id] = {s.placement for s in r1.plan}
    premium = {p.id for p in pall.placements if p.area.split("/")[0].strip() in knowledge.PREMIUM_AREAS}
    assert plans["property_launch"] & premium
    # No prices: the plan is the best mix for the brief's number of boards (SUV 3, the others 2).
    assert all(len(plans[c.id]) == c.boards for c in pall.campaign_options())
    assert len({frozenset(p) for p in plans.values()}) >= 2


def test_stress_test_reports_the_pick_and_where_it_tips(world):
    """Every assumption at its low and high end: the base plan is the app's plan; flips name a tipping point."""
    from ooh.pipeline import compute, plan_ids, prepare, stress_test

    _, pall, params, _ = world
    preps = prepare(pall, params, allow_download=False)
    pcfg = pall.with_campaign("property_launch")
    p = Params(load_assumptions(), {"interest_share": pcfg.campaign.interest_share})
    res = compute(preps, pcfg, p)
    df = stress_test(preps, pcfg, p, events=res.events)
    assert all(tuple(b) == plan_ids(res) for b in df["base_plan"])
    assert (df["swing"] >= 0).all()
    for r in df[~df["holds"]].itertuples():
        lo, hi = sorted([r.low, r.high])
        assert lo <= r.tip_value <= hi and tuple(r.tip_plan) != plan_ids(res)
    assert "budget" not in set(df["parameter"])                    # no money in the brief any more


def test_suv_brief_reproduces_the_solution_brief_table(world):
    """The AI Solution Brief quotes these figures (Section 4); the engine must keep producing them."""
    from ooh import duplication
    from ooh.pipeline import compute, prepare

    _, pall, params, _ = world
    pcfg = pall.with_campaign("suv_launch")
    preps = prepare(pcfg, params, allow_download=False)
    res = compute(preps, pcfg, Params(load_assumptions()))
    doc = {"H1": (112, 419, 126), "H2": (75, 282, 85), "H3": (107, 402, 121), "H4": (84, 315, 95)}
    for pid, (imp, uniq, rel) in doc.items():
        r = res.placements[pid]
        rr = r.profile.relevant_reach.value
        assert (round(r.metrics["impressions_day"].value / 1e3), round(r.metrics["unique_month"].value / 1e3),
                round(rr / 1e3)) == (imp, uniq, rel), pid
    u = res.placements["H1"].metrics["unique_month"]
    assert (round(u.low / 1e3), round(u.high / 1e3)) == (185, 940)
    plan = [s.placement for s in res.plan]
    aud = duplication.combined_relevant(plan, res.plan_items, res.overlap)
    naive = sum(res.placements[i].profile.relevant_reach.value for i in plan)
    # No prices: the brief books 3 boards and the best 3 are DIFC, Dubai Marina and Al Quoz.
    assert len(plan) == pcfg.campaign.boards == 3
    assert sorted(plan) == ["H1", "H3", "H4"] and round(aud / 1e3) == 310 and naive > aud
