"""
GET /api/etf-analysis/history — the sector and region allocation over time.

No network: the look-through per position (etf_holdings.position_mix), the bond
check and the closes download are stubbed, so these tests pin down the wiring —
holdings per date, values at that date's close, today's mix applied to every
date, one "Other", and an outage that is answered but not cached.
"""

import datetime

import pandas as pd
import pytest

from domain import database
from domain.portfolio import etf_holdings
from domain.portfolio import series as charts


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _tx(date, isin, name, kind, qty, total, ref):
    return {
        "date": date,
        "time": "10:00",
        "isin": isin,
        "name": name,
        "transaction_type": kind,
        "quantity": qty,
        "price": abs(total) / qty,
        "total_eur": total,
        "order_ref": ref,
        "currency": "EUR",
        "exchange": "EAM",
        "transaction_fee": 0.0,
        "autofx_cost": 0.0,
    }


def _seed(username):
    """A world fund since January, a tech share bought in March. Today: day 2 of a later month."""
    conn = database.connect(username)
    database.init_db(conn)
    database.save_transactions(
        conn,
        [
            _tx("2025-01-10", "IE00WORLD0001", "World Fund", "BUY", 10.0, -1000.0, "o1"),
            _tx("2025-03-05", "US00SHARE0001", "Tech Share", "BUY", 5.0, -500.0, "o2"),
        ],
    )
    database.save_price(conn, isin="IE00WORLD0001", name="World Fund", ticker="WRLD.AS", price=120.0, currency="EUR", previous_close=119.0)
    database.save_price(conn, isin="US00SHARE0001", name="Tech Share", ticker="TECH.AS", price=200.0, currency="EUR", previous_close=199.0)
    conn.close()


MIXES = {
    "IE00WORLD0001": {
        # The issuer's own unclassified bucket, under the name the fold uses.
        "sector": {"Information Technology": 0.5, "Financials": 0.3, "Other": 0.2},
        "country": {"United States": 0.7, "Japan": 0.3},
    },
    "US00SHARE0001": {"sector": {"Information Technology": 1.0}, "country": {"United States": 1.0}},
}


@pytest.fixture
def stubs(monkeypatch):
    def mix(conn, isin, name, ticker):
        m = MIXES[isin]
        return {**m, "dominant_region": "United States", "region_data": "exact", "sector_data": "exact"}

    monkeypatch.setattr(etf_holdings, "position_mix", mix)
    monkeypatch.setattr(etf_holdings, "bond_isins", lambda conn, positions: set())

    days = pd.date_range("2025-01-01", datetime.date.today())
    closes = pd.DataFrame(
        {("Close", "WRLD.AS"): [100.0] * len(days), ("Close", "TECH.AS"): [100.0] * len(days)},
        index=days,
    )
    calls = {"n": 0}

    def download(tickers, **kw):
        calls["n"] += 1
        return closes

    monkeypatch.setattr(charts.yf, "download", download)
    return calls


def test_one_point_per_month_end_and_today(client, stubs):
    _login(client)
    _seed("alice")

    body = client.get("/api/etf-analysis/history").json()

    assert body["dates"][0] == "2025-01-31"
    assert body["dates"][-1] == datetime.date.today().isoformat()
    assert body["breakdown_as_of"] == "current"
    for kind in ("sector", "region"):
        series = body[kind]
        assert len(series["pct"]) == len(series["value"]) == len(body["dates"])
        assert all(len(row) == len(series["keys"]) for row in series["value"])


def test_values_are_per_date_and_today_matches_the_card(client, stubs):
    _login(client)
    _seed("alice")

    body = client.get("/api/etf-analysis/history").json()
    sector = body["sector"]
    tech = sector["keys"].index("Information Technology")

    # January: only the fund, 10 x 100 at January's close, half of it tech.
    assert body["total"][0] == 1000.0
    assert sector["value"][0][tech] == 500.0
    assert sector["pct"][0][tech] == 50.0

    # March: the share joins, 5 x 100.
    march = body["dates"].index("2025-03-31")
    assert body["total"][march] == 1500.0
    assert sector["value"][march][tech] == 500.0 + 500.0

    # Today at today's cached prices, the same ones the current card uses.
    assert body["total"][-1] == 10 * 120.0 + 5 * 200.0


def test_exactly_one_other(client, stubs):
    _login(client)
    _seed("alice")

    sector = client.get("/api/etf-analysis/history").json()["sector"]
    assert sector["keys"].count("Other") == 1
    assert sector["keys"][-1] == "Other"


def test_regions_are_continents(client, stubs):
    _login(client)
    _seed("alice")

    region = client.get("/api/etf-analysis/history").json()["region"]
    assert set(region["keys"]) == {"North America", "Asia"}


def test_an_outage_is_answered_and_not_cached(client, stubs, monkeypatch):
    _login(client)
    _seed("alice")

    working = charts.yf.download
    monkeypatch.setattr(charts.yf, "download", lambda tickers, **kw: pd.DataFrame())
    assert client.get("/api/etf-analysis/history").json()["unavailable"] is True

    monkeypatch.setattr(charts.yf, "download", working)
    body = client.get("/api/etf-analysis/history").json()
    assert body.get("unavailable") is None
    assert body["dates"]


def test_no_transactions_is_an_empty_series(client, stubs):
    _login(client)
    conn = database.connect("alice")
    database.init_db(conn)
    conn.close()

    body = client.get("/api/etf-analysis/history").json()
    assert body["dates"] == []
    assert body["sector"]["keys"] == []
