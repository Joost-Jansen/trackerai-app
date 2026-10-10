"""
/api/returns behind its beta flag.

Hiding a tab in the nav is not access control. These prove the endpoint itself
refuses an account without the flag, that the flag is a real registry entry (so
the admin panel can grant it rather than an admin editing YAML by hand), and
that an account with nothing uploaded gets an empty answer instead of a 500.
"""

import pytest

from app.core import auth_store


def _login(client, who="alice"):
    return client.post("/api/auth/login", json={"username": who, "password": f"{who}pw"})


def test_returns_requires_auth(client):
    assert client.get("/api/returns").status_code == 401


def test_returns_is_refused_without_the_beta_flag(client, monkeypatch):
    # is_admin short-circuits has_beta, and the fixture's accounts are not
    # admins — so this is the plain "granted nothing" case.
    _login(client)
    assert client.get("/api/returns").status_code == 403


def test_returns_opens_up_once_the_flag_is_granted(client, monkeypatch):
    cfg = auth_store.load_config()
    cfg["beta"] = {"returns": ["alice"]}
    auth_store.save_config(cfg)

    _login(client)
    resp = client.get("/api/returns")
    assert resp.status_code == 200
    # Nothing uploaded yet: an empty answer, not an error.
    assert resp.json() == {"points": [], "gaps": [], "ranges": []}


def test_the_flag_bob_has_does_not_open_alices_tab(client):
    cfg = auth_store.load_config()
    cfg["beta"] = {"returns": ["bob"]}
    auth_store.save_config(cfg)

    _login(client, "alice")
    assert client.get("/api/returns").status_code == 403


def test_returns_is_a_registered_beta_feature():
    """The admin panel renders BETA_FEATURES and /api/admin validates against
    it, so a router naming a key that is not in there can never be granted."""
    assert "returns" in auth_store.BETA_FEATURES


def test_me_reports_the_granted_flag_so_the_nav_can_show_the_tab(client):
    cfg = auth_store.load_config()
    cfg["beta"] = {"returns": ["alice"]}
    auth_store.save_config(cfg)

    _login(client)
    assert "returns" in client.get("/api/auth/me").json()["beta_features"]
