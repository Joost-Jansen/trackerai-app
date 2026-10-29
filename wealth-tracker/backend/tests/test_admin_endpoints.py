"""
wealth-tracker with the shared admin page: accounts, sign-up and invitations are
the shared account's routes (/api/trackerai/admin, tested in packages/accounts);
here, what they do to wealth-tracker: who may call them, the sign-up modes on
this site's own register route, a suspended session, a deleted account's data
folder, beta flags that open a tab.

These are access control, not a feature: the interesting cases are the ones
where someone who should not get in, does not.
"""

import os

import pytest
import yaml

ADMIN = "/api/trackerai/admin"


@pytest.fixture()
def admin_client(client, tmp_path, monkeypatch):
    """The shared client fixture's alice, an admin (her login moves to the accounts as one)."""
    from app.core import config

    path = config.AUTH_CONFIG_PATH
    cfg = yaml.safe_load(open(path))
    cfg["admins"] = ["alice"]
    yaml.safe_dump(cfg, open(path, "w"))
    return client


def _login(client, user, pw):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _set_mode(client, mode):
    r = client.patch(f"{ADMIN}/registration", json={"registration": mode})
    assert r.status_code == 200, r.text
    return r


def _account_id(client, username):
    return next(a["id"] for a in client.get(f"{ADMIN}/accounts").json() if a["username"] == username)


def _bob_moves_over(client):
    """bob's old login becomes an account on his first login; then alice logs in again."""
    _login(client, "bob", "bobpw")
    _login(client, "alice", "alicepw")


# --- access control --------------------------------------------------------


def test_admin_routes_reject_anonymous(client):
    assert client.get(f"{ADMIN}/accounts").status_code == 401
    assert client.patch(f"{ADMIN}/registration", json={"registration": "open"}).status_code == 401
    assert client.get("/api/admin/tracker").status_code == 401


def test_admin_routes_reject_a_signed_in_non_admin(client):
    """Being logged in is not being an admin."""
    _login(client, "bob", "bobpw")
    assert client.get(f"{ADMIN}/accounts").status_code == 403
    assert client.patch(f"{ADMIN}/registration", json={"registration": "open"}).status_code == 403
    assert client.get("/api/admin/tracker").status_code == 403


def test_the_old_panel_routes_are_gone(admin_client):
    _login(admin_client, "alice", "alicepw")
    for path in ("/api/admin/settings", "/api/admin/audit"):
        assert admin_client.get(path).status_code in (404, 405)


# --- registration modes, on this site's own register route -----------------


def test_open_mode_lets_anyone_register_without_a_code(admin_client):
    _login(admin_client, "alice", "alicepw")
    _set_mode(admin_client, "open")
    assert (
        admin_client.post(
            "/api/auth/register",
            json={
                "username": "carol",
                "email": "carol@example.org",
                "name": "Carol",
                "password": "carol" + "-pw-2026",
            },
        ).status_code
        == 200
    )


def test_invite_mode_requires_the_code(admin_client):
    _login(admin_client, "alice", "alicepw")
    _set_mode(admin_client, "invite")
    code = admin_client.post(f"{ADMIN}/invites", json={"days": 7, "apps": ["wealth"]}).json()["code"]

    assert (
        admin_client.post(
            "/api/auth/register",
            json={
                "username": "carol",
                "email": "carol@example.org",
                "name": "Carol",
                "password": "carol" + "-pw-2026",
                "invite_code": code,
            },
        ).status_code
        == 200
    )
    assert (
        admin_client.post(
            "/api/auth/register",
            json={
                "username": "dave",
                "email": "dave@example.org",
                "name": "Dave",
                "password": "dave" + "-pw-2026",
                "invite_code": "wrong",
            },
        ).status_code
        == 403
    )


def test_closed_mode_rejects_registration(admin_client):
    _login(admin_client, "alice", "alicepw")
    _set_mode(admin_client, "closed")
    assert (
        admin_client.post(
            "/api/auth/register",
            json={
                "username": "carol",
                "email": "carol@example.org",
                "name": "Carol",
                "password": "carol" + "-pw-2026",
            },
        ).status_code
        == 403
    )


def test_registration_status_is_public_and_hides_the_code(admin_client, client):
    _login(admin_client, "alice", "alicepw")
    _set_mode(admin_client, "invite")
    # A brand-new (anonymous) client can read the mode, and never an invitation code.
    body = client.get("/api/auth/registration-status").json()
    assert body == {
        "mode": "invite",
        "first_user": False,
        "session_days": 30,
        "email_codes": False,
        "password_reset": False,
        "front_door_url": None,
        "tracker_urls": {"health": None, "wealth": None},
    }


# --- suspend ---------------------------------------------------------------


