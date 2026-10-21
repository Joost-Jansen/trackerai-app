"""
/api/onboarding — what you track, whether the welcome flow is done, and where you are.

With your account and not in your browser, so the tour does not come again on
your phone. An existing user with data is already on their way.
"""


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def test_without_a_session_nothing(client):
    assert client.get("/api/onboarding").status_code == 401


def test_a_new_user_gets_the_welcome_flow(client):
    _login(client)
    r = client.get("/api/onboarding").json()
    assert r["done"] is False and r["choice"] is None
    assert r["status"]["portfolio"] == {"transactions": 0, "dividends": 0}
    assert r["status"]["money"]["accounts"] == 0 and r["status"]["money"]["linked"] is False


def test_choice_and_done_are_kept(client):
    _login(client)
    r = client.put("/api/onboarding", json={"choice": "both"}).json()
    assert r["choice"] == "both" and r["done"] is False
    r = client.put("/api/onboarding", json={"done": True}).json()
    assert r["choice"] == "both" and r["done"] is True
    assert client.get("/api/onboarding").json()["done"] is True


def test_how_bank_data_comes_in_is_kept(client):
    """Exports only, or exports with the automatic bank connection on top."""
    _login(client)
    assert client.get("/api/onboarding").json()["bank"] is None
    r = client.put("/api/onboarding", json={"bank": "connect"}).json()
    assert r["bank"] == "connect"
    # Other fields don't wipe it.
    assert client.put("/api/onboarding", json={"step": 4}).json()["bank"] == "connect"
    assert client.put("/api/onboarding", json={"bank": "fax"}).status_code == 400


def test_tour_again(client):
    _login(client)
    client.put("/api/onboarding", json={"choice": "money", "done": True})
    assert client.put("/api/onboarding", json={"done": False}).json()["done"] is False


def test_nonsense_is_400(client):
    _login(client)
    assert client.put("/api/onboarding", json={"choice": "crypto"}).status_code == 400
    assert client.put("/api/onboarding", json={"iets": 1}).status_code == 400


def test_who_already_has_data_is_on_their_way(client):
    _login(client)
    r = client.post("/api/accounts", json={"kind": "bank", "provider": "manual", "name": "Bank"})
    rid = r.json()["account"]["id"]
    client.post(
        "/api/bank-transactions", json={"account_id": rid, "date": "2026-05-01", "amount": 10, "direction": "expense", "name": "Winkel"}
    )
    r = client.get("/api/onboarding").json()
    assert r["done"] is True and r["choice"] == "money"
    assert r["status"]["money"]["without_balance"] == ["Bank"]


def test_everyone_their_own_onboarding(client):
    _login(client)
    client.put("/api/onboarding", json={"choice": "investments", "done": True})
    client.post("/api/auth/logout")
    _login(client, "bob", "bobpw")
    assert client.get("/api/onboarding").json()["done"] is False


def test_the_tour_continues_where_you_were(client):
    _login(client)
    assert client.get("/api/onboarding").json()["step"] == 0
    client.put("/api/onboarding", json={"choice": "both", "step": 4})
    assert client.get("/api/onboarding").json()["step"] == 4
    assert client.put("/api/onboarding", json={"step": -1}).status_code == 400
    r = client.put("/api/onboarding", json={"done": False, "step": 0}).json()
    assert r["step"] == 0 and r["choice"] == "both"
