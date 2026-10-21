"""
Uploading the account statement also sets the DeGiro cash balance.

Reading itself is pinned down in backend/tests/domain/test_degiro_cash.py. What
is covered here is the wiring: the user already uploads the statement for the
Dividend tab, so the cash balance should come along with it — without a second
upload or button.
"""

import io

import pandas as pd

COLUMNS = [
    "Datum",
    "Tijd",
    "Valutadatum",
    "Product",
    "ISIN",
    "Omschrijving",
    "FX",
    "Mutatie",
    "Unnamed: 8",
    "Saldo",
    "Unnamed: 10",
    "Order Id",
]


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _row(date, time, balance):
    return {
        "Datum": date,
        "Tijd": time,
        "Valutadatum": date,
        "Product": "",
        "ISIN": "",
        "Omschrijving": "iDEAL Deposit",
        "FX": "",
        "Mutatie": "EUR",
        "Unnamed: 8": 0.0,
        "Saldo": "EUR",
        "Unnamed: 10": balance,
        "Order Id": "",
    }


def _overview(*rows) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(list(rows), columns=COLUMNS).to_excel(buf, index=False)
    return buf.getvalue()


def _upload(client, content: bytes):
    return client.post(
        "/api/uploads/dividends",
        files={"files": ("Account.xlsx", content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )


def test_uploading_the_overview_also_sets_the_cash_balance(client):
    _login(client)
    resp = _upload(client, _overview(_row("02-01-2026", "12:00", 1500.0), _row("01-01-2026", "12:00", 1000.0)))
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"][0]["cash_days"] == 2

    cash = [r for r in client.get("/api/accounts").json()["accounts"] if r["provider"] == "degiro"]
    assert len(cash) == 1
    assert cash[0]["balance"] == 1500.0
    assert cash[0]["stack"] == "investments"


def test_the_cash_balance_counts_in_net_worth(client):
    """The whole point: money that sits at DeGiro is net worth."""
    _login(client)
    _upload(client, _overview(_row("01-01-2026", "12:00", 12000.0)))

    now = client.get("/api/net-worth").json()["now"]
    assert now["investments"] == 12000.0


def test_uploading_again_creates_no_second_account(client):
    _login(client)
    content = _overview(_row("01-01-2026", "12:00", 1000.0))
    _upload(client, content)
    _upload(client, content)
    cash = [r for r in client.get("/api/accounts").json()["accounts"] if r["provider"] == "degiro"]
    assert len(cash) == 1
