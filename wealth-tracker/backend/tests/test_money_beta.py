"""
Money behind the beta flag `money`.

A hidden tab is not a lock: every money router must refuse by itself, and the
welcome flow must drop Money for an account without the flag.
"""

import pytest

from app.core import auth_store


def _login(client, who="alice"):
    return client.post("/api/auth/login", json={"username": who, "password": f"{who}pw"})


def _set_flag(who: list[str]):
    cfg = auth_store.load_config()
    cfg["beta"] = {"money": who}
    auth_store.save_config(cfg)


ENDPOINTS = [
    ("get", "/api/accounts"),
    ("get", "/api/bank-transactions"),
    ("get", "/api/categories"),
    ("get", "/api/labelling/queue"),
    ("get", "/api/spending/fixed-costs"),
    ("get", "/api/budget"),
    ("get", "/api/month-periods"),
    ("get", "/api/net-worth"),
    ("get", "/api/connections"),
    ("post", "/api/uploads/bank"),
]


def test_money_is_a_registered_beta_flag():
    assert "money" in auth_store.BETA_FEATURES


@pytest.mark.parametrize("method,path", ENDPOINTS)
def test_without_the_flag_every_money_router_refuses(client, method, path):
    _set_flag(["bob"])
    _login(client)
    assert getattr(client, method)(path).status_code == 403


def test_with_the_flag_it_opens(client):
    _set_flag(["alice"])
    _login(client)
    assert client.get("/api/accounts").status_code == 200
    assert "money" in client.get("/api/auth/me").json()["beta_features"]


def test_an_admin_always_has_it(client):
    cfg = auth_store.load_config()
    cfg["beta"] = {}
    cfg["admins"] = ["alice"]
    auth_store.save_config(cfg)
    _login(client)
    assert client.get("/api/accounts").status_code == 200


def test_without_the_flag_you_only_track_investments(client):
    _login(client)
    assert client.put("/api/onboarding", json={"choice": "both"}).status_code == 200

    _set_flag([])
    data = client.get("/api/onboarding").json()
    assert data["money"] is False and data["choice"] == "investments"
    assert client.put("/api/onboarding", json={"choice": "money"}).status_code == 403
    assert client.put("/api/onboarding", json={"choice": "investments"}).status_code == 200

    # The flag on again: the stored choice does not come back, because you just chose investments yourself.
    _set_flag(["alice"])
    data = client.get("/api/onboarding").json()
    assert data["money"] is True and data["choice"] == "investments"


def test_your_own_choice_comes_back_when_the_flag_is_on_again(client):
    _login(client)
    client.put("/api/onboarding", json={"choice": "both"})
    _set_flag([])
    assert client.get("/api/onboarding").json()["choice"] == "investments"
    _set_flag(["alice"])
    assert client.get("/api/onboarding").json()["choice"] == "both"
