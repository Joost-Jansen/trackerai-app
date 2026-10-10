"""S11: sessions last 30 days with "stay logged in" and are renewed while in use: the shared trackerai session (packages/accounts)."""

import time

import jwt
from trackerai_accounts.session import COOKIE

from app.core import security

SECRET = "s" * 40  # the session secret of the tests' accounts (conftest.py)


def _cookie(client):
    return client.cookies.get(COOKIE)


def _set(client, token):
    client.cookies.clear()
    client.cookies.set(COOKIE, token)


def _from_response(r):
    raw = r.headers["set-cookie"]
    return raw.split(COOKIE + "=", 1)[1].split(";", 1)[0]


def _alice(client) -> int:
    """alice's account (her login moves to the accounts on the first one)."""
    client.post("/api/auth/login", json={"username": "alice", "password": "alice" + "pw"})  # the conftest fixture's
    return int(jwt.decode(_cookie(client), SECRET, algorithms=["HS256"])["sub"][2:])


def _token(account_id: int, iat: int, auth: int, days: int = 30, sv: int = 0) -> str:
    return jwt.encode({"sub": f"a:{account_id}", "sv": sv, "iat": iat, "exp": iat + days * 86400, "auth": auth}, SECRET, algorithm="HS256")


def test_login_issues_a_30_day_cookie(client):
    r = client.post("/api/auth/login", json={"username": "alice", "password": "alicepw"})
    assert "Max-Age=2592000" in r.headers["set-cookie"]
    claims = jwt.decode(_cookie(client), SECRET, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == 30 * 86400
    assert claims["auth"] == claims["iat"]


def test_a_fresh_cookie_is_not_renewed(client):
    client.post("/api/auth/login", json={"username": "alice", "password": "alicepw"})
    r = client.get("/api/auth/me")
    assert r.status_code == 200 and "set-cookie" not in r.headers


def test_an_older_cookie_is_renewed_on_use(client):
    aid, now = _alice(client), int(time.time())
    _set(client, _token(aid, now - 3 * 86400, now - 10 * 86400))
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert COOKIE in r.headers["set-cookie"]
    claims = jwt.decode(_from_response(r), SECRET, algorithms=["HS256"])
    assert claims["iat"] >= now and claims["exp"] >= now + 30 * 86400 - 5
    assert claims["auth"] == now - 10 * 86400  # the moment of the password is kept


def test_no_renewal_beyond_the_maximum(client):
    aid, now = _alice(client), int(time.time())
    _set(client, _token(aid, now - 3 * 86400, now - 91 * 86400))
    r = client.get("/api/auth/me")
    assert r.status_code == 200 and "set-cookie" not in r.headers


def test_an_expired_cookie_is_refused(client):
    aid, now = _alice(client), int(time.time())
    _set(client, _token(aid, now - 31 * 86400, now - 31 * 86400))
    assert client.get("/api/auth/me").status_code == 401


def test_a_renewed_cookie_still_dies_with_a_password_change(client):
    aid, now = _alice(client), int(time.time())
    old = _token(aid, now - 3 * 86400, now - 3 * 86400)
    _set(client, old)
    r = client.post("/api/auth/change-password", json={"current_password": "alicepw", "new_password": "a-new-pass-2026"})
    assert r.status_code == 200
    _set(client, old)
    assert client.get("/api/auth/me").status_code == 401


def test_without_stay_logged_in_a_password_change_keeps_a_browser_session(client):
    r = client.post("/api/auth/login", json={"username": "alice", "password": "alice" + "pw", "remember": False})
    assert r.status_code == 200 and "max-age" not in r.headers["set-cookie"].lower()
    r = client.post("/api/auth/change-password", json={"current_password": "alice" + "pw", "new_password": "a-new-pass-2026"})
    assert r.status_code == 200 and "max-age" not in r.headers["set-cookie"].lower()


def test_an_empty_signing_key_is_never_accepted():
    token = jwt.encode({"sub": "alice", "iat": 1, "exp": 2**31}, "some-key-value!!", algorithm="HS256")
    assert security.decode_access_claims(token, "") is None
