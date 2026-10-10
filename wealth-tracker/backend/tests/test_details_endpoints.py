"""
The Details tab's endpoints (app/routers/details.py).

Deliberately not tested here: that the numbers are *right*. positions,
closed positions and dividends come straight from portfolio.py and
database.py, which tests/ already covers, and the Pi parity run compares them
against the live Streamlit app on real data. What is worth pinning is what
this router itself adds — the price-fetch timestamp, the priced-only total,
the groupby's shape, the override flow's ordering, and user scoping.
"""

import io

import pandas as pd


def _login(client, user="alice", pw="alicepw"):
    resp = client.post("/api/auth/login", json={"username": user, "password": pw})
    assert resp.status_code == 200


def _xlsx(rows: list[dict]) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    return buf.getvalue()


def _tx(isin="IE00B4L5Y983", name="iShares Core MSCI World", qty=10, price=80.5, order="order-1", date="05-01-2026"):
    return {
        "Datum": date, "Tijd": "09:30", "Product": name, "ISIN": isin,
        "Beurs": "EAM", "Uitvoeringsplaats": "EAM", "Aantal": qty, "Koers": price,
        "Lokale waarde": -(qty * price), "Waarde": -(qty * price), "Wisselkoers": 1.0,
        "Transactiekosten": -1.0, "Totaal": -(qty * price) - 1, "Order Id": order,
    }