def test_suspend_blocks_login_and_an_active_session(admin_client):
    """A valid cookie stops working mid-session, not only at the next login.

    A second TestClient holds bob's session in its own cookie jar while alice
    acts on `admin_client`.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    bob = TestClient(app, headers={"Origin": "http://testserver"})
    _login(bob, "bob", "bobpw")
    assert bob.get("/api/auth/me").status_code == 200

    _login(admin_client, "alice", "alicepw")
    bob_id = _account_id(admin_client, "bob")
    assert admin_client.patch(f"{ADMIN}/accounts/{bob_id}", json={"suspended": True}).status_code == 200
    assert bob.get("/api/auth/me").status_code == 401
    # and it is a distinct 403 at the next login, not "wrong password"
    assert bob.post("/api/auth/login", json={"username": "bob", "password": "bobpw"}).status_code == 403

    assert admin_client.patch(f"{ADMIN}/accounts/{bob_id}", json={"suspended": False}).status_code == 200
    _login(bob, "bob", "bobpw")


# --- reset password --------------------------------------------------------


def test_admin_resets_a_password(admin_client, client):
    _bob_moves_over(admin_client)
    temporary = admin_client.post(f"{ADMIN}/accounts/{_account_id(admin_client, 'bob')}/reset-password").json()["password"]
    assert client.post("/api/auth/login", json={"username": "bob", "password": temporary}).status_code == 200
    assert client.post("/api/auth/login", json={"username": "bob", "password": "bobpw"}).status_code == 401


# --- delete ----------------------------------------------------------------


def test_delete_removes_the_account_and_its_data(admin_client):
    from app.core.accounts import purge
    from domain import database

    _bob_moves_over(admin_client)
    database.connect("bob").close()
    assert os.path.isdir(database.user_data_dir("bob"))

    bob_id = _account_id(admin_client, "bob")
    assert admin_client.delete(f"{ADMIN}/accounts/{bob_id}", params={"confirm": "nee"}).status_code == 422
    assert admin_client.delete(f"{ADMIN}/accounts/{bob_id}", params={"confirm": "bob"}).status_code == 200
    purge()  # what the sweep does within a minute

    assert {a["username"] for a in admin_client.get(f"{ADMIN}/accounts").json()} == {"alice"}
    assert not os.path.exists(database.user_data_dir("bob"))
    assert admin_client.post("/api/auth/login", json={"username": "bob", "password": "bobpw"}).status_code == 401


# --- beta features ---------------------------------------------------------


def test_beta_features_grant_and_revoke(admin_client):
    _bob_moves_over(admin_client)
    bob_id = _account_id(admin_client, "bob")

    assert (
        admin_client.patch(f"/api/admin/tracker/betas/{bob_id}", json={"feature": "rebalancing", "enabled": True})
        .json()["betas"]
        .count("rebalancing")
        == 1
    )
    _login(admin_client, "bob", "bobpw")
    assert admin_client.get("/api/rebalancing/allocation").status_code == 200

    _login(admin_client, "alice", "alicepw")
    admin_client.patch(f"/api/admin/tracker/betas/{bob_id}", json={"feature": "rebalancing", "enabled": False})
    _login(admin_client, "bob", "bobpw")
    assert admin_client.get("/api/rebalancing/allocation").status_code == 403


def test_an_admin_reaches_a_beta_tab_without_being_granted_it(admin_client):
    """admins qualify for everything."""
    _login(admin_client, "alice", "alicepw")
    assert admin_client.get("/api/rebalancing/allocation").status_code == 200


def test_signup_on_wealth_tracker_gets_money_at_once(admin_client):
    """wealth-tracker is all Money: an account made there must not land on empty pages."""
    _login(admin_client, "alice", "alicepw")
    _set_mode(admin_client, "open")
    assert (
        admin_client.post(
            "/api/auth/register",
            json={
                "username": "carol",
                "email": "carol@example.org",
                "name": "Carol",
                "password": "carol" + "-pw-2026",
                "app": "money",
            },
        ).status_code
        == 200
    )
    assert "money" in admin_client.get("/api/auth/me").json()["beta_features"]

    assert (
        admin_client.post(
            "/api/auth/register",
            json={
                "username": "dave",
                "email": "dave@example.org",
                "name": "Dave",
                "password": "dave" + "-pw-2026",
            },
        ).status_code
        == 200
    )
    assert "money" not in admin_client.get("/api/auth/me").json()["beta_features"]


def test_password_policy_errors_carry_a_code(admin_client, client):
    _login(admin_client, "alice", "alicepw")
    _set_mode(admin_client, "open")
    r = client.post(
        "/api/auth/register",
        json={"username": "erin", "email": "erin@example.org", "name": "Erin", "password": "iloveyou12"},
        headers={"X-Locale": "en"},
    )
    assert r.status_code == 422 and r.json()["code"] == "password_too_common"
    assert "common" in r.json()["detail"]
    r = client.post(
        "/api/auth/register",
        json={"username": "erin", "email": "erin@example.org", "name": "Erin", "password": "kort"},
        headers={"X-Locale": "nl"},
    )
    assert r.json()["detail"] == "Kies een wachtwoord van minstens 10 tekens."
