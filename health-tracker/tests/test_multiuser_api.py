import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from tests.test_api import PASSWORD, engine, login, make_settings  # noqa: F401  (engine is a fixture)
from tools import db

ANNA_PW = "anna-wachtwoord-1"


@pytest.fixture
def app(engine, tmp_path):  # noqa: F811
    return create_app(engine=engine, settings=make_settings())


def as_admin(app):
    c = TestClient(app)
    login(c)
    return c


def register(app, username="anna", password=ANNA_PW, **kw):
    c = TestClient(app)
    return c, c.post("/api/register", json={"username": username, "email": f"{username}@example.org", "password": password, "consent": True, **kw})


def test_first_env_user_is_admin_and_registration_is_closed(app):
    admin = as_admin(app)
    assert admin.get("/api/me").json()["is_admin"] is True
    assert TestClient(app).get("/api/auth/config").json() | {"privacy": None} == {"registration": "closed", "first_user": False, "privacy": None, "session_days": 30, "front_door_url": None}
    _, r = register(app)
    assert r.status_code == 403


def test_open_registration_and_data_isolation(app, engine):  # noqa: F811
    admin = as_admin(app)
    assert admin.patch("/api/trackerai/admin/registration", json={"registration": "open"}).json()["registration"] == "open"
    anna, r = register(app, display_name="Anna")
    assert r.status_code == 200 and r.json()["is_admin"] is False
    me = anna.get("/api/me").json()
    assert me["username"] == "anna" and me["display_name"] == "Anna"

    # Joost's run is not Anna's
    assert [a["name"] for a in admin.get("/api/activities").json()] == ["Ochtendloop"]
    aid = admin.get("/api/activities").json()[0]["id"]
    assert anna.get("/api/activities").json() == []
    assert anna.get(f"/api/activities/{aid}").status_code == 404
    assert anna.get("/api/heatmap").json() == {"tracks": []}
    assert anna.get("/api/dashboard").json()["recent"] == []

    # plans, log, docs: each their own
    pid = admin.post("/api/plans", json={"title": "Marathon", "sessions": [{"date": "2026-10-04", "sport": "run"}]}).json()["id"]
    assert anna.get(f"/api/plans/{pid}").status_code == 404
    assert anna.patch(f"/api/plans/{pid}", json={"status": "stopped"}).status_code == 404
    assert anna.put(f"/api/plans/{pid}/sessions", json=[]).status_code == 404
    assert anna.get("/api/plans/active").json()["plan"] is None
    admin.post("/api/entries", json={"kind": "log", "title": "Joost-log", "body": "b"})
    anna.post("/api/entries", json={"kind": "log", "title": "Anna-log", "body": "b"})
    assert [e["title"] for e in anna.get("/api/entries").json()] == ["Anna-log"]
    assert [e["author"] for e in anna.get("/api/entries").json()] == ["anna"]
    admin.put("/api/docs/goals", json={"body": "Marathon 3:45"})
    assert anna.get("/api/docs/goals").status_code == 404
    assert anna.get("/api/context").json()["goals"] is None

    # agent tokens act as their own user
    tok = anna.post("/api/agent-tokens", json={"name": "Claude"}).json()["token"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {tok}"})
    assert agent.get("/api/me").json()["username"] == "anna"
    assert agent.get("/api/activities").json() == []
    assert [t["name"] for t in admin.get("/api/agent-tokens").json()] == []
    mcp = agent.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_activities", "arguments": {}}}).json()
    assert "Ochtendloop" not in mcp["result"]["content"][0]["text"]


def test_invite_registration(app):
    admin = as_admin(app)
    admin.patch("/api/trackerai/admin/registration", json={"registration": "invite"})
    _, r = register(app)
    assert r.status_code == 403
    code = admin.post("/api/admin/invites", json={"days": 7}).json()["code"]
    _, r = register(app, invite=code)
    assert r.status_code == 200
    _, r = register(app, username="bob", invite=code)
    assert r.status_code == 403  # used
    invite = admin.get("/api/trackerai/admin/registration").json()["invites"][0]
    assert invite["code"] == code and invite["used_by"] is not None


def test_an_invite_from_the_trackerai_admin_page_signs_up_here(app):
    """The admin page on trackerai.nl (and in the app) makes invitations through the accounts' /api/trackerai/admin;
    the link /register/?invite=CODE brings that code to this site's sign-up (/api/register)."""
    admin = as_admin(app)
    admin.patch("/api/trackerai/admin/registration", json={"registration": "invite"})
    code = admin.post("/api/trackerai/admin/invites", json={"days": 7, "apps": ["health"]}).json()["code"]
    bob, r = register(app, username="bob", invite=code)
    assert r.status_code == 200, r.text
    assert bob.get("/api/me").json()["id"] is not None  # in health-tracker at once
    _, r = register(app, username="cleo", invite=code)
    assert r.status_code == 403 and r.json()["code"] == "invalid_invite"  # one use
    # an invitation for another tracker signs up here too, and brings that tracker along
    code = admin.post("/api/trackerai/admin/invites", json={"days": 7, "apps": ["wealth"]}).json()["code"]
    _, r = register(app, username="dora", invite=code)
    assert r.status_code == 200, r.text
    assert sorted(app.state.accounts.apps(app.state.accounts.by_username("dora")["id"])) == ["health", "wealth"]


def test_registration_rules(app):
    admin = as_admin(app)
    admin.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    assert register(app, username="a")[1].status_code == 422
    assert register(app, password="kort")[1].status_code == 422
    assert register(app, username="Alice")[1].status_code == 409
    assert admin.patch("/api/trackerai/admin/registration", json={"registration": "iedereen"}).status_code == 422


def test_admin_manages_users(app):
    """The account tools themselves are packages/accounts' (tested there); here: they reach health-tracker."""
    admin = as_admin(app)
    admin.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    anna, _ = register(app)
    anna_acc = app.state.accounts.by_username("anna")["id"]
    assert anna.get("/api/trackerai/admin/accounts").status_code == 403
    assert {a["username"] for a in admin.get("/api/trackerai/admin/accounts").json()} == {"alice", "anna"}

    # suspend: no more access, no login
    admin.patch(f"/api/trackerai/admin/accounts/{anna_acc}", json={"suspended": True})
    assert anna.get("/api/me").status_code == 401
    assert TestClient(app).post("/api/login", json={"username": "anna", "password": ANNA_PW}).status_code == 403
    admin.patch(f"/api/trackerai/admin/accounts/{anna_acc}", json={"suspended": False})

    # reset password: the temporary one works, the old one not
    temp = admin.post(f"/api/trackerai/admin/accounts/{anna_acc}/reset-password").json()["password"]
    assert TestClient(app).post("/api/login", json={"username": "anna", "password": ANNA_PW}).status_code == 401
    assert TestClient(app).post("/api/login", json={"username": "anna", "password": temp}).status_code == 200

    # delete needs the username typed, and takes health-tracker's part along
    assert admin.delete(f"/api/trackerai/admin/accounts/{anna_acc}?confirm=nee").status_code == 422
    assert admin.delete(f"/api/trackerai/admin/accounts/{anna_acc}?confirm=anna").status_code == 200
    app.state.purge()
    assert {a["username"] for a in admin.get("/api/trackerai/admin/accounts").json()} == {"alice"}
    assert [u["username"] for u in db.list_users(app.state.engine)] == ["alice"]


def test_account_password_change(app):
    admin = as_admin(app)
    assert admin.post("/api/account/password", json={"current": "fout", "new": "nieuw-wachtwoord-99"}).status_code == 403
    assert admin.post("/api/account/password", json={"current": PASSWORD, "new": "kort"}).status_code == 422
    assert admin.post("/api/account/password", json={"current": PASSWORD, "new": "nieuw-wachtwoord-99"}).json() == {"ok": True}
    assert login(TestClient(app)).status_code == 401
    assert login(TestClient(app), password="nieuw-wachtwoord-99").status_code == 200
    assert admin.patch("/api/account", json={"display_name": "Joost J."}).json()["display_name"] == "Joost J."


def test_first_person_to_register_is_admin_on_an_empty_install(tmp_path):
    e = db.connect(f"sqlite:///{tmp_path / 'new.db'}")
    settings = make_settings()
    settings.user, settings.password_hash = "", ""
    app = create_app(engine=e, settings=settings)
    assert TestClient(app).get("/api/auth/config").json() | {"privacy": None} == {"registration": "open", "first_user": True, "privacy": None, "session_days": 30, "front_door_url": None}
    c, r = register(app, username="eerste")
    assert r.json()["is_admin"] is True
    assert TestClient(app).get("/api/auth/config").json()["registration"] == "closed"


def test_new_user_without_zones_gets_dashboard_and_trends(app, engine):  # noqa: F811
    from tests.test_store import GARMIN_ACTIVITY, GARMIN_SPLITS
    from tools.store import from_garmin

    admin = as_admin(app)
    admin.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    anna, _ = register(app)
    anna_id = anna.get("/api/me").json()["id"]
    db.upsert_activity(db.Scope(engine, anna_id), from_garmin(GARMIN_ACTIVITY, GARMIN_SPLITS))
    d = anna.get("/api/dashboard")
    assert d.status_code == 200 and d.json()["zones_set"] == [] and d.json()["zone_estimates"] == []
    assert anna.get("/api/trends").status_code == 200
    # Joost's zones say which sports are estimates; Anna's say nothing about him
    db.set_setting(db.Scope(engine, 1), "zones", {"run": {"max_hr": 189, "bounds": [132, 147, 162, 176]}, "ride": {"max_hr": 182, "bounds": [127, 141, 156, 169], "estimate": True}})
    assert admin.get("/api/dashboard").json()["zone_estimates"] == ["ride"]
    assert anna.get("/api/dashboard").json()["zone_estimates"] == []


def test_profile_resting_hr_is_used_without_sleep_data(app, engine):  # noqa: F811
    from datetime import date

    from api.dashboard import DEFAULT_RHR, resting_hr

    today = date(2026, 10, 6)
    assert resting_hr({}, today) == DEFAULT_RHR == 60
    assert resting_hr({}, today, 48) == 48
    assert resting_hr({"2026-10-01": {"resting_hr": 50}}, today, 48) == 50  # a measured night beats the profile


def test_logins_from_before_the_accounts_move_over_at_startup(tmp_path, monkeypatch):
    import bcrypt
    from datetime import datetime, timezone

    from trackerai_accounts import totp

    from api.main import test_accounts
    from tools import secretbox

    key = secretbox.default_key() or __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key)
    e = db.connect(f"sqlite:///{tmp_path / 'old.db'}")
    db.create_schema(e)
    pw = "anna" + "-wachtwoord-1"
    joost = db.create_user(e, "joost", bcrypt.hashpw(b"x" * 12, bcrypt.gensalt(4)).decode(), is_admin=True)
    anna = db.create_user(e, "anna", bcrypt.hashpw(pw.encode(), bcrypt.gensalt(4)).decode())
    db.create_user(e, "made-by-an-account", "!")
    secret = totp.new_secret()
    db.update_user(e, anna, totp_secret=secretbox.encrypt(secret, key), totp_enabled_at=datetime.now(timezone.utc), totp_backup=[])
    settings = make_settings()
    settings.user, settings.password_hash = "", ""
    accounts = test_accounts(settings)
    app = create_app(engine=e, settings=settings, accounts=accounts)
    assert sorted(a["username"] for a in accounts.list_accounts()) == ["anna", "joost"]
    assert accounts.by_username("joost")["is_admin"] and not accounts.by_username("anna")["is_admin"]
    c = TestClient(app)
    r = c.post("/api/login", json={"username": "anna", "password": pw})
    assert r.json()["code"] == "totp_required"  # her two-step login came along
    assert c.post("/api/login", json={"username": "anna", "password": pw, "totp": totp.code_at(secret)}).status_code == 200
    assert c.get("/api/me").json()["id"] == anna  # her own health-tracker user, with its data
    create_app(engine=e, settings=settings, accounts=accounts)  # a restart moves nothing twice
    assert len(accounts.list_accounts()) == 2 and joost
