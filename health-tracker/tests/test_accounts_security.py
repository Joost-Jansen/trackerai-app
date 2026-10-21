"""Logins and sessions for an install other people use: per-IP limits behind trusted proxies, sessions that end on a
password change and renew while in use, MCP only with tokens, secrets required in production (api/users.py,
api/main.py, api/mcp.py)."""

import time

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from trackerai_accounts import Config, crypto, session as account_session

from api import auth
from api.main import Settings, check_production_secrets, create_app
from tests.test_api import PASSWORD, engine, login, make_settings  # noqa: F401  (engine is a fixture)
from tools import db, secretbox
from trackerai_testing import new_database_url

PROXY = ("172.18.0.3", 40000)  # Caddy on the docker network


@pytest.fixture
def app(engine, tmp_path):  # noqa: F811
    return create_app(engine=engine, settings=make_settings(trusted_proxies="172.18.0.0/16"))


def via_proxy(app, ip):
    return TestClient(app, client=PROXY, headers={"CF-Connecting-IP": ip})


def test_login_is_limited_per_ip_behind_the_proxy(app):
    attacker = via_proxy(app, "198.51.100.1")
    for i in range(30):  # many usernames, so the per-username limit never trips
        assert login(attacker, user=f"user{i}", password="wrong-password").status_code == 401
    assert login(attacker).status_code == 429  # even the right password: this IP is out for a while
    assert login(via_proxy(app, "198.51.100.2")).status_code == 200  # someone else behind the same tunnel is not


def test_forged_forwarding_headers_from_an_untrusted_peer_are_ignored(app):
    for i in range(30):
        c = TestClient(app, client=("203.0.113.5", 1234), headers={"CF-Connecting-IP": f"10.9.{i}.1", "X-Forwarded-For": f"10.8.{i}.1"})
        login(c, user=f"user{i}", password="wrong-password")
    assert login(TestClient(app, client=("203.0.113.5", 1234), headers={"CF-Connecting-IP": "10.7.7.7"})).status_code == 429


def test_registration_is_limited_per_ip(app):
    c = via_proxy(app, "198.51.100.9")
    codes = [c.post("/api/register", json={"username": f"new{i}", "email": f"new{i}@example.org", "password": "paars-fiets-tegel-7"}).status_code for i in range(6)]
    assert codes[:5] == [403] * 5 and codes[5] == 429  # registration is closed, but every attempt counts (invite guessing)


def test_unknown_user_costs_a_full_password_check():
    assert auth.verify_password("anything", None) is False
    started = time.perf_counter()
    auth.verify_password("anything", None)
    assert time.perf_counter() - started > 0.05  # bcrypt at cost 12, not an early return


def test_new_passwords_follow_the_policy(app):
    c = TestClient(app)
    login(c)
    r = c.post("/api/account/password", json={"current": PASSWORD, "new": "password123"})
    assert r.status_code == 422 and r.json()["code"] == "password_too_common"
    assert c.post("/api/account/password", json={"current": PASSWORD, "new": "alice"}).json()["code"] == "password_too_short"


def test_password_change_ends_other_sessions_but_not_this_one(app):
    phone, laptop = TestClient(app), TestClient(app)
    login(phone)
    login(laptop)
    assert laptop.post("/api/account/password", json={"current": PASSWORD, "new": "nieuw-wachtwoord-99"}).status_code == 200
    assert laptop.get("/api/me").status_code == 200
    assert phone.get("/api/me").status_code == 401


def test_admin_reset_ends_the_users_sessions(app):
    admin = TestClient(app)
    login(admin)
    admin.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    anna = TestClient(app)
    assert anna.post("/api/register", json={"username": "anna", "email": "anna@example.org", "password": "anna-wachtwoord-1", "consent": True}).status_code == 200
    admin.post(f"/api/trackerai/admin/accounts/{app.state.accounts.by_username('anna')['id']}/reset-password")
    assert anna.get("/api/me").status_code == 401


def test_session_lasts_30_days_and_renews_while_in_use(app):
    c = TestClient(app)
    r = login(c)
    assert "max-age=2592000" in r.headers["set-cookie"].lower()
    assert "set-cookie" not in c.get("/api/me").headers  # fresh: nothing to renew
    old = int(time.time()) - 3 * 86400
    secret = app.state.accounts.config.session_secret
    stale = jwt.encode({"sub": "a:1", "iat": old, "auth": old, "exp": old + 14 * 86400, "sv": 0}, secret, algorithm="HS256")
    c.cookies.clear()  # replace the login's cookie (httpx2 2.16 keeps both when only the value is set)
    c.cookies.set(account_session.COOKIE, stale)
    r = c.get("/api/me")
    assert r.status_code == 200 and "max-age=2592000" in r.headers["set-cookie"].lower()


