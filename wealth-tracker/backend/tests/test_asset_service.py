"""
One asset's koersgrafiek: the caching wrapper and the day's anchoring.

The download itself is stubbed — what is worth pinning is everything around it,
because each of these silently draws a *plausible* wrong line rather than
raising: a cached failure would leave a position chartless for an hour, an
unanchored last point would end the line a few cents off the price printed above
it, and a shared cache key would show one ticker's history under another's name.

Each test was watched fail first (rule 3): the anchoring ones by dropping the
override, the cache ones by removing the key's ticker or by returning {} instead
of raising.
"""

import sqlite3

import pytest

from app.services import asset_service
from domain import database


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    database.init_db(c)
    yield c
    c.close()


def _bars(*closes, prev=None):
    """A stubbed intraday payload: `prev` is the previous session's close, which
    _fetch_intraday prepends as the line's first point."""
    points = [{"d": f"2026-08-04T1{i}:00+00:00", "c": c} for i, c in enumerate(closes)]
    if prev is not None:
        points.insert(0, {"d": "2026-08-03T17:25+00:00", "c": prev})
    return {"points": points, "prev_close": prev}


# ---------------------------------------------------------------------------
# Daily closes
# ---------------------------------------------------------------------------


def test_no_ticker_means_an_empty_chart_not_a_download(conn, monkeypatch):
    monkeypatch.setattr(
        asset_service,
        "_fetch_daily",
        lambda t: pytest.fail("a position without a ticker must not be downloaded"),
    )
    assert asset_service.daily_closes(conn, None) == {"points": []}


def test_daily_closes_are_cached_per_ticker(conn, monkeypatch):
    calls = []

    def fake(ticker):
        calls.append(ticker)
        return {"points": [{"d": "2026-08-03", "c": 10.0}]}

    monkeypatch.setattr(asset_service, "_fetch_daily", fake)

    assert asset_service.daily_closes(conn, "AAPL")["points"][0]["c"] == 10.0
    asset_service.daily_closes(conn, "AAPL")
    assert calls == ["AAPL"]  # second read came from the cache

    asset_service.daily_closes(conn, "IWDA.AS")  # a different ticker is a different key
    assert calls == ["AAPL", "IWDA.AS"]


def test_a_failed_download_is_not_cached(conn, monkeypatch):
    """A Yahoo outage must cost this request, not the whole TTL: the fetch
    raises, the wrapper degrades to an empty chart, and the next call retries."""
    attempts = []

    def flaky(ticker):
        attempts.append(ticker)
        if len(attempts) == 1:
            raise RuntimeError("yahoo is down")
        return {"points": [{"d": "2026-08-03", "c": 10.0}]}

    monkeypatch.setattr(asset_service, "_fetch_daily", flaky)

    assert asset_service.daily_closes(conn, "AAPL") == {"points": []}
    assert asset_service.daily_closes(conn, "AAPL")["points"] != []
    assert len(attempts) == 2


# ---------------------------------------------------------------------------
# Intraday, and the two anchors
# ---------------------------------------------------------------------------


def test_the_last_bar_becomes_the_live_price(conn, monkeypatch):
    """The five-minute feed runs about a quarter of an hour behind the quote,
    so the bars give the day its shape and the price cache its endpoint."""
    monkeypatch.setattr(asset_service, "_fetch_intraday", lambda t: _bars(101.0, 102.0, prev=100.0))

    data = asset_service.intraday_closes(conn, "X1.AS", live_price=102.4, previous_close=100.0)

    assert data["points"][-1]["c"] == 102.4
    assert data["points"][1]["c"] == 101.0  # the shape in between is untouched


def test_the_first_bar_is_the_previous_close_and_moves_with_it(conn, monkeypatch):
    """The line starts at the previous close — that is what a day is measured
    against — so a differing cached previous_close must move the point, not just
    the number beside it."""
    monkeypatch.setattr(asset_service, "_fetch_intraday", lambda t: _bars(101.0, prev=100.0))

    data = asset_service.intraday_closes(conn, "X1.AS", live_price=101.5, previous_close=99.5)

    assert data["prev_close"] == 99.5
    assert data["points"][0]["c"] == 99.5


def test_without_a_previous_close_the_bars_keep_their_own(conn, monkeypatch):
    monkeypatch.setattr(asset_service, "_fetch_intraday", lambda t: _bars(101.0, 102.0))

    data = asset_service.intraday_closes(conn, "X1.AS", live_price=102.5)

    assert data["prev_close"] is None
    assert data["points"][-1]["c"] == 102.5
    assert data["points"][0]["c"] == 101.0  # nothing to anchor the start to


def test_no_bars_at_all_is_an_ordinary_answer(conn, monkeypatch):
    """A market holiday, or a product Yahoo has no minute bars for. The page
    falls back to the daily series; anchoring a single made-up point would draw
    a flat day that never happened."""
    monkeypatch.setattr(asset_service, "_fetch_intraday", lambda t: {"points": [], "prev_close": None})

    assert asset_service.intraday_closes(conn, "X1.AS", live_price=102.5) == {"points": [], "prev_close": None}
