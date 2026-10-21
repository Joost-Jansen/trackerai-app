"""
Letting Claude help: the endpoints. Off by default and not available without a
key; Claude itself is never called here.
"""


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def test_without_a_key_it_is_not_there(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _login(client)
    status = client.get("/api/categories/ai").json()
    assert status["available"] is False and status["on"] is False and status["transactions"] == []
    assert client.post("/api/categories/ai/analyse").status_code == 400


def test_turning_it_on_is_a_preference(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    _login(client)
    assert client.put("/api/preferences/ai_labelling", json={"value": {"on": True}}).status_code == 200
    status = client.get("/api/categories/ai").json()
    assert status["available"] is True and status["on"] is True


def test_a_decision_must_be_a_known_choice(client):
    _login(client)
    assert client.post("/api/categories/ai/check/decision", json={"ids": [1], "choice": "misschien"}).status_code == 400
    assert client.post("/api/categories/ai/verify").status_code == 400  # not turned on


def test_not_right_without_transactions(client):
    _login(client)
    assert client.post("/api/categories/ai/reject", json={"ids": []}).status_code == 400


def test_the_queue_and_a_decision(client):
    _login(client)
    w = client.get("/api/labelling/queue").json()
    assert {"items", "tellers", "waiting", "coverage", "claude"} <= set(w)
    assert client.post("/api/labelling/decision", json={"decisions": [{"kind": "x", "choice": "agreed"}]}).status_code == 400
