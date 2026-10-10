"""
Guarding the login door itself, rather than what is behind it.

Three properties, each of which was missing and each of which fails silently if
it regresses — nothing about the app looks broken when the limiter stops
counting or when an old cookie keeps working, which is exactly why they are
pinned here:

  * password guessing is bounded (per account and per source),
  * an unknown username costs the same time as a real one, so response latency
    does not disclose which accounts exist,
  * changing a password retires the sessions that existed before it.
"""

import time

import pytest
import yaml

from app.core import auth_store, config, security


def _login(client, user="alice", pw="alicepw"):
    return client.post("/api/auth/login", json={"username": user, "password": pw})


# --- Rate limiting -------------------------------------------------------


def test_repeated_wrong_passwords_are_eventually_refused(client):
    """The behaviour that was missing entirely: guessing used to be unbounded."""
    seen = [_login(client, pw=f"wrong-{i}").status_code for i in range(15)]
    assert 401 in seen, "early attempts should still be answered normally"
    assert 429 in seen, "guessing must stop being answered at some point"
    # And the refusal sticks: the correct password does not slip through after.
    assert _login(client).status_code == 429


def test_the_limit_is_per_account_not_global(client):
    """One account being hammered must not lock a different one out."""
    for i in range(12):
        _login(client, user="alice", pw=f"wrong-{i}")
    assert _login(client, user="alice").status_code == 429
    assert _login(client, user="bob", pw="bobpw").status_code == 200


def test_normal_use_is_never_throttled(client):
    """A few fat-fingered attempts followed by the right one must work."""
    for _ in range(3):
        assert _login(client, pw="oops").status_code == 401
    assert _login(client).status_code == 200


def test_a_blocked_attempt_does_not_reach_bcrypt(client, monkeypatch):
    """The point of refusing early is to stop spending CPU, not just to say no.

    If the check ran after the password comparison, an attacker would still get
    the ~240ms of bcrypt per request that makes this a denial-of-service lever
    on the Pi.
    """
    for i in range(12):
        _login(client, pw=f"wrong-{i}")

    calls = []
    real = security.verify_password
    monkeypatch.setattr(
        security, "verify_password", lambda *a, **k: (calls.append(1), real(*a, **k))[1]
    )
    assert _login(client, pw="another-guess").status_code == 429
    assert calls == [], "a throttled request must not hash anything"


# --- Timing oracle -------------------------------------------------------


