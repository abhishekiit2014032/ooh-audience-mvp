"""Smoke test: every dashboard page renders without an exception, with no API keys."""

import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
MAIN = ["Locations", "Data sources", "Audience profile", "Compare locations", "Campaign performance"]
PLAN = ["The brief", "Overview", "Explore a location", "Score & compare", "Decision", "Duplication and plan",
        "Campaign health", "Map", "Placement detail", "Check the data", "Stress-test the pick", "Hand off",
        "Assumptions and sources"]
MORE = PLAN
PAGES = MAIN + PLAN
MONEY = re.compile(r"\bAED\b|\bUSD\b|budget|per 1,000 AED|cost per", re.I)


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    monkeypatch.setenv("OOH_NO_DOTENV", "1")
    from ooh import news
    from tests.test_news import FAKE

    monkeypatch.setattr(news, "fetch_news", lambda p, use_gdelt=True: ([news.NewsItem(**i.to_dict()) for i in FAKE], []))
    for k in ["TOMTOM_API_KEY", "DUBAI_PULSE_KEY", "DUBAI_PULSE_SECRET", "MAPILLARY_TOKEN", "ANTHROPIC_API_KEY"]:
        monkeypatch.delenv(k, raising=False)


def open_page(at, page):
    """Pick the part of the app (Insights or Plan a campaign), then the page in it."""
    part = "Insights" if page in MAIN else "Plan a campaign"
    if at.button_group(key="section").value != part:
        at.button_group(key="section").set_value(part).run()
    at.sidebar.radio(key="page").set_value(page).run()


def test_two_parts_each_list_only_their_pages():
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    assert at.button_group(key="section").value == "Insights"
    assert [o.split("\u2002")[-1] for o in at.sidebar.radio(key="page").options] == MAIN
    at.button_group(key="section").set_value("Plan a campaign").run()
    assert not at.exception, at.exception
    assert [o.split("\u2002")[-1] for o in at.sidebar.radio(key="page").options] == PLAN
    assert at.sidebar.radio(key="page").value == "The brief"


def test_all_pages_render():
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    assert not at.exception, at.exception
    for page in PAGES:
        open_page(at, page)
        assert not at.exception, (page, at.exception)


def test_slider_change_recomputes():
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    open_page(at, "Check the data")
    at.sidebar.slider(key="param_monthly_frequency").set_value(4.0).run()
    assert not at.exception


def test_every_campaign_renders_the_decision_pages():
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    for cid in ["suv_launch", "property_launch", "retail_festival"]:
        at.selectbox(key="campaign_id").set_value(cid).run()
        for page in MAIN + MORE[:6] + ["Check the data", "Stress-test the pick", "Hand off"]:
            open_page(at, page)
            assert not at.exception, (cid, page, at.exception)


def test_brief_buttons_open_the_proving_page_on_the_brief_campaign():
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    at.selectbox(key="campaign_id").set_value("retail_festival").run()
    open_page(at, "The brief")
    assert not at.exception, at.exception
    at.button(key="brief_q3").click().run()
    assert not at.exception, at.exception
    assert at.sidebar.radio(key="page").value == "Score & compare"
    assert at.button_group(key="section").value == "Plan a campaign"
    assert at.selectbox(key="campaign_id").value == "suv_launch"


def _texts(at) -> list[str]:
    out = []
    for kind in ("markdown", "caption", "header", "subheader", "info", "warning", "success", "metric"):
        for el in getattr(at, kind):
            out.append(str(getattr(el, "value", "")) + " " + str(getattr(el, "label", "")))
    return out


def test_no_money_on_any_page():
    """No prices, budgets or currency anywhere: price is a 1-4 rating and plans pick a number of boards."""
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    for page in PAGES:
        open_page(at, page)
        hits = [t[:120] for t in _texts(at) if MONEY.search(t)]
        assert not hits, (page, hits)


def test_compare_screen_shows_two_locations_side_by_side():
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    open_page(at, "Compare locations")
    assert not at.exception, at.exception
    table = next(m.value for m in at.markdown if "<table class='cmp-t cmp2'>" in m.value)
    for words in ("Traffic", "Visibility", "Reach", "Audience", "Nearby", "People who pass both"):
        assert words in table, words
    at.selectbox(key="cmp_b").set_value("H4").run()
    assert not at.exception, at.exception


def test_info_button_opens_the_source_of_that_number():
    """Locations shows numbers only; ⓘ on a number opens Data sources on that number's source."""
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    assert at.sidebar.radio(key="page").value == "Locations"
    assert not any("Estimate" in m.value for m in at.markdown if "nt-v" in m.value)
    at.button(key="info_vehicles_H1").click().run()
    assert not at.exception, at.exception
    assert at.sidebar.radio(key="page").value == "Data sources"
    assert at.button_group(key="section").value == "Insights"
    card = next(m.value for m in at.markdown if "You asked about" in m.value)
    assert "Vehicles passing within view" in card and "RTA lane capacity" in card
