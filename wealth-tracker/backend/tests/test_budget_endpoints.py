"""
/api/budget — the budget per group over HTTP, separated per user.

The arithmetic is pinned down in backend/tests/domain/test_budget.py; here the wiring.
"""


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _a_spending_group(client) -> str:
    cats = client.get("/api/categories").json()["categories"]
    return next(c["group_name"] for c in cats if c["type"] == "EXPENSE")


def test_without_a_session_nothing(client):
    assert client.get("/api/budget").status_code == 401
    assert client.put("/api/budget/Wonen", json={"amount": 1}).status_code == 401


def test_setting_returns_the_new_overview(client):
    _login(client)
    group_name = _a_spending_group(client)
    r = client.put(f"/api/budget/{group_name}", json={"amount": 350})
    assert r.status_code == 200, r.text
    assert r.json()["total"]["budget"] == 350.0
    assert client.get("/api/budget").json()["total"]["budget"] == 350.0


def test_empty_removes_it(client):
    _login(client)
    group_name = _a_spending_group(client)
    client.put(f"/api/budget/{group_name}", json={"amount": 350})
    assert client.put(f"/api/budget/{group_name}", json={"amount": None}).json()["total"]["budget"] is None


def test_an_unknown_group_is_404(client):
    _login(client)
    assert client.put("/api/budget/Bestaat%20niet", json={"amount": 10}).status_code == 404


def test_a_negative_amount_is_400(client):
    _login(client)
    group_name = _a_spending_group(client)
    assert client.put(f"/api/budget/{group_name}", json={"amount": -10}).status_code == 400


def test_everyone_their_own_budget(client):
    _login(client)
    group_name = _a_spending_group(client)
    client.put(f"/api/budget/{group_name}", json={"amount": 350})
    client.post("/api/auth/logout")
    _login(client, "bob", "bobpw")
    assert client.get("/api/budget").json()["total"]["budget"] is None


def test_fixed_costs_admin_and_choice(client):
    _login(client)
    assert client.get("/api/spending/fixed-costs/manage").json() == {"is_fixed": [], "candidates": [], "excluded": []}
    r = client.put("/api/spending/fixed-costs/choice", json={"name": "Kroeg", "is_fixed": False})
    assert r.status_code == 200, r.text
    assert [v["key"] for v in r.json()["excluded"]] == ["KROEG"]
    assert client.put("/api/spending/fixed-costs/choice", json={"name": "123", "is_fixed": True}).status_code == 400
    assert client.put("/api/spending/fixed-costs/choice", json={"name": "Kroeg", "is_fixed": None}).json()["excluded"] == []
