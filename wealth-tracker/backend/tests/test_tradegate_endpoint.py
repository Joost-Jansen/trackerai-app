"""/api/holdings/{isin}/tradegate, and the price-source line on the detail.

The adapter itself is pinned by test_tradegate_service.py; what only the
endpoint can get wrong is *which* position gets a Tradegate quote (ISIN plus
beurs — only a position held on TDG) and that everything else costs no request.
"""

import datetime
import io

import pandas as pd
import pytest

from app.services import asset_service, holdings_service, tradegate_service, venue_price_service
from domain import database
from domain.portfolio import positions as portfolio


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _tx(
    isin="IE00B4L5YC18",
    name="iShares MSCI EM UCITS ETF USD (Acc)",
    qty=10,
    price=55.0,
    order="order-1",
    date="05-01-2026",
    fee=-1.0,
    exchange="TDG",
):
    value = -(qty * price)
    return {
        "Datum": date,
        "Tijd": "09:30",
        "Product": name,
        "ISIN": isin,
        "Beurs": exchange,
        "Uitvoeringsplaats": exchange,
        "Aantal": qty,
        "Koers": price,
        "Lokale waarde": value,
        "Waarde": value,
        "Wisselkoers": 1.0,
        "Transactiekosten": fee,
        "Totaal": value + fee,
        "Order Id": order,
    }


