"""
To label: the counter, the suspicious labels and the fixed costs.

Suspicious is what the rules labelled while it looks like the money moved
between your own accounts: your own IBAN in the description, or the name of
your own transfers.
"""

from domain.money import bank_transactions
from domain import database


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _account(client, name, iban=None) -> int:
    r = client.post("/api/accounts", json={"kind": "bank", "provider": "manual", "name": name, "iban": iban})
    return r.json()["account"]["id"]


def _import(account_id, date, amount, name, description="", counterparty=None, user="alice"):
    """As if from an export: not manual, so the rules label it."""
    conn = database.connect(user)
    bank_transactions.save(conn, account_id, [{
        "date": date, "interest_date": None, "amount": amount, "currency": "EUR", "name": name,
        "counterparty_iban": counterparty, "description": description, "code": None, "kind": None,
        "dedup_hash": f"{account_id}{date}{amount}{name}"[:40], "raw": {},
    }])
    conn.close()


def _relabel(client):
    assert client.post("/api/categories/relabel?everything=true").status_code == 200


def test_the_counter_counts_everything_without_a_category(client):
    _login(client)
    rid = _account(client, "Bank")
    for i in range(3):
        _import(rid, f"2026-05-0{i + 1}", 10.0 + i, f"ONBEKENDE ZAAK {i}")
    _relabel(client)
    r = client.get("/api/categories/unknown?limit=1").json()
    assert len(r["counterparties"]) == 1 and r["count"] == 3


def test_your_own_iban_in_the_description_is_an_own_account_at_once(client):
    """Used to be a suspicious label to correct yourself; now the engine knows it by itself."""
    _login(client)
    ing = _account(client, "ING", "NL00INGB0000000001")
    bunq = _account(client, "bunq", "NL00BUNQ0000000002")
    _import(bunq, "2026-03-12", -1400.0, "Adyen Merchant Payout EUR",
            "iDEAL Top Up from NL00INGB0000000001", counterparty="NL46BUNQ0000000003")
    _relabel(client)
    conn = database.connect("alice")
    [row] = bank_transactions.load(conn)
    conn.close()
    assert row["category"] == "Eigen rekeningen"
    assert client.get("/api/categories/suspicious").json()["transactions"] == []


def test_the_name_of_your_own_transfers_is_suspicious(client):
    _login(client)
    ing = _account(client, "ING", "NL00INGB0000000001")
    bunq = _account(client, "bunq", "NL00BUNQ0000000002")
    _import(bunq, "2026-01-10", -500.0, "J. de Vries", counterparty="NL00INGB0000000001")   # demonstrably own
    _import(bunq, "2026-02-10", -900.0, "J. de Vries")                                      # without IBAN
    _relabel(client)
    suspicious = client.get("/api/categories/suspicious").json()["transactions"]
    assert [(v["date"], v["amount"]) for v in suspicious] == [("2026-02-10", -900.0)]


def test_what_you_set_by_hand_is_never_suspicious(client):
    _login(client)
    ing = _account(client, "ING", "NL00INGB0000000001")
    bunq = _account(client, "bunq", "NL00BUNQ0000000002")
    _import(bunq, "2026-01-10", -500.0, "J. de Vries", counterparty="NL00INGB0000000001")
    _import(bunq, "2026-02-10", -900.0, "J. de Vries")
    _relabel(client)
    tid = client.get("/api/categories/suspicious").json()["transactions"][0]["id"]
    client.put("/api/bank-transactions/category", json={"ids": [tid], "category": "Overige inkomsten"})
    assert client.get("/api/categories/suspicious").json()["transactions"] == []


def test_fixed_costs_endpoint(client):
    _login(client)
    rid = _account(client, "Bank")
    from datetime import date, timedelta
    today = date.today()
    for i in range(4):
        on_date = (today.replace(day=1) - timedelta(days=30 * i)).replace(day=3)
        _import(rid, on_date.isoformat(), 12.99, "NETFLIX.COM")
    _relabel(client)
    r = client.get("/api/spending/fixed-costs").json()
    assert [v["name"] for v in r["fixed_costs"]] == ["NETFLIX.COM"]
    assert client.get(f"/api/spending/fixed-costs?account_id={rid + 99}").json()["fixed_costs"] == []
