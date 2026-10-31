import json

from ooh import sources
from ooh.brain_viz import brain_html, diagram_data


def test_scores_in_range_and_ordered():
    reg = sources.registry()
    assert len({s.id for s in reg}) == len(reg)
    for s in reg:
        assert 0 <= s.score <= 100 and 0 <= s.potential <= 100
        assert s.score <= s.potential or s.status in ("live", "cached", "configured", "on demand")
    by = {s.status: s for s in reg}
    not_connected = [s.score for s in reg if s.status == "not connected"]
    samples = [s.score for s in reg if s.status == "sample"]
    live = [s.score for s in reg if s.status in ("live", "cached")]
    assert not_connected and all(x == 0 for x in not_connected)
    assert samples and live and max(samples) < min(live)
    assert by  # registry has statuses


def test_every_edge_points_to_a_known_output():
    for s in sources.registry():
        assert s.engine in sources.ENGINE
        assert s.feeds, s.id
        for o in s.feeds:
            assert o in sources.OUTPUTS, (s.id, o)
            assert o in sources.ENGINE_OUTPUTS[s.engine], (s.id, o, "output built by the other engine half")
    covered = {o for outs in sources.ENGINE_OUTPUTS.values() for o in outs}
    assert covered == set(sources.OUTPUTS)


def test_claude_is_engine_not_scored_source():
    assert all("claude" not in s.name.lower() for s in sources.registry())


def test_status_follows_keys(monkeypatch):
    monkeypatch.setenv("TOMTOM_API_KEY", "test-value")
    flow = next(s for s in sources.registry() if s.id == "tomtom_flow")
    assert flow.status == "live" and flow.score > 0
    monkeypatch.delenv("TOMTOM_API_KEY")
    flow = next(s for s in sources.registry() if s.id == "tomtom_flow")
    assert flow.status == "not connected" and flow.score == 0


def test_diagram_html_has_data_and_no_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-secret-test-value")
    html = brain_html(diagram_data())
    assert "__DATA__" not in html and "sk-ant" not in html
    payload = json.loads(html.split("const DATA = ", 1)[1].split(";\n", 1)[0])
    assert len(payload["sources"]) == len(sources.registry())
    assert payload["engine"]["ai"]["status"] == "active"