def _upload_tx(client, rows):
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    resp = client.post(
        "/api/uploads/transactions",
        files={"files": ("tx.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text


@pytest.fixture()
def quotes(monkeypatch):
    """No Yahoo on upload, and a recording stand-in for the Tradegate adapter."""
    monkeypatch.setattr(
        portfolio, "refresh_all_prices", lambda conn, deadline_seconds=None: portfolio.RefreshResult(refreshed=0, failed=[])
    )
    calls = []

    def fake_get_quote(isin):
        calls.append(isin)
        return {
            "status": "ok",
            "isin": isin,
            "venue": "TDG",
            "currency": "EUR",
            "last": 55.52,
            "bid": 55.05,
            "ask": 55.53,
            "previous_close": 56.304,
            "quote_time": None,
            "stale": False,
            "fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }

    monkeypatch.setattr(tradegate_service, "get_quote", fake_get_quote)
    return calls


def test_requires_auth(client):
    assert client.get("/api/holdings/IE00B4L5YC18/tradegate").status_code == 401


def test_a_tradegate_position_gets_the_tradegate_quote(client, quotes):
    _login(client)
    _upload_tx(client, [_tx()])

    body = client.get("/api/holdings/IE00B4L5YC18/tradegate?exchange=TDG").json()
    assert body["status"] == "ok"
    assert (body["last"], body["bid"], body["ask"]) == (55.52, 55.05, 55.53)
    assert quotes == ["IE00B4L5YC18"]

    detail = client.get("/api/holdings/IE00B4L5YC18?exchange=TDG").json()
    assert detail["tradegate_quote"] is True


def test_a_position_on_another_exchange_costs_no_request(client, quotes):
    _login(client)
    _upload_tx(client, [_tx(exchange="EAM")])

    body = client.get("/api/holdings/IE00B4L5YC18/tradegate?exchange=EAM").json()
    assert body["status"] == "not_applicable"
    assert "EAM" in body["message"]
    assert quotes == []
    assert client.get("/api/holdings/IE00B4L5YC18?exchange=EAM").json()["tradegate_quote"] is False


def test_same_isin_on_two_exchanges_only_the_tdg_position_is_asked(client, quotes):
    _login(client)
    _upload_tx(
        client,
        [
            _tx(qty=10, order="a", exchange="EAM"),
            _tx(qty=5, order="b", exchange="TDG"),
        ],
    )

    assert client.get("/api/holdings/IE00B4L5YC18/tradegate?exchange=EAM").json()["status"] == "not_applicable"
    assert quotes == []
    assert client.get("/api/holdings/IE00B4L5YC18/tradegate?exchange=TDG").json()["status"] == "ok"
    assert quotes == ["IE00B4L5YC18"]


def test_no_position_is_a_404_and_no_request(client, quotes):
    _login(client)
    assert client.get("/api/holdings/IE00B4L5YC18/tradegate").status_code == 404
    _upload_tx(client, [_tx(exchange="EAM")])
    assert client.get("/api/holdings/IE00B4L5YC18/tradegate?exchange=TDG").status_code == 404
    assert quotes == []


def test_the_real_adapter_answers_an_outage_with_a_status_not_a_500(client, monkeypatch):
    """End to end through the real service, with the network failing."""
    import requests

    monkeypatch.setattr(
        portfolio, "refresh_all_prices", lambda conn, deadline_seconds=None: portfolio.RefreshResult(refreshed=0, failed=[])
    )
    tradegate_service.clear_cache()
    monkeypatch.setattr(tradegate_service, "_sleep", lambda s: None)

    def down(url, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(tradegate_service, "_http_get", down)
    try:
        _login(client)
        _upload_tx(client, [_tx()])
        resp = client.get("/api/holdings/IE00B4L5YC18/tradegate?exchange=TDG")
        assert resp.status_code == 200
        assert resp.json()["status"] == "unavailable"
        # And the position page itself is untouched by it.
        assert client.get("/api/holdings/IE00B4L5YC18?exchange=TDG").status_code == 200
    finally:
        tradegate_service.clear_cache()


# ---------------------------------------------------------------------------
# The Tradegate price as the position's price
# ---------------------------------------------------------------------------


def _save_yahoo(price=55.15, prev=56.0):
    with database.user_db("alice") as conn:
        database.save_price(
            conn, isin="IE00B4L5YC18", name="iShares MSCI EM", ticker="EUNM.DE", price=price, currency="EUR", previous_close=prev
        )


def test_after_a_tradegate_quote_the_position_is_valued_at_its_last_trade(client, quotes):
    _login(client)
    _upload_tx(client, [_tx(qty=10, order="a", exchange="EAM"), _tx(qty=5, order="b", exchange="TDG")])
    _save_yahoo()

    before = client.get("/api/holdings/IE00B4L5YC18?exchange=TDG").json()
    assert before["position"]["current_price"] == 55.15  # nothing from Tradegate yet
    assert before["price_source"]["venue_fallback"] is True

    client.get("/api/holdings/IE00B4L5YC18/tradegate?exchange=TDG")

    tdg = client.get("/api/holdings/IE00B4L5YC18?exchange=TDG").json()
    eam = client.get("/api/holdings/IE00B4L5YC18?exchange=EAM").json()
    assert tdg["position"]["current_price"] == 55.52
    assert tdg["position"]["current_value"] == round(5 * 55.52, 2)
    assert tdg["price_source"]["provider"] == "Tradegate"
    assert eam["position"]["current_price"] == 55.15  # its own exchange's price
    assert eam["price_source"]["provider"] == "Yahoo Finance"

    # The overview's totals are the sum of its rows...
    overview = client.get("/api/holdings/overview").json()
    assert overview["totals"]["value"] == pytest.approx(sum(r["current_value"] for r in overview["positions"]), abs=0.011)
    # ...and the dashboard, which computes per ISIN, lands on the same value.
    summary = client.get("/api/dashboard/summary").json()
    assert summary["summary"]["total_value"] == pytest.approx(overview["totals"]["value"], abs=0.011)

    details = client.get("/api/positions").json()["positions"][0]
    assert details["price_blended"] is True


def test_the_1d_line_ends_on_the_positions_own_price(client, quotes, monkeypatch):
    monkeypatch.setattr(
        asset_service,
        "_fetch_intraday",
        lambda t: {
            "points": [{"d": "2026-09-14T07:30+00:00", "c": 56.0}, {"d": "2026-09-14T15:00+00:00", "c": 55.2}],
            "prev_close": 56.0,
        },
    )
    _login(client)
    _upload_tx(client, [_tx(qty=10, order="a", exchange="EAM"), _tx(qty=5, order="b", exchange="TDG")])
    _save_yahoo()
    client.get("/api/holdings/IE00B4L5YC18/tradegate?exchange=TDG")

    tdg = client.get("/api/holdings/IE00B4L5YC18/intraday?exchange=TDG").json()
    assert tdg["points"][-1]["c"] == 55.52
    assert tdg["prev_close"] == 56.304

    eam = client.get("/api/holdings/IE00B4L5YC18/intraday?exchange=EAM").json()
    assert eam["points"][-1]["c"] == 55.15


def test_the_refresh_button_also_refreshes_tradegate(client, quotes, monkeypatch):
    monkeypatch.setattr(venue_price_service, "refresh", lambda conn: {"refreshed": 1, "failed": 0})
    _login(client)
    body = client.post("/api/prices/refresh").json()
    assert body["venue_refreshed"] == 1 and body["venue_failed"] == 0


# ---------------------------------------------------------------------------
# Where the price at the top comes from
# ---------------------------------------------------------------------------


def test_a_tradegate_position_priced_off_xetra_is_labelled_a_fallback(client, quotes):
    _login(client)
    _upload_tx(client, [_tx()])
    with database.user_db("alice") as conn:
        database.save_price(conn, isin="IE00B4L5YC18", name="iShares MSCI EM", ticker="EUNM.DE", price=55.4, currency="EUR")

    source = client.get("/api/holdings/IE00B4L5YC18?exchange=TDG").json()["price_source"]
    assert source == {
        "provider": "Yahoo Finance",
        "ticker": "EUNM.DE",
        "listing_venue": "XETRA",
        "position_venue": "TDG",
        "venue_fallback": True,
    }


@pytest.mark.parametrize(
    "ticker, exchange, venue, fallback",
    [
        ("IWDA.AS", "EAM", "Euronext Amsterdam", False),
        ("EUNM.DE", "XET", "XETRA", False),
        ("EUNM.DE", "TDG", "XETRA", True),  # Yahoo has no Tradegate feed
        ("EUNM.DE", "EAM", "XETRA", True),  # a cached listing on the wrong venue
        ("AAPL", "NDQ", "VS", False),
        ("IE00BYTRRD19.SG", "EAM", "Börse Stuttgart", True),
        ("FOO.AS", "ZZZ", "Euronext Amsterdam", False),  # unknown venue: nothing to compare
        ("FOO.AS", None, "Euronext Amsterdam", False),
    ],
)
def test_price_source(ticker, exchange, venue, fallback):
    source = holdings_service.price_source(ticker, exchange)
    assert source["listing_venue"] == venue
    assert source["venue_fallback"] is fallback


def test_no_ticker_no_source():
    assert holdings_service.price_source(None, "TDG") is None
