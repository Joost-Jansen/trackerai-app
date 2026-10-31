"""
Trade Republic through the API: the upload, the broker account, entering by
hand (browser and agent) and how the Portfolio tab lists two brokers.

The parsing and the ledger arithmetic are pinned in
tests/domain/test_trade_republic.py; this file covers the wiring.
"""

import io
import pathlib

import pandas as pd
import pytest
from fastapi.testclient import TestClient

FIXTURE = pathlib.Path(__file__).resolve().parent / "data" / "trade_republic_export.csv"
VWCE = "IE00BK5BQT80"


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _upload(client, content: bytes, name="export.csv"):
    return client.post("/api/uploads/trade-republic", files={"files": (name, content, "text/csv")})


def _tr_account(client) -> int:
    r = client.post("/api/brokers/accounts", json={"broker": "trade_republic"})
    assert r.status_code == 200, r.text
    return r.json()["account"]["id"]


def _degiro_buy(client, qty=10, price=100.0):
    buf = io.BytesIO()
    value = -(qty * price)
    pd.DataFrame(
        [
            {
                "Datum": "05-10-2026",
                "Tijd": "09:30",
                "Product": "VANGUARD FTSE AW",
                "ISIN": VWCE,
                "Beurs": "XET",
                "Uitvoeringsplaats": "XETA",
                "Aantal": qty,
                "Koers": price,
                "Lokale waarde": value,
                "Waarde": value,
                "Wisselkoers": 1.0,
                "Transactiekosten": -3.0,
                "Totaal": value - 3.0,
                "Order Id": "dg-1",
            }
        ]
    ).to_excel(buf, index=False)
    r = client.post(
        "/api/uploads/transactions",
        files={"files": ("tx.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text


def _price(isin, price):
    from domain import database

    with database.user_db("alice") as conn:
        database.init_db(conn)
        database.save_price(conn, isin, isin, "T", price, "EUR")


# --- upload ------------------------------------------------------------------


def test_upload_requires_a_session(client):
    assert _upload(client, FIXTURE.read_bytes()).status_code == 401


def test_upload_reads_trades_dividends_and_cash(client):
    _login(client)
    r = _upload(client, FIXTURE.read_bytes())
    assert r.status_code == 200, r.text
    result = r.json()["results"][0]
    assert (result["saved"], result["dividends"], result["cash_entries"]) == (4, 1, 9)
    assert result["unread"] == [{"line": 11, "type": "CARD_TRANSACTION", "reason": "currency USD"}]

    again = _upload(client, FIXTURE.read_bytes()).json()["results"][0]
    assert (again["saved"], again["skipped"], again["cash_entries"]) == (0, 4, 0)

    brokers = client.get("/api/brokers").json()
    (account,) = brokers["accounts"]
    assert account["broker"] == "trade_republic" and account["stack"] == "investments"
    assert account["balance"] == pytest.approx(47.51)

    txs = client.get("/api/transactions").json()["transactions"]
    assert {t["broker"] for t in txs} == {"trade_republic"}


def test_a_degiro_file_is_refused_with_a_reason(client):
    _login(client)
    r = _upload(client, b"Datum,Tijd,Product,ISIN,Aantal\n01-01-2026,09:00,X,IE00BK5BQT80,1\n", "degiro.csv")
    assert r.status_code == 422
    assert "Trade Republic" in r.json()["detail"]


# --- the account and manual entry --------------------------------------------


def test_the_account_is_made_once(client):
    _login(client)
    first = client.post("/api/brokers/accounts", json={"broker": "trade_republic"}).json()
    second = client.post("/api/brokers/accounts", json={"broker": "trade_republic"}).json()
    assert first["created"] is True and second["created"] is False
    assert first["account"]["id"] == second["account"]["id"]
    assert client.post("/api/brokers/accounts", json={"broker": "nope"}).status_code == 400


def test_entering_a_savings_plan_by_hand(client):
    _login(client)
    aid = _tr_account(client)
    deposit = client.post("/api/brokers/transactions", json={"account_id": aid, "kind": "deposit", "date": "2026-09-01", "amount": 500})
    assert deposit.status_code == 201, deposit.text
    buy = client.post(
        "/api/brokers/transactions",
        json={"broker": "trade_republic", "kind": "buy", "date": "2026-09-03", "isin": VWCE, "quantity": 2.8901, "amount": 400},
    )
    assert buy.status_code == 201, buy.text
    assert buy.json()["account"]["balance"] == pytest.approx(100.0)

    ledger = client.get(f"/api/brokers/accounts/{aid}/ledger").json()["entries"]
    assert [e["kind"] for e in ledger] == ["buy", "deposit"]
    ref = ledger[0]["ref"]
    assert client.delete(f"/api/brokers/transactions/{ref['table']}/{ref['id']}").json() == {"ok": True}
    assert client.get("/api/transactions").json()["transactions"] == []
    assert client.delete(f"/api/brokers/transactions/{ref['table']}/{ref['id']}").status_code == 404


def test_wrong_input_is_a_400_and_a_missing_account_a_404(client):
    _login(client)
    missing = client.post(
        "/api/brokers/transactions", json={"broker": "trade_republic", "kind": "deposit", "date": "2026-09-01", "amount": 5}
    )
    assert missing.status_code == 404
    aid = _tr_account(client)
    bad = client.post(
        "/api/brokers/transactions", json={"account_id": aid, "kind": "buy", "date": "2026-09-01", "isin": "X", "quantity": 1}
    )
    assert bad.status_code == 400


def test_the_cash_counts_in_net_worth(client):
    _login(client)
    aid = _tr_account(client)
    client.post("/api/brokers/transactions", json={"account_id": aid, "kind": "deposit", "date": "2026-01-02", "amount": 750})
    assert client.get("/api/net-worth").json()["now"]["investments"] == pytest.approx(750.0)


# --- two brokers in the portfolio ---------------------------------------------


def test_the_same_fund_at_two_brokers_is_two_rows_and_one_position(client):
    _login(client)
    _degiro_buy(client)
    aid = _tr_account(client)
    client.post(
        "/api/brokers/transactions",
        json={"account_id": aid, "kind": "buy", "date": "2026-09-03", "isin": VWCE, "quantity": 2.5, "price": 120, "fee": 1},
    )
    _price(VWCE, 130.0)

    body = client.get("/api/holdings/overview").json()
    rows = {r["broker"]: r for r in body["positions"]}
    assert set(rows) == {"degiro", "trade_republic"}
    assert rows["trade_republic"]["shares_held"] == pytest.approx(2.5)
    assert rows["trade_republic"]["avg_cost_ex_costs"] == pytest.approx(120.0)
    assert rows["degiro"]["avg_cost_ex_costs"] == pytest.approx(100.0)
    by_broker = {b["broker"]: b for b in body["totals"]["by_broker"]}
    assert by_broker["trade_republic"]["costs_eur"] == pytest.approx(1.0)
    assert by_broker["degiro"]["costs_eur"] == pytest.approx(3.0)

    (position,) = client.get("/api/positions").json()["positions"]
    assert position["shares_held"] == pytest.approx(12.5), "per ISIN everything adds up"

    tr_detail = client.get(f"/api/holdings/{VWCE}?broker=trade_republic").json()
    assert tr_detail["position"]["broker"] == "trade_republic" and tr_detail["num_transactions"] == 1
    assert [v["broker"] for v in tr_detail["other_venues"]] == ["degiro"]


# --- an agent -----------------------------------------------------------------


def _agent(client, scope):
    from app.main import app

    token = client.post("/api/agent-tokens", json={"name": "Claude", "scope": scope}).json()["token"]
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _call(agent, name, args):
    r = agent.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def test_an_agent_records_a_buy_but_does_not_make_the_account(client):
    import json

    _login(client)
    write = _agent(client, "write")
    args = {"broker": "Trade Republic", "kind": "buy", "date": "2026-09-03", "isin": VWCE, "quantity": 0.5, "price": 130}
    assert _call(write, "add_broker_transaction", args)["isError"], "no account yet"
    assert write.post("/api/brokers/accounts", json={"broker": "trade_republic"}).status_code == 403

    _tr_account(client)
    res = _call(write, "add_broker_transaction", args)
    assert not res["isError"], res
    out = json.loads(res["content"][0]["text"])
    assert out["stored"]["table"] == "transactions" and out["account"]["broker"] == "trade_republic"

    read = _agent(client, "read")
    assert _call(read, "add_broker_transaction", args)["isError"]