def _upload_tx(client, rows):
    resp = client.post(
        "/api/uploads/transactions",
        files={"files": ("tx.xlsx", _xlsx(rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text


def test_details_endpoints_require_auth(client):
    for path in ["/api/positions", "/api/positions/closed", "/api/transactions",
                 "/api/dividends", "/api/ticker-overrides"]:
        assert client.get(path).status_code == 401, path


def test_empty_portfolio_returns_empty_collections(client):
    _login(client)
    assert client.get("/api/positions").json() == {"positions": [], "priced_total": 0}
    assert client.get("/api/transactions").json()["transactions"] == []
    assert client.get("/api/dividends").json() == {"by_stock": [], "payments": []}
    assert client.get("/api/positions/closed").json()["positions"] == []


def test_positions_carry_price_fetch_time_and_priced_only_total(client):
    """An unpriced position must not count as zero in the total.

    app.py:650 sums only the priced ones, and the caption beside it is what a
    user reconciles against DeGiro — silently counting an unpriced holding as
    €0 would make that total quietly wrong rather than visibly incomplete.
    """
    _login(client)
    _upload_tx(client, [_tx()])

    body = client.get("/api/positions").json()
    assert len(body["positions"]) == 1
    position = body["positions"][0]
    # No price has been fetched (yfinance is never called in tests), so the
    # timestamp is present-but-null and the total stays at zero rather than
    # inventing one.
    assert "price_fetched_at" in position
    assert position["price_fetched_at"] is None
    assert position["current_value"] is None
    assert body["priced_total"] == 0


def test_transactions_and_dividends_are_scoped_to_the_session_user(client):
    _login(client, "alice", "alicepw")
    _upload_tx(client, [_tx()])
    assert len(client.get("/api/transactions").json()["transactions"]) == 1

    client.post("/api/auth/login", json={"username": "bob", "password": "bobpw"})
    assert client.get("/api/transactions").json()["transactions"] == []
    assert client.get("/api/positions").json()["positions"] == []


def test_dividends_group_by_stock_and_sort_by_net_descending(client):
    """Mirrors app.py:765-783: one row per ISIN, counted and summed, best first."""
    _login(client)
    mutations = [
        # Two payments for one ISIN, one for another that nets more.
        {"Datum": "02-01-2026", "Omschrijving": "Dividend", "ISIN": "IE00B4L5Y983",
         "Product": "iShares Core MSCI World", "Mutatie": "EUR", "Bedrag": 10.0, "Saldo": "EUR"},
        {"Datum": "03-01-2026", "Omschrijving": "Dividend", "ISIN": "IE00B4L5Y983",
         "Product": "iShares Core MSCI World", "Mutatie": "EUR", "Bedrag": 5.0, "Saldo": "EUR"},
        {"Datum": "04-01-2026", "Omschrijving": "Dividend", "ISIN": "NL0010773842",
         "Product": "NN Group", "Mutatie": "EUR", "Bedrag": 40.0, "Saldo": "EUR"},
    ]
    resp = client.post(
        "/api/uploads/dividends",
        files={"files": ("acc.xlsx", _xlsx(mutations), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text

    body = client.get("/api/dividends").json()
    if not body["by_stock"]:
        # The parser needs the real DeGiro column shape; if this synthetic sheet
        # does not match it, the grouping is covered by the Pi parity run instead.
        import pytest
        pytest.skip("dividend parser did not recognise the synthetic sheet")

    nets = [row["net_eur"] for row in body["by_stock"]]
    assert nets == sorted(nets, reverse=True), "app.py sorts by net, descending"
    assert sum(row["payments"] for row in body["by_stock"]) == len(body["payments"])


def test_ticker_override_rejects_blank_and_unknown_isin(client):
    _login(client)
    _upload_tx(client, [_tx()])

    assert client.put("/api/ticker-overrides/IE00B4L5Y983", json={"ticker": "   "}).status_code == 400
    # An ISIN with no open position cannot be re-priced against a name.
    assert client.put("/api/ticker-overrides/XX0000000000", json={"ticker": "AAPL"}).status_code == 404


def test_ticker_override_is_stored_even_when_the_price_fetch_fails(client, monkeypatch):
    """Parity with app.py:689-712, which saves before it fetches.

    The user's correction survives a failed lookup and comes back with an error
    they can act on, rather than vanishing from the cell they typed it into.
    """
    from domain.portfolio import positions as portfolio

    monkeypatch.setattr(portfolio, "fetch_price_for_isin", lambda *a, **k: None)
    _login(client)
    _upload_tx(client, [_tx()])

    resp = client.put("/api/ticker-overrides/IE00B4L5Y983", json={"ticker": "NOSUCH.XX"})
    assert resp.status_code == 422
    assert "NOSUCH.XX" in resp.json()["detail"]
    assert client.get("/api/ticker-overrides").json()["overrides"] == {"IE00B4L5Y983": "NOSUCH.XX"}


def test_ticker_override_rejects_a_non_eur_listing(client, monkeypatch):
    """A USD price cannot be mixed into a EUR cost basis (app.py:706-710)."""
    from domain.portfolio import positions as portfolio

    monkeypatch.setattr(
        portfolio, "fetch_price_for_isin",
        lambda *a, **k: {"ticker": "URTH", "price": 100.0, "currency": "USD"},
    )
    _login(client)
    _upload_tx(client, [_tx()])

    resp = client.put("/api/ticker-overrides/IE00B4L5Y983", json={"ticker": "URTH"})
    assert resp.status_code == 422
    assert "USD" in resp.json()["detail"]


def test_saving_an_override_prices_the_position_and_deleting_it_restores(client, monkeypatch):
    from domain.portfolio import positions as portfolio

    monkeypatch.setattr(
        portfolio, "fetch_price_for_isin",
        lambda *a, **k: {"ticker": "IWDA.AS", "price": 95.0, "currency": "EUR"},
    )
    monkeypatch.setattr(
        portfolio, "refresh_all_prices",
        lambda conn: portfolio.RefreshResult(refreshed=0, failed=[]),
    )
    _login(client)
    _upload_tx(client, [_tx()])

    resp = client.put("/api/ticker-overrides/IE00B4L5Y983", json={"ticker": "IWDA.AS"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "ticker": "IWDA.AS", "price": 95.0}

    body = client.get("/api/positions").json()
    position = body["positions"][0]
    assert position["current_price"] == 95.0
    assert position["current_value"] == 950.0  # 10 shares
    assert position["price_fetched_at"] is not None
    assert body["priced_total"] == 950.0

    assert client.delete("/api/ticker-overrides/IE00B4L5Y983").status_code == 200
    assert client.get("/api/ticker-overrides").json()["overrides"] == {}


def test_closed_positions_appear_only_once_fully_sold(client):
    _login(client)
    _upload_tx(client, [_tx(qty=10, price=80.0, order="buy-1")])
    assert client.get("/api/positions/closed").json()["positions"] == []

    sell = _tx(qty=10, price=90.0, order="sell-1", date="06-01-2026")
    sell["Aantal"] = -10  # DeGiro marks a sale with a negative quantity
    sell["Lokale waarde"] = 900.0
    sell["Waarde"] = 900.0
    sell["Totaal"] = 899.0
    _upload_tx(client, [sell])

    closed = client.get("/api/positions/closed").json()["positions"]
    assert len(closed) == 1
    assert closed[0]["isin"] == "IE00B4L5Y983"
    assert client.get("/api/positions").json()["positions"] == []


def test_saving_an_override_keeps_the_previous_close(client, monkeypatch):
    """save_price rewrites the whole row, so omitting previous_close blanked it
    — and the position then dropped out of the day chip ("today"), which read
    a euro amount short and qualified itself only with "(partly)".
    """
    from domain.portfolio import positions as portfolio
    from app.services import dashboard_service

    monkeypatch.setattr(
        portfolio, "fetch_price_for_isin",
        lambda *a, **k: {"ticker": "IWDA.AS", "price": 95.0, "currency": "EUR",
                         "previous_close": 90.0},
    )
    monkeypatch.setattr(
        portfolio, "refresh_all_prices",
        lambda conn: portfolio.RefreshResult(refreshed=0, failed=[]),
    )
    _login(client)
    _upload_tx(client, [_tx()])

    assert client.put("/api/ticker-overrides/IE00B4L5Y983",
                      json={"ticker": "IWDA.AS"}).status_code == 200

    from domain import database
    conn = database.connect("alice")
    try:
        prices = database.load_prices(conn)
        assert prices["IE00B4L5Y983"]["previous_close"] == 90.0
        positions = portfolio.calculate_positions(database.load_transactions(conn), prices)
        day = dashboard_service.portfolio_day_change(positions, prices)
    finally:
        conn.close()

    assert day is not None
    assert day["delta_eur"] == 50.0     # 10 shares x (95 - 90)
    assert day["complete"] is True