def test_mcp_needs_a_token_not_a_cookie(app):
    c = TestClient(app)
    login(c)
    r = c.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_agent_token"


def test_failed_mcp_tokens_are_limited_per_ip(app):
    c = via_proxy(app, "198.51.100.20")
    for i in range(20):
        assert c.post(f"/api/mcp/tr_guess{i}", json={}).status_code == 401
    assert c.post("/api/mcp/tr_guess", json={}).status_code == 429
    assert c.get("/api/me", headers={"Authorization": "Bearer tr_x"}).status_code == 429  # same budget for the REST API


def test_production_needs_explicit_secrets(monkeypatch):
    monkeypatch.delenv("ALLOW_INSECURE_DEFAULTS", raising=False)
    for var in secretbox.KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    shared = Config(database_url="postgresql://never-connected/accounts", session_secret="s" * 40, encryption_key=crypto.new_key())
    good = Settings(jwt_secret="s" * 64, accounts=shared)
    with pytest.raises(RuntimeError, match="APP_ENCRYPTION_KEY"):
        check_production_secrets(good)
    with pytest.raises(RuntimeError, match="ACCOUNTS_SESSION_SECRET"):
        check_production_secrets(Settings(accounts=Config(database_url="postgresql://never-connected/accounts", session_secret="short", encryption_key=crypto.new_key())))
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "not-a-key")
    with pytest.raises(RuntimeError, match="valid"):
        check_production_secrets(good)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", secretbox.derived_key("s" * 64))  # the older name still works
    check_production_secrets(good)
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY")
    monkeypatch.setenv("ALLOW_INSECURE_DEFAULTS", "true")
    check_production_secrets(Settings(accounts=Config(database_url="", session_secret="", encryption_key="")))


def test_derived_key_helper_keeps_old_values_readable(monkeypatch, capsys):
    monkeypatch.setenv("TRAINING_JWT_SECRET", "old-secret")
    for var in secretbox.KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    stored = secretbox.encrypt("garmin-session", secretbox.default_key())  # what an install without a key stored
    assert secretbox.main(["--print-derived-key"]) == 0
    printed = capsys.readouterr().out.strip()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", printed)
    assert secretbox.decrypt(stored, secretbox.default_key()) == "garmin-session"


def test_schema_6_adds_the_user_columns_to_an_older_database():
    e = db.connect(new_database_url())
    with e.begin() as c:
        c.execute(text("CREATE TABLE users (id SERIAL PRIMARY KEY, username VARCHAR(40) NOT NULL UNIQUE, display_name VARCHAR(80), "
                       "password_hash VARCHAR(100) NOT NULL, is_admin BOOLEAN NOT NULL, suspended BOOLEAN NOT NULL, "
                       "created_at TIMESTAMP WITH TIME ZONE NOT NULL, last_login_at TIMESTAMP WITH TIME ZONE)"))
        c.execute(text("INSERT INTO users VALUES (1, 'joost', NULL, 'h', true, false, '2026-01-01 00:00:00+00', NULL)"))
    db.create_schema(e)
    u = db.get_user(e, 1)
    assert u["session_version"] == 0 and u["totp_enabled"] is False and u["consent_at"] is None  # existing users are not blocked
    assert db.bump_session_version(e, 1) == 1
    assert "totp_secret" not in u and "password_hash" not in u


def test_registration_needs_explicit_consent_and_records_it(app, engine, monkeypatch):  # noqa: F811
    monkeypatch.setenv("PRIVACY_CONTROLLER", "Joost Jansen")
    monkeypatch.setenv("PRIVACY_CONTACT", "privacy@example.org")
    admin = TestClient(app)
    login(admin)
    admin.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    c = TestClient(app)
    r = c.post("/api/register", json={"username": "anna", "email": "anna@example.org", "password": "anna-wachtwoord-1"})
    assert r.status_code == 422 and r.json()["code"] == "consent_required"
    assert c.post("/api/register", json={"username": "anna", "email": "anna@example.org", "password": "anna-wachtwoord-1", "consent": True}).status_code == 200
    assert c.get("/api/me").json()["id"]  # health-tracker's own user, made on the first visit, carries the consent
    row = db.get_user_by_name(engine, "anna")
    assert row["consent_at"] and row["privacy_version"]
    assert db.get_user(engine, 1)["consent_at"] is None and login(TestClient(app)).status_code == 200  # existing users are not blocked
    privacy = TestClient(app).get("/api/auth/config").json()["privacy"]
    assert privacy == {"controller": "Joost Jansen", "contact": "privacy@example.org", "version": row["privacy_version"]}
