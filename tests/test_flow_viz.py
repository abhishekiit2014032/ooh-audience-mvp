"""The knowledge-layer flow diagram renders every campaign's graph with consistent ids and no secrets."""

import json

import pytest

from ooh import knowledge, pipeline
from ooh.config import Params, load_assumptions, load_placements
from ooh.flow_viz import flow_html
from ooh.sources import registry


@pytest.fixture(scope="module")
def payload():
    mp = pytest.MonkeyPatch()
    mp.setenv("OOH_NO_DOTENV", "1")
    for k in ["TOMTOM_API_KEY", "DUBAI_PULSE_KEY", "DUBAI_PULSE_SECRET", "MAPILLARY_TOKEN", "ANTHROPIC_API_KEY"]:
        mp.delenv(k, raising=False)
    try:
        pcfg, params = load_placements(), Params(load_assumptions())
        res = pipeline.run(allow_download=False, write=False)
        facts = knowledge.build(res, pcfg, params)
        reg = registry()
        camps = [{"id": c.id, "title": c.title, "emoji": c.emoji, "audience_short": c.audience_short,
                  "graph": knowledge.flow_graph(facts, c, reg)} for c in pcfg.campaign_options()]
        data = {**camps[0]["graph"], "campaigns": camps, "focus_campaign": camps[0]["id"]}
        yield data
    finally:
        mp.undo()


def test_every_link_endpoint_exists(payload):
    for c in payload["campaigns"]:
        g = c["graph"]
        src, top, out = ({x["id"] for x in g[k]} for k in ("sources", "topics", "outcomes"))
        assert g["s2t"] and g["t2o"]
        for e in g["s2t"]:
            assert e["s"] in src and e["t"] in top and 0 <= e["used"] <= e["n"]
        for e in g["t2o"]:
            assert e["t"] in top and e["o"] in out and 0 <= e["used"] <= e["n"]
        assert 0 < g["used"] <= g["total"]


def test_html_embeds_payload_without_secrets(payload, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-secret-test-value")
    html = flow_html(payload)
    assert "sk-ant" not in html
    data = json.loads(html.split("const D = ", 1)[1].split(";\n", 1)[0])
    assert data["focus_campaign"] == payload["focus_campaign"]
    assert len(data["campaigns"]) == len(payload["campaigns"]) >= 2
    assert "function apply" in html and "prefers-reduced-motion" in html


def test_not_connected_sources_have_no_links(payload):
    g = payload["campaigns"][0]["graph"]
    off = {s["id"] for s in g["sources"] if s["status"] == "not connected"}
    assert off and not any(e["s"] in off for e in g["s2t"])
