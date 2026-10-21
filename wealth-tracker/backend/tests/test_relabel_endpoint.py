"""
PUT /api/bank-transactions/category — labelling a whole selection at once.

For what no rule can catch: money from friends for a holiday you paid. Set by
hand, so it wins over the rules; empty puts the rules back to work.
"""


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _account(client) -> int:
    r = client.post("/api/accounts", json={"kind": "bank", "provider": "manual", "name": "bunq"})
    return r.json()["account"]["id"]


def _tx(client, rid, date, amount, direction, name) -> int:
    r = client.post(
        "/api/bank-transactions", json={"account_id": rid, "date": date, "amount": amount, "direction": direction, "name": name}
    )
    assert r.status_code == 201, r.text
    return r.json()["transaction"]["id"]


def _per_id(client) -> dict[int, dict]:
    return {t["id"]: t for t in client.get("/api/bank-transactions").json()["transactions"]}


def test_a_selection_at_once(client):
    _login(client)
    rid = _account(client)
    a = _tx(client, rid, "2026-01-10", 400, "income", "A. Vriend")
    b = _tx(client, rid, "2026-02-10", 400, "income", "B. Vriend")
    c = _tx(client, rid, "2026-02-11", 12, "expense", "Bakker")

    r = client.put("/api/bank-transactions/category", json={"ids": [a, b], "category": "Niet meetellen"})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2
    tx = _per_id(client)
    assert tx[a]["category"] == tx[b]["category"] == "Niet meetellen"
    assert tx[a]["category_manual"] == "Niet meetellen"
    assert tx[c]["category"] != "Niet meetellen", "wat niet gekozen was blijft staan"


def test_empty_hands_it_back_to_the_rules(client):
    _login(client)
    rid = _account(client)
    a = _tx(client, rid, "2026-01-10", 400, "income", "A. Vriend")
    client.put("/api/bank-transactions/category", json={"ids": [a], "category": "Niet meetellen"})
    client.put("/api/bank-transactions/category", json={"ids": [a], "category": None})
    assert _per_id(client)[a]["category_manual"] is None


def test_an_unknown_category_is_400(client):
    _login(client)
    rid = _account(client)
    a = _tx(client, rid, "2026-01-10", 400, "income", "A. Vriend")
    assert client.put("/api/bank-transactions/category", json={"ids": [a], "category": "Bestaat niet"}).status_code == 400


def test_what_does_not_exist_does_not_count(client):
    _login(client)
    r = client.put("/api/bank-transactions/category", json={"ids": [987654], "category": "Niet meetellen"})
    assert r.status_code == 200 and r.json()["updated"] == 0


def test_money_from_friends_leaves_net_worth_flat(client):
    """Received in January, the holiday paid in June: with Niet meetellen net worth is
    not higher in between.
    """
    _login(client)
    rid = _account(client)
    a = _tx(client, rid, "2026-01-10", 2000, "income", "Vrienden")
    b = _tx(client, rid, "2026-06-10", 2000, "expense", "Zeilschool")
    client.put(f"/api/accounts/{rid}/balance", json={"date": "2026-07-01", "balance": 1000})

    def net_on(d):
        points = client.get("/api/net-worth").json()["points"]
        return next(p for p in points if p["d"] == d)["net"]

    assert net_on("2026-03-01") == 3000, "zonder label lijkt het alsof je rijker werd"
    client.put("/api/bank-transactions/category", json={"ids": [a, b], "category": "Niet meetellen"})
    assert net_on("2026-03-01") == 1000


def test_a_payment_processor_is_named_as_such(client):
    """Different shops sit behind Mollie: one rule on that name labels them all the
    same. The list says so, so the screen can offer labelling per transaction.
    """
    _login(client)
    rid = _account(client)
    _tx(client, rid, "2026-05-05", 30, "expense", "STICHTING MOLLIE PAYMENTS")
    _tx(client, rid, "2026-05-06", 20, "expense", "STICHTING MOLLIE PAYMENTS")
    _tx(client, rid, "2026-05-07", 15, "expense", "Kees de Vries Klussen")
    groups = {g["name"]: g for g in client.get("/api/categories/unknown").json()["counterparties"]}
    assert groups["STICHTING MOLLIE PAYMENTS"]["processor"] is True
    assert groups["STICHTING MOLLIE PAYMENTS"]["count"] == 2
    assert all(not g["processor"] for n, g in groups.items() if n != "STICHTING MOLLIE PAYMENTS")