def test_an_unknown_username_still_costs_a_hash(monkeypatch, tmp_path):
    """Unknown usernames used to skip bcrypt, so latency alone leaked which
    accounts exist (~236ms vs ~0.3ms). Asserted by counting hashes rather than
    by timing, which would be flaky on a loaded CI box."""
    path = tmp_path / "auth_config.yaml"
    path.write_text(
        yaml.safe_dump({
            "cookie": {"name": "c", "key": "k", "expiry_days": 30},
            "credentials": {"usernames": {
                "alice": {"name": "Alice", "password": security.hash_password("alicepw")},
            }},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "AUTH_CONFIG_PATH", str(path))

    calls = []
    real = security.verify_password
    monkeypatch.setattr(
        auth_store.security, "verify_password",
        lambda *a, **k: (calls.append(1), real(*a, **k))[1],
    )

    assert auth_store.verify_credentials("nobody-at-all", "guess") is None
    assert len(calls) == 1, "an unknown username must still pay for one hash"

    calls.clear()
    assert auth_store.verify_credentials("alice", "wrong") is None
    assert len(calls) == 1, "a real username costs the same one hash"


def test_the_placeholder_hash_is_not_a_usable_password(client):
    """The constant-time filler must never authenticate anybody.

    Takes `client` for the accounts it sets up, not for the HTTP calls: this
    needs a config on disk to load, and asking for one that exists is what
    keeps the assertion about the placeholder rather than about the config.
    """
    assert auth_store.verify_credentials("nobody", "absent-user-constant-time-placeholder") is None


# --- Session invalidation ------------------------------------------------


def test_changing_your_password_signs_out_other_sessions(client):
    """The cookie a thief copied must stop working once the password changes."""
    assert _login(client).status_code == 200
    stolen = dict(client.cookies)
    assert client.get("/api/auth/me", cookies=stolen).status_code == 200

    # Second (must be a later whole second than the login: `iat` and
    # `pw_changed_at` are both unix seconds).
    time.sleep(1.1)
    assert client.post(
        "/api/auth/change-password",
        json={"current_password": "alicepw", "new_password": "brand-new-pw"},
    ).status_code == 200

    assert client.get("/api/auth/me", cookies=stolen).status_code == 401


def test_the_session_that_changed_the_password_stays_signed_in(client):
    """Changing your password must not log *you* out — the response carries a
    fresh cookie minted after the change."""
    assert _login(client).status_code == 200
    time.sleep(1.1)
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": "alicepw", "new_password": "brand-new-pw"},
    )
    assert r.status_code == 200
    # The client keeps the Set-Cookie from that response, so this is the reissued one.
    assert client.get("/api/auth/me").status_code == 200


def test_an_admin_reset_signs_the_target_out_everywhere(client, tmp_path):
    """The action taken when an account is believed compromised has to actually
    evict whoever is in it."""
    path = config.AUTH_CONFIG_PATH
    cfg = yaml.safe_load(open(path))
    cfg["admins"] = ["bob"]
    yaml.safe_dump(cfg, open(path, "w"))

    assert _login(client).status_code == 200
    alice_cookie = dict(client.cookies)
    assert client.get("/api/auth/me", cookies=alice_cookie).status_code == 200

    time.sleep(1.1)
    client.cookies.clear()
    assert _login(client, user="bob", pw="bobpw").status_code == 200
    from app.core.accounts import accounts

    alice = accounts.by_username("alice")["id"]
    assert client.post(f"/api/trackerai/admin/accounts/{alice}/reset-password").status_code == 200

    assert client.get("/api/auth/me", cookies=alice_cookie).status_code == 401


def test_an_account_without_the_new_field_still_works(client):
    """Configs written before this existed have no `pw_changed_at`; every token
    must stay valid rather than everyone being logged out on deploy."""
    path = config.AUTH_CONFIG_PATH
    cfg = yaml.safe_load(open(path))
    assert "pw_changed_at" not in cfg["credentials"]["usernames"]["alice"]
    assert _login(client).status_code == 200
    assert client.get("/api/auth/me").status_code == 200


# --- Capitalisation ------------------------------------------------------
#
# A username differing only in case used to be a *different* account, with its
# own data/users/ folder. Two accounts for the same person came into being that
# way, and the second one looks exactly like "my portfolio is empty".


def test_capitalisation_does_not_change_which_account_you_reach(client):
    assert _login(client, user="ALICE").status_code == 200
    # The session must carry the stored spelling: every per-user path is built
    # from it, so "ALICE" reading alice's data is the whole point.
    assert client.get("/api/auth/me").json()["username"] == "alice"


def test_a_wrong_password_is_still_wrong_in_any_capitalisation(client):
    assert _login(client, user="Alice", pw="nope").status_code == 401


def test_the_guessing_limit_is_not_reset_by_changing_capitals(client):
    """Otherwise each spelling of a name buys a fresh budget of attempts."""
    spellings = ["alice", "Alice", "ALICE", "aLiCe"]
    seen = [
        _login(client, user=spellings[i % len(spellings)], pw=f"wrong-{i}").status_code
        for i in range(15)
    ]
    assert 429 in seen


def test_signing_up_cannot_duplicate_an_existing_name_in_other_capitals(client, tmp_path, monkeypatch):
    cfg = yaml.safe_load(open(config.AUTH_CONFIG_PATH, encoding="utf-8"))
    cfg["registration_mode"] = "open"
    open(config.AUTH_CONFIG_PATH, "w", encoding="utf-8").write(yaml.safe_dump(cfg))

    response = client.post("/api/auth/register", json={
        "username": "Alice", "email": "Alice@example.org", "name": "Alice again", "password": "another-pw", "invite_code": "",
    })
    assert response.status_code == 409 and response.json()["code"] == "username_taken"
    assert "bezet" in response.json()["detail"].lower()  # Dutch: no X-Locale header
