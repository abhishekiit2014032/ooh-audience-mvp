"""Online signals: ledger, de-duplication, noise filter and forecast adjustments (all offline)."""

from datetime import date

import numpy as np
import pytest

from ooh import signals
from ooh.config import load_placements
from ooh.metrics import Metric
from ooh.news import NewsItem
from ooh.signals import Extraction, Ledger, campaign_forecast

RIDE = ["Dubai Ride takes over Sheikh Zayed Road", "Sheikh Zayed Road closed for Dubai Ride",
        "Dubai Ride 2026: RTA announces road closures", "Dubai Ride: what you need to know",
        "Cyclists to take over Sheikh Zayed Road on Sunday"]
NOISE = "Bank opens regional office in DIFC"
OLD = "Marina festival brought crowds in September"
UNDATED = "Roadworks planned on Al Khail Road"


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(signals, "LEDGER_PATH", tmp_path / "ledger.json")
    monkeypatch.setattr(signals, "MANUAL_EVENTS_PATH", tmp_path / "none.yaml")
    return tmp_path


def fake_fetch(p):
    titles = RIDE + [NOISE, OLD, UNDATED] if p.id == "H1" else RIDE[:2]
    return [NewsItem(t, "Test", f"https://example.com/{i}", "2026-10-30", "Google News") for i, t in enumerate(titles)]


def fake_extract(items):
    out = []
    for i, a in enumerate(items):
        t = a["title"]
        if t in RIDE:
            out.append(Extraction(id=i, relevant=True, event_type="full_closure", event_date=date(2026, 11, 1),
                                  start_hour=4, end_hour=10, corridor="Sheikh Zayed Road", confidence=0.9))
        elif t == NOISE:
            out.append(Extraction(id=i, relevant=False, event_type="opening", confidence=0.9, reason="bank office"))
        elif t == OLD:
            out.append(Extraction(id=i, relevant=True, event_type="major_event", event_date=date(2026, 9, 20),
                                  areas=["Dubai Marina"], confidence=0.9))
        else:
            out.append(Extraction(id=i, relevant=True, event_type="roadworks", corridor="Al Khail Road",
                                  confidence=0.7))
    return out


def refresh(params):
    return signals.refresh(load_placements(), params, fetch=fake_fetch, extract=fake_extract,
                           enrich=lambda title, published: None)


def test_many_articles_make_one_event_and_noise_is_kept_but_rejected(isolated, params):
    ledger = refresh(params)
    assert len(ledger.events) == 1
    ev = next(iter(ledger.events.values()))
    assert ev["type"] == "full_closure" and len(ev["articles"]) == 5 and ev["enabled"]
    by_title = {a["title"]: a for a in ledger.articles.values()}
    assert by_title[NOISE]["status"] == "rejected"
    assert "outside the campaign window" in by_title[OLD]["reason"]
    assert by_title[UNDATED]["status"] == "pending"
    assert (isolated / "ledger.json").exists()


def test_extraction_is_frozen_on_refresh(isolated, params):
    refresh(params)
    calls = []
    signals.refresh(load_placements(), params, fetch=fake_fetch,
                    extract=lambda items: calls.append(len(items)) or [], enrich=lambda *a: None)
    assert calls == []  # nothing new to extract


def _forecast(placement, params, events, overrides=None):
    shares = np.asarray(params.cfg.hourly_profile.shares)
    road = {k: 1000.0 * shares * 24 for k in ("low", "base", "high")}
    other = {k: 0.0 for k in ("low", "base", "high")}
    u = Metric(30000, 20000, 50000, "ESTIMATE", "test")
    return campaign_forecast(placement, load_placements().campaign, road, other, u, params, events, overrides)


def test_empty_ledger_leaves_baseline_unchanged(placement, params):
    f = _forecast(placement, params, [])
    assert f.adjusted.value == pytest.approx(f.baseline.value)
    assert f.applied == []


def test_closure_applies_only_on_its_corridor_and_day(isolated, params):
    ledger = refresh(params)
    events = list(ledger.events.values())
    pc = load_placements()
    szr = next(p for p in pc.placements if p.id == "H1")
    khail = next(p for p in pc.placements if p.id == "H4")
    f_szr, f_khail = _forecast(szr, params, events), _forecast(khail, params, events)
    assert f_khail.adjusted.value == pytest.approx(f_khail.baseline.value)
    assert f_szr.adjusted.value < f_szr.baseline.value
    changed = [d for d, a, b in zip(f_szr.days, f_szr.adjusted_daily, f_szr.baseline_daily) if a != b]
    assert changed == [date(2026, 11, 1)]
    shares = np.asarray(params.cfg.hourly_profile.shares)
    lost = shares[4:10].sum()  # factor 0 between 04:00 and 10:00
    assert f_szr.adjusted_daily[0] == pytest.approx(f_szr.baseline_daily[0] * (1 - lost))


def test_magnitude_comes_from_config_and_toggle_switches_off(isolated, params):
    events = list(refresh(params).events.values())
    szr = next(p for p in load_placements().placements if p.id == "H1")
    full = _forecast(szr, params, events)
    half = _forecast(szr, params.with_override("event_full_closure_factor", 0.5), events)
    assert full.adjusted.value < half.adjusted.value < full.baseline.value
    off = _forecast(szr, params, events, overrides={events[0]["id"]: False})
    assert off.adjusted.value == pytest.approx(off.baseline.value)


def test_no_extractor_means_pending_and_no_events(isolated, params):
    ledger = signals.refresh(load_placements(), params, fetch=fake_fetch, extract=lambda items: None,
                             enrich=lambda *a: None)
    assert ledger.events == {}
    assert {a["status"] for a in ledger.articles.values()} == {"pending"}


def test_named_section_limits_the_faces_hit(isolated, params):
    events = list(refresh(params).events.values())
    events[0]["placements"] = ["H1"]  # source says only the DIFC stretch closed
    pc = load_placements()
    h1, h2 = (next(p for p in pc.placements if p.id == i) for i in ("H1", "H2"))
    assert _forecast(h1, params, events).adjusted.value < _forecast(h1, params, events).baseline.value
    f2 = _forecast(h2, params, events)
    assert f2.adjusted.value == pytest.approx(f2.baseline.value)
