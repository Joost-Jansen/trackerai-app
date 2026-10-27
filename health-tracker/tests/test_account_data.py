"""Self-service export and deletion of your own account (api/account.py)."""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from tests.test_api import PASSWORD, engine, login, make_settings  # noqa: F401  (engine is a fixture)
from tools import db
from trackerai_accounts import totp

ANNA_PW = "anna-wachtwoord-1"


@pytest.fixture
def app(engine, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "Q0FGRUJBQkVDQUZFQkFCRUNBRkVCQUJFQ0FGRUJBQkU=")
    return create_app(engine=engine, settings=make_settings())


def anna(app, engine):  # noqa: F811
    admin = TestClient(app)
    login(admin)
    admin.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    c = TestClient(app)
    assert (
        c.post("/api/register", json={"username": "anna", "email": "anna@example.org", "password": ANNA_PW, "consent": True}).status_code
        == 200
    )
    uid = c.get("/api/me").json()["id"]
    s = db.Scope(engine, uid)
    db.upsert_activity(
        s,
        {
            "start_utc": "2026-10-01T06:00:00Z",
            "start_local": "2026-10-01T08:00:00",
            "sport": "ride",
            "name": "Anna's ride",
            "distance_km": 30.0,
            "moving_time_s": 3600,
            "streams": {"time": [0, 1], "heartrate": [120, 121]},
            "sources": {"fit": {"id": "x"}},
        },
    )
    aid = db.load_activities(s)[0]["id"]
    db.put_fit(s, f"upload/{aid}", b"FIT-BYTES")
    db.set_setting(s, "garmin_tokens", "k1:abcd:encrypted-session")
    db.put_document(s, "goals", "Sub 3", author="anna")
    c.post("/api/entries", json={"kind": "log", "title": "Anna-log", "body": "b"})
    c.post("/api/plans", json={"title": "Plan", "sessions": [{"date": "2026-10-04", "sport": "run"}]})
    c.post("/api/agent-tokens", json={"name": "Claude"})
    c.post("/api/feedback", json={"kind": "idea", "message": "more charts", "screenshot": "data:image/png;base64,iVBORw0KGgo="})
    return admin, c, uid


def test_export_is_a_zip_of_own_data_without_secrets(app, engine):  # noqa: F811
    admin, c, uid = anna(app, engine)
    r = c.get("/api/account/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers["content-disposition"] and "health-tracker-anna-" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(z.namelist())
    assert {
        "README.txt",
        "account.json",
        "activities.json",
        "activity_streams.json",
        "settings.json",
        "plans.json",
        "plan_sessions.json",
        "entries.json",
        "documents.json",
        "feedback.json",
        "agent_tokens.json",
    } <= names
    assert any(n.startswith("fit/upload__") for n in names) and any(n.startswith("feedback/") for n in names)
    load = lambda n: json.loads(z.read(n))  # noqa: E731
    assert load("account.json")[0]["username"] == "anna" and "password_hash" not in load("account.json")[0]
    assert [a["data"]["name"] for a in load("activities.json")] == ["Anna's ride"]  # not the admin's Ochtendloop
    assert all(s["key"] != "garmin_tokens" for s in load("settings.json"))
    assert "hash" not in load("agent_tokens.json")[0] and load("plan_sessions.json")[0]["sport"] == "run"
    assert b"Ochtendloop" not in r.content
    agent_token = c.post("/api/agent-tokens", json={"name": "x", "scope": "write"}).json()["token"]
    assert TestClient(app, headers={"Authorization": f"Bearer {agent_token}"}).get("/api/account/export").status_code == 403


def test_delete_removes_everything_of_the_account_and_nothing_else(app, engine):  # noqa: F811
    admin, c, uid = anna(app, engine)
    before_admin = len(db.load_activities(db.Scope(engine, 1)))
    assert c.request("DELETE", "/api/account", json={"password": "wrong-password"}).status_code == 403
    r = c.request("DELETE", "/api/account", json={"password": ANNA_PW})
    assert r.status_code == 200 and 'trackerai_session=""' in r.headers["set-cookie"]
    assert db.get_user(engine, uid) is None
    with engine.connect() as conn:
        for t in (*db.USER_TABLES, db.agent_tokens):
            assert conn.execute(t.select().where(t.c.user_id == uid)).first() is None, t.name
    assert len(db.load_activities(db.Scope(engine, 1))) == before_admin  # the admin's data is untouched
    assert admin.get("/api/me").status_code == 200
    assert TestClient(app).post("/api/login", json={"username": "anna", "password": ANNA_PW}).status_code == 401
    assert any(a["action"] == "delete_account" for a in db.list_audit(engine))


def test_delete_needs_the_second_factor_when_on(app, engine):  # noqa: F811
    admin, c, uid = anna(app, engine)
    secret = c.post("/api/account/totp/setup").json()["secret"]
    backup = c.post("/api/account/totp/enable", json={"code": totp.code_at(secret)}).json()["backup_codes"]
    assert c.request("DELETE", "/api/account", json={"password": ANNA_PW}).json()["code"] == "totp_required"
    assert c.request("DELETE", "/api/account", json={"password": ANNA_PW, "totp": "000000"}).json()["code"] == "totp_invalid"
    assert c.request("DELETE", "/api/account", json={"password": ANNA_PW, "totp": backup[0]}).status_code == 200


def test_the_last_admin_cannot_delete_themselves(app, engine):  # noqa: F811
    admin, c, uid = anna(app, engine)
    r = admin.request("DELETE", "/api/account", json={"password": PASSWORD})
    assert r.status_code == 409 and r.json()["code"] == "last_admin"
    anna_account = c.get("/api/auth/account").json()["id"]
    admin.patch(f"/api/admin/accounts/{anna_account}", json={"is_admin": True})  # someone else can run the install now
    assert admin.request("DELETE", "/api/account", json={"password": PASSWORD}).status_code == 200


def test_delete_waits_for_a_running_sync(app, engine):  # noqa: F811
    admin, c, uid = anna(app, engine)
    app.state.sync.running[uid] = "now"
    assert c.request("DELETE", "/api/account", json={"password": ANNA_PW}).status_code == 200
    assert db.get_user(engine, uid) is not None  # the sync would write after the delete: the data goes on the next sweep
    app.state.sync.running.pop(uid)
    assert app.state.purge() == 1 and db.get_user(engine, uid) is None


def test_leaving_health_tracker_deletes_its_data_but_keeps_the_account(app, engine):  # noqa: F811
    admin, c, uid = anna(app, engine)
    assert c.request("DELETE", "/api/account/apps/health", json={"password": ANNA_PW}).status_code == 200
    assert db.get_user(engine, uid) is None
    me = c.get("/api/me").json()
    assert me["in_app"] is False and me["id"] is None
    assert c.get("/api/dashboard").json()["code"] == "not_in_app"
