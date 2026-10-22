"""Two-step login with an authenticator app (the shared account: packages/accounts)."""

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from tests.test_api import PASSWORD, engine, login, make_settings  # noqa: F401  (engine is a fixture)
from trackerai_accounts import totp


@pytest.fixture
def app(engine, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "Q0FGRUJBQkVDQUZFQkFCRUNBRkVCQUJFQ0FGRUJBQkU=")
    return create_app(engine=engine, settings=make_settings())


def enable(c):
    setup = c.post("/api/account/totp/setup").json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/trackerai%3Aalice?")  # one entry for every tracker
    secret = setup["secret"]
    assert c.post("/api/account/totp/enable", json={"code": "000000"}).json()["code"] == "totp_invalid"
    r = c.post("/api/account/totp/enable", json={"code": totp.code_at(secret)})
    assert r.status_code == 200
    return secret, r.json()["backup_codes"]


def test_enable_login_with_code_and_replay_refused(app, engine):  # noqa: F811
    c = TestClient(app)
    other = TestClient(app)
    login(c)
    login(other)
    secret, backup = enable(c)
    assert len(backup) == 10
    assert c.get("/api/me").json()["totp_enabled"] is True  # this browser stays logged in
    assert other.get("/api/me").status_code == 401  # every other session ends
    assert "totp_secret" not in c.get("/api/trackerai/admin/accounts").json()[0]  # the secret never leaves the server again
    stored = app.state.accounts.by_username("alice")["totp_secret"]
    assert stored.startswith("k1:") and secret not in stored  # encrypted, in the shared accounts

    fresh = TestClient(app)
    r = login(fresh)
    assert r.status_code == 401 and r.json()["code"] == "totp_required" and "set-cookie" not in r.headers
    r = fresh.post("/api/login", json={"username": "alice", "password": PASSWORD, "totp": "123456"})
    assert r.json()["code"] in ("totp_invalid",)
    # the code that enabled it was used already: the next step's code works, once
    step = app.state.accounts.by_username("alice")["totp_last_step"]
    code = totp.hotp(secret, step + 1)
    import time

    t = (step + 1) * 30 + 1
    real = time.time
    time.time = lambda: t
    try:
        assert fresh.post("/api/login", json={"username": "alice", "password": PASSWORD, "totp": code}).status_code == 200
        again = TestClient(app).post("/api/login", json={"username": "alice", "password": PASSWORD, "totp": code})
        assert again.status_code == 401 and again.json()["code"] == "totp_invalid"
    finally:
        time.time = real


def test_backup_code_logs_in_once_and_disable_needs_password_and_code(app):
    c = TestClient(app)
    login(c)
    secret, backup = enable(c)
    b = TestClient(app)
    assert b.post("/api/login", json={"username": "alice", "password": PASSWORD, "totp": backup[0]}).status_code == 200
    assert TestClient(app).post("/api/login", json={"username": "alice", "password": PASSWORD, "totp": backup[0]}).status_code == 401
    assert b.post("/api/account/totp/disable", json={"password": "wrong-password", "code": backup[1]}).status_code == 403
    assert b.post("/api/account/totp/disable", json={"password": PASSWORD, "code": "nope"}).json()["code"] == "totp_invalid"
    assert b.post("/api/account/totp/disable", json={"password": PASSWORD, "code": backup[1]}).status_code == 200
    assert login(TestClient(app)).status_code == 200  # the password alone again
    assert b.get("/api/me").json()["totp_enabled"] is False


def test_admin_can_turn_it_off_for_a_user_who_lost_the_phone(app, engine):  # noqa: F811
    admin = TestClient(app)
    login(admin)
    admin.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    anna = TestClient(app)
    anna.post("/api/register", json={"username": "anna", "email": "anna@example.org", "password": "anna-wachtwoord-1", "consent": True})
    setup = anna.post("/api/account/totp/setup").json()
    anna.post("/api/account/totp/enable", json={"code": totp.code_at(setup["secret"])})
    aid = app.state.accounts.by_username("anna")["id"]
    assert admin.delete(f"/api/trackerai/admin/accounts/{aid}/totp").status_code == 200
    assert anna.get("/api/me").status_code == 401
    assert TestClient(app).post("/api/login", json={"username": "anna", "password": "anna-wachtwoord-1"}).status_code == 200
    assert anna.delete(f"/api/trackerai/admin/accounts/{aid}/totp").status_code in (401, 403)


def test_agents_cannot_manage_two_step_login(app, engine):  # noqa: F811
    c = TestClient(app)
    login(c)
    tok = c.post("/api/agent-tokens", json={"name": "x"}).json()["token"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {tok}"})
    assert agent.post("/api/account/totp/setup").status_code == 401  # a site login only: a token is no session
