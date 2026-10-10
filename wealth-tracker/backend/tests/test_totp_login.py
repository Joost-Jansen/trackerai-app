"""S14: two-step login (TOTP) with backup codes, a setting of the shared trackerai account (packages/accounts)."""

import yaml
from trackerai_accounts import totp

from app.core import config


def _login(client, pw="alicepw", code=None):
    body = {"username": "alice", "password": pw}
    if code is not None:
        body["totp"] = code
    return client.post("/api/auth/login", json=body)


def _enable(client):
    assert _login(client).status_code == 200
    r = client.post("/api/account/totp/setup", json={"issuer": "wealth-tracker"})
    assert r.status_code == 200
    secret = r.json()["secret"]
    assert r.json()["otpauth_uri"].startswith("otpauth://totp/trackerai%3Aalice?")  # one entry for every tracker
    assert client.post("/api/account/totp/enable", json={"code": "000000"}).status_code == 422
    r = client.post("/api/account/totp/enable", json={"code": totp.code_at(secret)})
    assert r.status_code == 200
    return secret, r.json()["backup_codes"]


def test_the_secret_is_stored_encrypted(client, _accounts):
    secret, codes = _enable(client)
    raw = open(config.AUTH_CONFIG_PATH).read()
    assert secret not in raw and codes[0] not in raw and "totp" not in yaml.safe_load(raw)["credentials"]["usernames"]["alice"]
    stored = _accounts.by_username("alice")["totp_secret"]
    assert stored.startswith("k1:") and secret not in stored
    assert client.get("/api/auth/me").json()["totp_enabled"] is True


def test_login_asks_for_the_code_and_refuses_replay(client, _accounts):
    secret, _ = _enable(client)
    client.post("/api/auth/logout")
    client.cookies.clear()
    r = _login(client)
    assert r.status_code == 401 and r.json()["code"] == "totp_required"
    r = _login(client, code="123456")
    assert r.status_code == 401 and r.json()["code"] == "totp_invalid"
    # A wrong password never reveals that a code is needed.
    assert _login(client, pw="wrong", code="").json()["code"] == "bad_credentials"
    # The code used to enable cannot be replayed (by its step, not the clock: a test can cross a 30 s boundary).
    last = _accounts.by_username("alice")["totp_last_step"]
    assert _login(client, code=totp.hotp(secret, last)).json().get("code") == "totp_invalid"
    nxt = totp.hotp(secret, last + 1)
    assert _login(client, code=nxt).status_code == 200
    client.cookies.clear()
    assert _login(client, code=nxt).status_code == 401  # same code twice


def test_backup_codes_work_once(client):
    _, codes = _enable(client)
    client.cookies.clear()
    assert _login(client, code=codes[0].upper()).status_code == 200
    client.cookies.clear()
    assert _login(client, code=codes[0]).status_code == 401
    assert client.get("/api/account/totp").status_code == 401  # not logged in
    assert _login(client, code=codes[1]).status_code == 200
    status = client.get("/api/account/totp").json()
    assert {k: status[k] for k in ("enabled", "required", "backup_codes_left")} == {"enabled": True, "required": False, "backup_codes_left": 8}


def test_disable_needs_password_and_code(client):
    secret, codes = _enable(client)
    assert client.post("/api/account/totp/disable", json={"password": "wrong", "code": codes[0]}).status_code == 403
    r = client.post("/api/account/totp/disable", json={"password": "alicepw", "code": "111111"})
    assert r.status_code == 401
    assert client.post("/api/account/totp/disable", json={"password": "alicepw", "code": codes[1]}).status_code == 200
    client.cookies.clear()
    assert _login(client).status_code == 200


def test_delete_account_needs_the_code_too(client):
    _, codes = _enable(client)
    r = client.request("DELETE", "/api/account", json={"password": "alicepw"})
    assert r.status_code == 401 and r.json()["code"] == "totp_required"
    assert client.request("DELETE", "/api/account", json={"password": "alicepw", "totp": codes[0]}).status_code == 200


def test_admin_reset_turns_two_step_off(client, _accounts):
    _enable(client)
    cfg = yaml.safe_load(open(config.AUTH_CONFIG_PATH))
    cfg["admins"] = ["bob"]
    open(config.AUTH_CONFIG_PATH, "w").write(yaml.safe_dump(cfg))
    from fastapi.testclient import TestClient

    admin = TestClient(client.app, headers={"Origin": "http://testserver"})
    assert admin.post("/api/auth/login", json={"username": "bob", "password": "bobpw"}).status_code == 200
    from app.core.accounts import accounts

    assert admin.delete(f"/api/trackerai/admin/accounts/{accounts.by_username('alice')['id']}/totp").status_code == 200
    client.cookies.clear()
    assert _login(client).status_code == 200  # the password alone again
