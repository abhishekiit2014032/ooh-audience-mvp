from ooh import news
from ooh.news import NewsItem, area_news, keyword_signal

FAKE = [
    NewsItem("Dubai Ride takes over Sheikh Zayed Road on Sunday", "Gulf News", "https://example.com/1", "2026-10-30",
             "Google News"),
    NewsItem("New Lexus showroom opens on Sheikh Zayed Road", "Khaleej Times", "https://example.com/2", "2026-10-29",
             "Google News"),
    NewsItem("Dubai Fitness Challenge 2026: free community runs", "The National", "https://example.com/3",
             "2026-10-28", "GDELT"),
    NewsItem("Bank opens regional office in DIFC", "Reuters", "https://example.com/4", "2026-10-27", "GDELT"),
]


def test_keyword_signals():
    assert keyword_signal(FAKE[0].title)[0] == "traffic_risk"
    assert keyword_signal(FAKE[1].title)[0] == "category"
    assert keyword_signal(FAKE[2].title)[0] == "audience_boost"
    assert keyword_signal(FAKE[3].title)[0] == "other"


def test_area_news_without_key_uses_rules(monkeypatch, placement):
    monkeypatch.setattr(news, "fetch_news", lambda p, use_gdelt=True: ([NewsItem(**i.to_dict()) for i in FAKE], []))
    n = area_news(placement, "Example SUV launch")
    assert n.counts() == {"traffic_risk": 1, "audience_boost": 1, "category": 1, "other": 1}
    assert all(i.classified_by == "keyword rules" for i in n.items)
    assert "traffic risk" in n.summary and "Dubai Ride" in n.summary
    assert n.summary_source.startswith("Template")
