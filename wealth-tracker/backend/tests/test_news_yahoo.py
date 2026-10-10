"""The Yahoo fallback for the News tab: without a Finnhub key the feeds must not
come back empty, and both shapes yfinance has returned are read."""

from app.core import config
from app.services import news_service


NEW_SHAPE = {
    "id": "abc",
    "content": {
        "title": "ASML beats expectations",
        "summary": "Orders were higher than expected.",
        "pubDate": "2026-10-05T14:30:00Z",
        "provider": {"displayName": "Reuters"},
        "canonicalUrl": {"url": "https://example.com/asml"},
    },
}
OLD_SHAPE = {
    "uuid": "def",
    "title": "Stocks rise as inflation cools",
    "publisher": "Bloomberg",
    "link": "https://example.com/stocks",
    "providerPublishTime": 1791200000,
}


def test_normalise_new_shape():
    it = news_service._yahoo_normalise(NEW_SHAPE, "ASML", "ASML Holding")
    assert it["title"] == "ASML beats expectations"
    assert it["publisher"] == "Reuters"
    assert it["link"] == "https://example.com/asml"
    assert it["published"].startswith("2026-10-05T14:30:00")
    assert it["ticker"] == "ASML" and it["holding"] == "ASML Holding"
    assert it["source_api"] == "yahoo"
    assert it["label"] == "Earnings"


def test_normalise_old_shape():
    it = news_service._yahoo_normalise(OLD_SHAPE, None, None)
    assert it["title"] == "Stocks rise as inflation cools"
    assert it["publisher"] == "Bloomberg"
    assert it["link"] == "https://example.com/stocks"
    assert it["published"] is not None


def test_normalise_skips_items_without_title():
    assert news_service._yahoo_normalise({"content": {"summary": "x"}}, None, None) is None


class _FakeTicker:
    def __init__(self, symbol):
        self.symbol = symbol

    def get_news(self, count=10):
        if self.symbol == "BROKEN":
            raise RuntimeError("Yahoo down")
        return [NEW_SHAPE]


def test_yahoo_only_without_finnhub_key(monkeypatch):
    import yfinance

    monkeypatch.setattr(yfinance, "Ticker", _FakeTicker)
    monkeypatch.setattr(config, "FINNHUB_API_KEY", "")
    assert len(news_service._yahoo_news("ASML.AS", tag="ASML")) == 1
    assert news_service._yahoo_news("BROKEN") == []

    monkeypatch.setattr(config, "FINNHUB_API_KEY", "set")
    assert news_service._yahoo_news("ASML.AS") == []


def test_market_feed_filled_by_yahoo(monkeypatch, tmp_path):
    import sqlite3
    import yfinance
    from domain import database

    monkeypatch.setattr(yfinance, "Ticker", _FakeTicker)
    monkeypatch.setattr(config, "FINNHUB_API_KEY", "")
    monkeypatch.setattr(config, "ALPHAVANTAGE_API_KEY", "")
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.row_factory = sqlite3.Row
    database.init_db(conn)
    items = news_service.get_market_news(conn)
    # The same story from both index pages is shown once.
    assert [i["title"] for i in items] == ["ASML beats expectations"]
