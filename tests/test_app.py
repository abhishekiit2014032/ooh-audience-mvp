"""Smoke test: every dashboard page renders without an exception, with no API keys."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")
PAGES = ["Map", "Data sources", "Placement detail", "Compare locations", "Duplication and plan", "Planned vs actual",
         "Sensitivity", "Activation", "Area signals", "Assumptions and sources"]


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    monkeypatch.setenv("OOH_NO_DOTENV", "1")
    from ooh import news
    from tests.test_news import FAKE

    monkeypatch.setattr(news, "fetch_news", lambda p, use_gdelt=True: ([news.NewsItem(**i.to_dict()) for i in FAKE], []))
    for k in ["TOMTOM_API_KEY", "DUBAI_PULSE_KEY", "DUBAI_PULSE_SECRET", "MAPILLARY_TOKEN", "ANTHROPIC_API_KEY"]:
        monkeypatch.delenv(k, raising=False)


def test_all_pages_render():
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    assert not at.exception, at.exception
    for page in PAGES:
        at.sidebar.radio(key="page").set_value(page).run()
        assert not at.exception, (page, at.exception)


def test_slider_change_recomputes():
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    at.sidebar.radio(key="page").set_value("Compare locations").run()
    at.sidebar.slider(key="param_monthly_frequency").set_value(4.0).run()
    assert not at.exception
