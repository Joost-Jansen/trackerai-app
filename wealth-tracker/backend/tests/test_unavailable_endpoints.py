"""What the three screens say when the closes could not be fetched.

The rule, one level up from charts.DataUnavailable: a failed download is never
stored. database.get_or_fetch only caches what fetch_fn returns, so the raise
has to travel through it and be caught outside — otherwise the outage is
written into the cache and outlives itself by an hour, and the retry the user
is invited to make cannot work.

Watched fail first (rule 3): with the raise swallowed inside charts, every one
of these returns a full, plausible, drawable payload.
"""

import datetime

import pytest

from app.services import dashboard_service as ds
from domain import database
from domain.portfolio import series as charts


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _seed(username, isins=("NL0000001",)):
    conn = database.connect(username)
    database.init_db(conn)
    database.save_transactions(
        conn,
        [
            {
                "date": "2025-01-02",
                "time": "10:00",
                "isin": isin,
                "name": f"Fund {i}",
                "transaction_type": "BUY",
                "quantity": 10.0,
                "price": 100.0,
                "total_eur": 1000.0,
                "order_ref": f"o{i}",
                "currency": "EUR",
                "exchange": "EAM",
                "transaction_fee": 1.0,
                "autofx_cost": 0.0,
            }
            for i, isin in enumerate(isins)
        ],
    )
    for i, isin in enumerate(isins):
        database.save_price(conn, isin=isin, name=f"Fund {i}", ticker=f"T{i}.AS", price=110.0, currency="EUR", previous_close=100.0)
    conn.close()


@pytest.fixture
def outage(monkeypatch):
    """Every yfinance download comes back empty, as a real outage does."""
    import pandas as pd

    monkeypatch.setattr(charts.yf, "download", lambda tickers, **kw: pd.DataFrame())


# ---------------------------------------------------------------------------
# The dashboard's value card
# ---------------------------------------------------------------------------


def test_value_history_says_unavailable_instead_of_a_flat_line(client, outage):
    _login(client)
    _seed("alice")

    body = client.get("/api/dashboard/value-history").json()

    assert body["unavailable"] is True
    assert body["points"] == []


def test_a_failed_value_history_is_not_cached(client, monkeypatch):
    """The whole point of raising: the next request after the line is back
    must build a real chart, not be served an hour-old apology."""
    import pandas as pd

    _login(client)
    _seed("alice")

    calls = {"n": 0}
    days = pd.DatetimeIndex([datetime.date(2025, 1, 2) + datetime.timedelta(days=i) for i in range(5)])

    def flaky(tickers, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return pd.DataFrame()  # the outage
        return pd.DataFrame({("Close", "T0.AS"): [100.0] * 5}, index=days)

    monkeypatch.setattr(charts.yf, "download", flaky)

    assert client.get("/api/dashboard/value-history").json()["unavailable"] is True

    second = client.get("/api/dashboard/value-history").json()
    assert calls["n"] == 2, "the failure was cached — it must not be"
    assert second.get("unavailable") is None
    assert second["points"]


def test_the_sparkline_hides_rather_than_draws_a_straight_line(client, outage):
    _login(client)
    _seed("alice")
    assert client.get("/api/dashboard/sparkline").json() == {"points": []}


# ---------------------------------------------------------------------------
# The Returns tab
# ---------------------------------------------------------------------------


def test_returns_says_unavailable_instead_of_zero_percent(client, outage):
    from app.core import auth_store

    # The tab is behind a beta flag; the endpoint is gated as well as the nav.
    cfg = auth_store.load_config()
    cfg["beta"] = {"returns": ["alice"]}
    auth_store.save_config(cfg)

    _login(client)
    _seed("alice")

    body = client.get("/api/returns").json()
    # Pre-fix: points full of 0,00% next to a simple return computed from the
    # price cache — two numbers over the same period, disagreeing.
    assert body["unavailable"] is True
    assert body["points"] == []
    assert body["ranges"] == []


# ---------------------------------------------------------------------------
# The Benchmarks tab
# ---------------------------------------------------------------------------


def test_benchmarks_answers_with_its_error_and_caches_nothing(client, monkeypatch):
    import pandas as pd

    _login(client)
    _seed("alice")

    calls = {"n": 0}

    def flaky(tickers, **kw):
        calls["n"] += 1
        return pd.DataFrame()

    monkeypatch.setattr(charts.yf, "download", flaky)

    first = client.get("/api/benchmarks/series")
    assert first.status_code == 422
    assert "niet bij Yahoo Finance worden opgehaald" in first.json()["detail"]

    before = calls["n"]
    client.get("/api/benchmarks/series")
    # "Try again in a few minutes" has to mean something: the
    # second request must actually go out to Yahoo again.
    assert calls["n"] > before


# ---------------------------------------------------------------------------
# Partial data is still drawn, and still named
# ---------------------------------------------------------------------------


def test_a_substituted_holding_is_reported_beside_the_line():
    txns = [{"date": "2026-07-01", "isin": "X1", "name": "Een fonds", "quantity": 10.0, "transaction_type": "BUY", "total_eur": 1000.0}]
    # No ticker: nothing is downloaded, so every day is the cached price.
    out = ds._build_value_history(txns, {"X1": {"price": 110.0, "currency": "EUR"}}, [])

    assert out["points"]
    assert out["estimated"] == [{"isin": "X1", "name": "Een fonds", "base": "huidige koers"}]
