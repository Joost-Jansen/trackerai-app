"""
/api/holdings/{isin} and its two chart routes — the wiring behind a click on a
row of the Portfolio tab.

The figures themselves are pinned by test_holdings_service.py; what only the
endpoint can get wrong is which position a URL resolves to (an ISIN held on two
exchanges is two positions, with two different GAKs), that "overview" is not
read as an ISIN, and that a missing ticker yields an empty chart rather than a
404 or a stack trace.
"""

import io

import pandas as pd
import pytest

from app.services import asset_service


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _xlsx(rows: list[dict]) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    return buf.getvalue()


def _tx(
    isin="IE00B4L5Y983", name="iShares Core MSCI World", qty=10, price=80.5, order="order-1", date="05-01-2026", fee=-1.0, exchange="EAM"
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
    resp = client.post(
        "/api/uploads/transactions",
        files={"files": ("tx.xlsx", _xlsx(rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text


@pytest.fixture()
def no_network(monkeypatch):
    """Both downloads stubbed: these tests are about routing, not about Yahoo."""
    monkeypatch.setattr(asset_service, "_fetch_daily", lambda t: {"points": [{"d": "2026-08-03", "c": 81.0}]})
    monkeypatch.setattr(
        asset_service, "_fetch_intraday", lambda t: {"points": [{"d": "2026-08-04T10:00+00:00", "c": 81.0}], "prev_close": None}
    )


# ---------------------------------------------------------------------------
# The position payload
# ---------------------------------------------------------------------------


def test_detail_requires_auth(client):
    assert client.get("/api/holdings/IE00B4L5Y983").status_code == 401


def test_unknown_isin_is_a_404(client):
    _login(client)
    assert client.get("/api/holdings/NL0000000000").status_code == 404


def test_overview_is_not_read_as_an_isin(client):
    """Route order: /overview is declared first, so it keeps winning."""
    _login(client)
    body = client.get("/api/holdings/overview").json()
    assert "totals" in body


def test_detail_carries_the_same_row_as_the_table(client):
    _login(client)
    _upload_tx(client, [_tx()])

    row = client.get("/api/holdings/overview").json()["positions"][0]
    detail = client.get("/api/holdings/IE00B4L5Y983").json()

    assert detail["position"] == row
    assert detail["first_buy"] == "2026-01-05"
    assert detail["num_transactions"] == 1
    assert detail["other_venues"] == []


def test_two_venues_are_two_positions_with_their_own_avg_cost(client):
    """The same fund on Amsterdam and Tradegate is two rows in DeGiro, each
    with its own average price — so ?beurs= has to pick one, not merge them."""
    _login(client)
    _upload_tx(
        client,
        [
            _tx(qty=10, price=80.0, order="a", exchange="EAM"),
            _tx(qty=10, price=90.0, order="b", exchange="TDG"),
        ],
    )

    eam = client.get("/api/holdings/IE00B4L5Y983?exchange=EAM").json()
    tdg = client.get("/api/holdings/IE00B4L5Y983?exchange=TDG").json()

    assert eam["position"]["avg_cost_ex_costs"] == 80.0
    assert tdg["position"]["avg_cost_ex_costs"] == 90.0
    assert [v["exchange"] for v in eam["other_venues"]] == ["TDG"]
    # A link that carries no venue still lands on a real position of that ISIN.
    assert client.get("/api/holdings/IE00B4L5Y983").json()["position"]["exchange"] in {"EAM", "TDG"}


def test_a_venue_that_is_not_held_is_a_404(client):
    _login(client)
    _upload_tx(client, [_tx(exchange="EAM")])
    assert client.get("/api/holdings/IE00B4L5Y983?exchange=XET").status_code == 404


def test_detail_is_scoped_to_the_logged_in_user(client):
    _login(client, "alice", "alicepw")
    _upload_tx(client, [_tx()])
    assert client.get("/api/holdings/IE00B4L5Y983").status_code == 200

    client.post("/api/auth/logout")
    _login(client, "bob", "bobpw")
    assert client.get("/api/holdings/IE00B4L5Y983").status_code == 404


# ---------------------------------------------------------------------------
# The chart routes
# ---------------------------------------------------------------------------


def test_charts_are_empty_without_a_price_row(client, no_network):
    """No price was ever fetched here (no network in the tests), so there is no
    ticker to ask Yahoo about. That is a chartless position, not an error."""
    _login(client)
    _upload_tx(client, [_tx()])

    assert client.get("/api/holdings/IE00B4L5Y983/history").json() == {"points": []}
    assert client.get("/api/holdings/IE00B4L5Y983/intraday").json() == {"points": [], "prev_close": None}


def test_charts_follow_the_stored_ticker(client, no_network):
    _login(client)
    _upload_tx(client, [_tx()])

    from domain import database

    with database.user_db("alice") as conn:
        database.save_price(conn, isin="IE00B4L5Y983", name="iShares Core MSCI World", ticker="IWDA.AS", price=81.5, currency="EUR")

    assert client.get("/api/holdings/IE00B4L5Y983/history").json()["points"] == [{"d": "2026-08-03", "c": 81.0}]
    # The last bar is the cached quote, not the feed's own last print.
    assert client.get("/api/holdings/IE00B4L5Y983/intraday").json()["points"][-1]["c"] == 81.5
