"""
The tour's example data: while the walk is on a page, the web client sends
`X-Example-Data: 1` and the data pages read a shared, made-up example account.

What must hold: it only ever reads, it never touches the user's own data,
nothing personal comes from it, agents can't use it, and nobody can register
or log in as it.
"""

import datetime

import pytest

EXAMPLE = {"X-Example-Data": "1"}


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _accounts(client, headers=None):
    r = client.get("/api/accounts", headers=headers or {})
    assert r.status_code == 200, r.text
    data = r.json()
    return data.get("accounts", data) if isinstance(data, dict) else data


def test_example_mode_reads_the_example_account(client):
    _login(client)
    assert _accounts(client) == []
    names = {a["name"] for a in _accounts(client, EXAMPLE)}
    assert {"Betaalrekening", "Spaarrekening", "Studieschuld"} <= names
    # Leaving example mode is the user's own (empty) data again.
    assert _accounts(client) == []


def test_example_data_cannot_be_changed(client):
    _login(client)
    r = client.post("/api/accounts", json={"name": "X", "kind": "bank"}, headers=EXAMPLE)
    assert r.status_code == 403
    r = client.put("/api/budget/Wonen", json={"amount": 1}, headers=EXAMPLE)
    assert r.status_code == 403
    # And the user's own data stayed empty.
    assert _accounts(client) == []


def test_personal_routes_ignore_the_header(client):
    _login(client)
    # The tour saves its step while showing example pages: that is the real user.
    assert client.put("/api/onboarding", json={"step": 3}, headers=EXAMPLE).status_code == 200
    assert client.get("/api/onboarding").json()["step"] == 3
    assert client.get("/api/auth/me", headers=EXAMPLE).json()["username"] == "alice"


def test_agents_never_get_example_data():
    from starlette.requests import Request
    from app.deps import CurrentUser, example_mode

    def req(path):
        return Request({"type": "http", "method": "GET", "path": path, "headers": [(b"x-example-data", b"1")]})

    cookie = CurrentUser(username="alice", name="A", is_admin=False, beta_features=[])
    agent = CurrentUser(username="alice", name="A", is_admin=False, beta_features=[], via="agent")
    assert example_mode(req("/api/accounts"), cookie)
    assert not example_mode(req("/api/accounts"), agent)
    assert not example_mode(req("/api/admin/tracker"), cookie)
    assert not example_mode(req("/api/accountsX"), cookie)


def test_the_example_name_cannot_be_registered(client):
    from app.core import auth_store

    with auth_store._locked_update() as cfg:
        cfg["registration_mode"] = "open"
    for name in ("_example", "_Example-next"):
        with pytest.raises(auth_store.AuthError):
            auth_store.register_user(name, name, "pw-123456", "")


def test_the_example_is_rebuilt_after_a_week(client):
    from app.services import example_service

    today = datetime.date.today()
    example_service.ensure(today)
    assert example_service.fresh(today)
    assert example_service.fresh(today + datetime.timedelta(days=6))
    assert not example_service.fresh(today + datetime.timedelta(days=7))
