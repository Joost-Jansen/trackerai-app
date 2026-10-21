"""
Reversals through the uploads: the broker's account statement and the bank, in
either order.

The pairing itself is pinned down in backend/tests/domain/test_reversals.py.
Made-up data, with an IBAN that belongs to no real bank: recognition must
depend on nothing but amount and date.
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
BUNQ_HEADER = '"Date","Interest Date","Amount","Account","Counterparty","Name","Description"'
BANK = "NL00BUNQ0000000009"
ELSEWHERE = "DE00999999990000000001"


def _overview() -> bytes:
    def row(date, time, entry, balance, oms):
        return {
            "Datum": date,
            "Tijd": time,
            "Valutadatum": date,
            "Product": "",
            "ISIN": "",
            "Omschrijving": oms,
            "FX": "",
            "Mutatie": "EUR",
            "Unnamed: 8": entry,
            "Saldo": "EUR",
            "Unnamed: 10": balance,
            "Order Id": "",
        }

    buf = io.BytesIO()
    pd.DataFrame(
        [
            row("07-11-2025", "22:47", -69209.08, 0.0, "Opname"),
            row("05-11-2025", "10:00", 69209.08, 69209.08, "Verkoop"),
        ],
        columns=COLUMNS,
    ).to_excel(buf, index=False)
    return buf.getvalue()


def _bank() -> bytes:
    rules = [BUNQ_HEADER, f'"2025-11-07","2025-11-07","69.209,08","{BANK}","{ELSEWHERE}","A. B. Voorbeeld",""']
    return ("\n".join(rules) + "\n").encode("utf-8")


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _upload_overview(client):
    r = client.post(
        "/api/uploads/dividends",
        files={"files": ("Account.xlsx", _overview(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text


def _upload_bank(client):
    r = client.post("/api/uploads/bank", files=[("files", ("bank.csv", _bank(), "text/csv"))])
    assert r.status_code == 200 and "error" not in r.json()["results"][0], r.text


def _withdrawal(client) -> dict:
    return next(t for t in client.get("/api/bank-transactions").json()["transactions"] if t["counterparty_iban"] == ELSEWHERE)


def test_first_the_bank_then_the_overview(client):
    _login(client)
    _upload_bank(client)
    assert _withdrawal(client)["type"] == "INCOME"  # no counterpart known yet
    _upload_overview(client)
    assert _withdrawal(client)["type"] == "INTERNAL"


def test_first_the_overview_then_the_bank(client):
    _login(client)
    _upload_overview(client)
    _upload_bank(client)
    withdrawal = _withdrawal(client)
    assert withdrawal["category"] == "Naar beleggen" and withdrawal["type"] == "INTERNAL"


def test_the_sale_itself_has_no_counterpart(client):
    """A sale at the broker (+69,209 in) is not a bank row and pairs with nothing;
    only the withdrawal (−69,209 out) belongs with the bank.
    """
    _login(client)
    _upload_overview(client)
    _upload_bank(client)
    assert len(client.get("/api/bank-transactions").json()["transactions"]) == 1
