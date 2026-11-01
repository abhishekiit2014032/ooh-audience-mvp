"""People facts from the news: validation, grouping, campaign windows and the crowd conversion (offline)."""

from datetime import date

import pytest

from ooh import footprint as fp
from ooh.config import load_placements

URL = "https://news.example.com/motor-show"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(fp, "PEOPLE_PATH", tmp_path / "people.json")
    monkeypatch.setattr(fp, "MANUAL_PEOPLE_PATH", tmp_path / "none.yaml")
    monkeypatch.setattr(fp, "_headlines_for", lambda key: [])
    return tmp_path


def fact(**kw) -> dict:
    base = {"kind": "event_attendance", "what": "Example Motor Show", "place": "Dubai World Trade Centre",
            "value": 35000, "unit": "visitors", "period": "event", "event_start": "2026-11-20",
            "event_end": "2026-11-21", "tags": ["cars"], "quote": "The show welcomed 35,000 visitors.",
            "source_url": URL, "source_title": "Example News", "confidence": 0.9, "measure": "count"}
    return {**base, **kw}


@pytest.mark.parametrize("value,quote,ok", [
    (35000, "It drew 35,000 people.", True),
    (35000, "It drew 35k people.", True),
    (1_200_000, "Over 1.2 million riders used the station.", True),
    (35000, "Thousands of people came.", False),
    (35000, "It drew 3,500 people.", False),
])
def test_quote_must_state_the_number(value, quote, ok):
    assert fp.quote_has_number(value, quote) is ok


def test_search_keeps_only_quoted_numbers_with_real_links(isolated):
    pcfg = load_placements()
    rows = [fact(),
            fact(what="Made-up Expo", source_url="https://invented.example.org/page"),
            fact(what="Vague Fair", quote="Huge crowds are expected.")]
    store = fp.refresh(pcfg, force=True, only=["H1"], search=lambda s, a, b, h: (rows, {URL}))
    by_what = {f["what"]: f for f in store.facts.values()}
    assert by_what["Example Motor Show"]["status"] == "kept"
    assert by_what["Example Motor Show"]["placements"] == ["H1"]
    assert "not among the pages" in by_what["Made-up Expo"]["reason"]
    assert "does not state" in by_what["Vague Fair"]["reason"]
    assert (isolated / "people.json").exists()


def test_several_sources_make_one_number_with_a_range():
    rows = [fact(), fact(value=40000, quote="About 40,000 visitors came.", source_url=URL + "/2"),
            fact(what="Example Motor Show 2026 (record)", value=38000, quote="38,000 attended.", source_url=URL + "/3")]
    for r in rows:
        r["status"], r["placements"] = "kept", ["H1"]
    groups = fp.group_facts(rows)
    assert len(groups) == 1
    g = groups[0]
    assert (g.low, g.value, g.high) == (35000, 38000, 40000)
    assert len(g.sources) == 3


def test_campaign_window_and_conversion(params):
    pcfg = load_placements()
    camps = {c.id: c for c in pcfg.campaign_options()}
    row = {**fact(), "status": "kept", "placements": ["H1"]}
    groups = fp.group_facts([row])
    people_day = {p.id: 300_000.0 for p in pcfg.placements}
    shares = {p.id: 0.3 for p in pcfg.placements}
    nov = fp.campaign_pulse(groups, pcfg, camps["suv_launch"], params, people_day, shares)["H1"]
    assert len(nov.events) == 1
    e = nov.events[0]
    pass_share = params.base("news_event_pass_share")
    assert e.extra_people == pytest.approx(35000 * pass_share)
    assert e.matches_campaign and e.extra_target == pytest.approx(e.extra_people * params.base("news_audience_match_share"))
    # the same fact sits outside the December campaign: context only, nothing modelled
    dec = fp.campaign_pulse(groups, pcfg, camps["luxury_launch"], params, people_day, shares)["H1"]
    assert not dec.events and len(dec.later) == 1 and dec.extra_people == 0


def test_capacity_is_never_modelled_and_crowds_are_capped(params):
    pcfg = load_placements()
    camp = pcfg.campaign
    cap_row = {**fact(measure="capacity"), "status": "kept", "placements": ["H1"]}
    huge = {**fact(what="Huge Run", value=5_000_000, quote="5 million runners.", tags=["sports"]),
            "status": "kept", "placements": ["H3"]}
    pulse = fp.campaign_pulse(fp.group_facts([cap_row, huge]), pcfg, camp, params,
                              {p.id: 10_000.0 for p in pcfg.placements}, {p.id: 0.3 for p in pcfg.placements})
    assert not pulse["H1"].events
    e = pulse["H3"].events[0]
    assert e.capped and e.extra_people == pytest.approx(params.base("event_max_daily_change") * 10_000 * 2)
    assert not e.matches_campaign and e.extra_target == pytest.approx(e.extra_people * 0.3)


def test_switched_off_facts_are_ignored():
    row = {**fact(), "status": "kept", "placements": ["H1"], "enabled": False}
    assert fp.group_facts([row]) == []


def test_two_editions_of_one_show_make_one_card():
    old = {**fact(what="Example Motor Show", value=100000, quote="100,000 visitors.", figure_year=2017,
                  event_start=None, event_end=None), "status": "kept", "placements": ["H1"]}
    new = {**fact(what="Example Motor Show (edition year not stated)", value=108357, quote="108,357 attendees",
                  event_start=None, event_end=None, source_url=URL + "/b"), "status": "kept", "placements": ["H1"]}
    groups = fp.group_facts([old, new])
    assert len(groups) == 2
    merged = fp.merge_by_name(groups)
    assert len(merged) == 1 and merged[0].value == 108357 and len(merged[0].sources) == 2


def test_same_dated_crowd_in_two_units_is_counted_once():
    a = {**fact(kind="transit_ridership", what="Burj Khalifa/Dubai Mall Metro Station on New Year's Eve", value=110000,
                quote="110,000 riders", period="day", event_start="2026-12-31", event_end="2026-12-31", tags=["general"]),
         "status": "kept", "placements": ["H1"]}
    b = {**a, "what": "Burj Khalifa-Dubai Mall Metro Station on New Year's Eve", "period": "event", "source_url": URL + "/x"}
    assert len(fp.group_facts([a, b])) == 1
