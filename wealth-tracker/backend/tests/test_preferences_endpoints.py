"""
/api/preferences — how you set up a screen, stored with your account.
"""


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def test_without_a_session_nothing(client):
    assert client.get("/api/preferences/spending_overview").status_code == 401


def test_empty_by_default_and_kept_afterwards(client):
    _login(client)
    assert client.get("/api/preferences/spending_overview").json() == {"value": None}
    layout = {"charts": [{"id": "price", "visible": True, "settings": {"measure": "amount"}}]}
    r = client.put("/api/preferences/spending_overview", json={"value": layout})
    assert r.status_code == 200 and r.json()["value"] == layout
    assert client.get("/api/preferences/spending_overview").json()["value"] == layout


def test_empty_restores_the_default(client):
    _login(client)
    client.put("/api/preferences/spending_overview", json={"value": {"a": 1}})
    assert client.put("/api/preferences/spending_overview", json={"value": None}).json() == {"value": None}


def test_unknown_key_and_too_large(client):
    _login(client)
    assert client.get("/api/preferences/iets").status_code == 404
    assert client.put("/api/preferences/spending_overview", json={"value": {"x": "a" * 20000}}).status_code == 400


def test_everyone_their_own_preferences(client):
    _login(client)
    client.put("/api/preferences/spending_overview", json={"value": {"a": 1}})
    client.post("/api/auth/logout")
    _login(client, "bob", "bobpw")
    assert client.get("/api/preferences/spending_overview").json() == {"value": None}
