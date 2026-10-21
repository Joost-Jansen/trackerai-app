"""
/api/holdings/overview — the wiring, not the arithmetic.

The numbers are pinned by test_holdings_service.py against plain dicts; what
this file covers is what only the endpoint can get wrong: auth, per-user
scoping, and that a real DeGiro-shaped upload survives the whole path from
xlsx to the payload the Portfolio tab renders.
"""

import io

import pandas as pd


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _xlsx(rows: list[dict]) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    return buf.getvalue()


def _tx(isin="IE00B4L5Y983", name="iShares Core MSCI World", qty=10, price=80.5, order="order-1", date="05-01-2026", fee=-1.0):
    """A buy, with DeGiro's own signs: value and total negative, fee on top."""
    value = -(qty * price)
    return {
        "Datum": date,
        "Tijd": "09:30",
        "Product": name,
        "ISIN": isin,
        "Beurs": "EAM",
        "Uitvoeringsplaats": "EAM",
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
    resp = client.post(
        "/api/uploads/transactions",
        files={"files": ("tx.xlsx", _xlsx(rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text


def test_overview_requires_auth(client):
    assert client.get("/api/holdings/overview").status_code == 401


def test_empty_portfolio_returns_an_empty_table_not_an_error(client):
    _login(client)
    body = client.get("/api/holdings/overview").json()
    assert body["positions"] == []
    assert body["totals"]["num_positions"] == 0
    assert body["totals"]["value"] == 0
    assert body["totals"]["day"] is None


def test_upload_flows_through_to_the_cost_split(client):
    """10 shares at 80,50 plus a 1 euro fee: GAK 80,50 and 806 invested."""
    _login(client)
    _upload_tx(client, [_tx()])

    body = client.get("/api/holdings/overview").json()
    assert len(body["positions"]) == 1
    row = body["positions"][0]
    assert row["isin"] == "IE00B4L5Y983"
    assert row["shares_held"] == 10
    assert row["avg_cost_ex_costs"] == 80.5
    assert row["invested_ex_costs"] == 805.0
    assert row["invested_gross"] == 806.0
    assert row["costs_eur"] == 1.0
    # No price was fetched in the test (no network), so every price-derived
    # figure is absent rather than zero.
    assert row["current_value"] is None
    assert row["total_eur"] is None


def test_overview_is_scoped_to_the_logged_in_user(client):
    _login(client, "alice", "alicepw")
    _upload_tx(client, [_tx()])
    assert len(client.get("/api/holdings/overview").json()["positions"]) == 1

    client.post("/api/auth/logout")
    _login(client, "bob", "bobpw")
    assert client.get("/api/holdings/overview").json()["positions"] == []
