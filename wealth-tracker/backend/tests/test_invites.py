"""
Invite links per person, made on the shared admin page (/api/trackerai/admin):
usable once, with an end date, revocable, and they work on this site's own
sign-up too.
"""

from datetime import UTC, datetime, timedelta, timezone

from fastapi.testclient import TestClient

ADMIN = "/api/trackerai/admin"


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _admin(client):
    from app.core import auth_store

    with auth_store._locked_update() as cfg:
        cfg["admins"] = ["alice"]
    _login(client)


def _register(code, username="carol"):
    from app.main import app

    return TestClient(app).post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.org",
            "name": username.title(),
            "password": f"{username}pw-123",
            "invite_code": code,
        },
    )


def test_an_invite_link_works_once(client, _accounts):
    _account_admin(client, _accounts)
    assert client.patch(f"{ADMIN}/registration", json={"registration": "invite"}).status_code == 200
    inv = client.post(f"{ADMIN}/invites", json={"days": 7, "apps": ["wealth"]}).json()
    assert len(inv["code"]) >= 10

    assert _register(inv["code"]).status_code in (200, 201)
    assert _register(inv["code"], "dave").status_code == 403  # used
    assert _register("nonsense", "erin").status_code == 403


def test_an_expired_or_revoked_invite_does_not_work(client, _accounts):
    from trackerai_accounts.store import invites

    _account_admin(client, _accounts)
    client.patch(f"{ADMIN}/registration", json={"registration": "invite"})
    old = client.post(f"{ADMIN}/invites", json={"days": 1, "apps": ["wealth"]}).json()
    with _accounts.engine.begin() as c:
        c.execute(invites.update().values(expires_at=datetime.now(UTC) - timedelta(hours=1)))
    assert _register(old["code"]).status_code == 403

    gone = client.post(f"{ADMIN}/invites", json={"days": 7, "apps": ["wealth"]}).json()
    assert client.delete(f"{ADMIN}/invites/{gone['code']}").status_code == 200
    assert _register(gone["code"]).status_code == 403


def test_invites_are_for_admins_only(client):
    _login(client, "bob", "bobpw")
    assert client.post(f"{ADMIN}/invites", json={"days": 7, "apps": ["wealth"]}).status_code == 403


def _account_admin(client, _accounts):
    """alice logged in as the administrator of every tracker (the one who makes invitations on trackerai.nl/admin)."""
    from sqlalchemy import update

    from trackerai_accounts.store import accounts as accounts_table

    _admin(client)
    with _accounts.engine.begin() as c:
        c.execute(update(accounts_table).where(accounts_table.c.username == "alice").values(is_admin=True))


def test_an_invite_from_the_trackerai_admin_page_signs_up_here(client, _accounts):
    """The shared admin page (trackerai.nl/admin, and the one in the app) makes invitations through the accounts'
    /api/trackerai/admin/invites; the link /register?invite=CODE brings the code to this site's sign-up."""
    _account_admin(client, _accounts)
    client.patch(f"{ADMIN}/registration", json={"registration": "invite"})
    r = client.post("/api/trackerai/admin/invites", json={"days": 7, "apps": ["wealth"]})
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    assert _register(code).status_code in (200, 201)
    assert _register(code, "dave").status_code == 403  # used
    assert sorted(_accounts.apps(_accounts.by_username("carol")["id"])) == ["wealth"]


def test_an_invite_for_health_too_asks_consent_here(client, _accounts):
    """An invitation that brings health-tracker along needs the consent for health data, also when used here."""
    _account_admin(client, _accounts)
    client.patch(f"{ADMIN}/registration", json={"registration": "invite"})
    code = client.post("/api/trackerai/admin/invites", json={"days": 7, "apps": ["wealth", "health"]}).json()["code"]
    r = _register(code)
    assert r.status_code == 422 and r.json()["code"] == "consent_required"
    from app.main import app

    r = TestClient(app).post(
        "/api/auth/register",
        json={
            "username": "carol",
            "email": "carol@example.org",
            "name": "Carol",
            "password": "carol" + "pw-123",
            "invite_code": code,
            "consent": True,
        },
    )
    assert r.status_code in (200, 201), r.text
    assert sorted(_accounts.apps(_accounts.by_username("carol")["id"])) == ["health", "wealth"]
