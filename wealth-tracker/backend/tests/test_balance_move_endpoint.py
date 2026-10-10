"""POST /api/accounts/{id}/balance/{date}/move: putting a balance on another day."""


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _account(client) -> int:
    r = client.post("/api/accounts", json={"kind": "bank", "provider": "manual", "name": "Bank"})
    assert r.status_code == 201
    return r.json()["account"]["id"]


def test_move_a_balance(client):
    _login(client)
    rid = _account(client)
    client.put(f"/api/accounts/{rid}/balance", json={"date": "2026-09-14", "balance": 305.8})
    r = client.post(f"/api/accounts/{rid}/balance/2026-09-14/move", json={"dest": "2026-09-15"})
    assert r.status_code == 200
    balances = client.get(f"/api/accounts/{rid}/balances").json()["balances"]
    assert [(s["date"], s["balance"]) for s in balances] == [("2026-09-15", 305.8)]


def test_without_a_balance_on_that_day_404(client):
    _login(client)
    rid = _account(client)
    r = client.post(f"/api/accounts/{rid}/balance/2026-09-14/move", json={"dest": "2026-09-15"})
    assert r.status_code == 404


def test_an_odd_date_400(client):
    _login(client)
    rid = _account(client)
    client.put(f"/api/accounts/{rid}/balance", json={"date": "2026-09-14", "balance": 1.0})
    r = client.post(f"/api/accounts/{rid}/balance/2026-09-14/move", json={"dest": "morgen"})
    assert r.status_code == 400
