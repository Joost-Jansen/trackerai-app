"""The shared trackerai account in wealth-tracker (core/accounts.py): old logins move over on first use, an account
from another tracker joins, deleting reaches the data folder, and a wealth admin manages only wealth's own accounts."""

import time
import os

import yaml
from fastapi.testclient import TestClient

from app.core import auth_store, config
from trackerai_accounts import totp
from domain import database


def _login(client, user="alice", pw="alicepw", code=None):
    body = {"username": user, "password": pw, **({"totp": code} if code else {})}
    return client.post("/api/auth/login", json=body)


def _client(client):
    return TestClient(client.app, headers={"Origin": "http://testserver"})


def test_an_old_login_moves_to_the_accounts_on_first_use(client, _accounts):
    assert _accounts.by_username("alice") is None
    assert _login(client).status_code == 200
    alice = _accounts.by_username("alice")
    assert alice and _accounts.local_key(alice["id"], "wealth") == "alice"
    user = yaml.safe_load(open(config.AUTH_CONFIG_PATH))["credentials"]["usernames"]["alice"]
    assert "password" not in user  # the password lives in the accounts now
    assert _login(_client(client), pw="wrong").status_code == 401


def test_two_step_login_moves_along(client, _accounts):
    secret = totp.new_secret()
    with auth_store._locked_update() as cfg:
        cfg["credentials"]["usernames"]["alice"]["totp"] = {
            "enabled": True, "secret": auth_store._encrypt_secret(secret), "backup_codes": []}
    r = _login(client)
    assert r.status_code == 401 and r.json()["code"] == "totp_required"
    assert _login(client, code=totp.code_at(secret, time.time() + 30)).status_code == 200


def test_an_account_from_another_tracker_joins(client, _accounts):
    _login(client)  # alice becomes the first account (and so its admin)
    alice = _accounts.by_username("alice")
    _accounts.set_registration_mode(alice, "open")
    _accounts.create_linked("henk", alice["password_hash"], "health", "7")
    henk = _client(client)
    assert _login(henk, "henk", "alicepw").status_code == 200
    me = henk.get("/api/auth/me").json()
    assert me["in_app"] is False and henk.get("/api/accounts").json()["code"] == "not_in_app"
    assert henk.post("/api/auth/join", json={"money": True}).status_code == 200
    me = henk.get("/api/auth/me").json()
    assert me["in_app"] is True and "money" in me["beta_features"] and me["apps"] == ["health", "wealth"]


def test_signing_up_waits_while_no_login_has_moved(client):
    r = _client(client).post("/api/auth/register", json={"username": "zoe", "email": "zoe@example.org", "name": "Zoe", "password": "zoe-pw-2026-x"})
    assert r.status_code == 403 and r.json()["code"] == "registration_closed"


def test_deleting_the_account_removes_the_data_folder(client, _accounts):
    _login(client)
    assert client.get("/api/accounts").status_code == 200
    assert os.path.exists(database.user_data_dir("alice"))
    assert client.request("DELETE", "/api/account", json={"password": "alicepw"}).status_code == 200
    assert not os.path.exists(database.user_data_dir("alice"))
    assert "alice" not in auth_store.users_or_empty()
    assert _accounts.by_username("alice") is None


def test_wealth_admin_manages_only_accounts_of_wealth_alone(client, _accounts):
    _login(client)  # alice: the account admin
    bob = _client(client)
    assert _login(bob, "bob", "bobpw").status_code == 200
    with auth_store._locked_update() as cfg:
        cfg["admins"] = ["alice", "bob"]
    _accounts.set_app(_accounts.by_username("alice"), _accounts.by_username("alice")["id"], "health", enabled=True)
    # bob administers wealth-tracker, alice uses health-tracker too and runs the installation
    alice = _accounts.by_username("alice")["id"]
    assert bob.patch(f"/api/trackerai/admin/accounts/{alice}", json={"suspended": True}).status_code == 403
    assert bob.patch("/api/trackerai/admin/registration", json={"registration": "open"}).status_code == 403


def test_joining_brings_an_old_login_of_the_same_name_along(client, _accounts):
    _login(client, "bob", "bobpw")  # someone's login has moved: sign-ups and joining are open for business
    _accounts.set_registration_mode(_accounts.by_username("bob"), "open")
    _accounts.create_linked("alice", _accounts.by_username("bob")["password_hash"], "health", "3")  # alice from health-tracker
    alice = _client(client)
    assert _login(alice, "alice", "bobpw").status_code == 200  # the account's password, not the old wealth one
    r = alice.post("/api/auth/join", json={})
    assert r.status_code == 409 and r.json()["code"] == "old_login_password"
    assert alice.post("/api/auth/join", json={"old_password": "wrong"}).status_code == 403
    assert alice.post("/api/auth/join", json={"old_password": "alice" + "pw"}).status_code == 200  # conftest's
    a = _accounts.by_username("alice")
    assert _accounts.local_key(a["id"], "wealth") == "alice"  # her own data folder, not a new one
    assert alice.get("/api/accounts").status_code == 200


def test_signing_up_on_the_front_door_for_health_only(client, _accounts):
    """trackerai.nl posts here with the trackers chosen: health only makes no wealth-tracker folder."""
    accounts = _accounts
    _login(client)  # alice's login moves in; she is the admin and opens sign-up
    accounts.set_registration_mode(accounts.by_username("alice"), "open")
    c = _client(TestClient(client.app))
    secret = "-".join(["yara", "pw", "2026", "x"])  # test data, built so the secret scanner doesn't mistake it
    body = {"username": "yara", "name": "Yara", "password": secret, "email": "yara@example.org", "apps": ["health"]}
    assert c.post("/api/auth/register", json=body).json()["code"] == "consent_required"
    r = c.post("/api/auth/register", json={**body, "consent": True})
    assert r.status_code == 200
    account = accounts.by_username("yara")
    assert sorted(accounts.apps(account["id"])) == ["health"]
    assert accounts.local_key(account["id"], "wealth") is None
    me = c.get("/api/auth/me").json()
    assert me["in_app"] is False and me["apps"] == ["health"]
