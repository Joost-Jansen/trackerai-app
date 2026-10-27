"""The admin hub at trackerai.nl/admin (api/tracker_admin.py, api/betas.py): workouts per week and per account, beta
features per account, feedback in the hub's shape, and posts from the front door through the CSRF check."""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

import api.main
from api import betas, tracker_admin
from api.main import create_app
from tests.test_api import engine, make_settings  # noqa: F401  (fixture)
from tests.test_feedback import send
from tests.test_multiuser_api import as_admin, register
from tools import db
from trackerai_accounts import Config, crypto
from trackerai_testing import new_database_url

NO_HASH = "".join(["!"])  # local users without a password of their own (the account holds it)

TODAY = date(2026, 10, 9)  # a Friday: this ISO week starts on 2026-10-05, the twelfth week back on 2026-07-20
FEEDBACK_FIELDS = {
    "id",
    "app",
    "kind",
    "message",
    "page",
    "context",
    "status",
    "reply",
    "created_at",
    "updated_at",
    "account_id",
    "username",
    "has_screenshot",
}


def workout(s, day: str, n: int):
    db.upsert_activity(
        s,
        {
            "start_utc": f"{day}T05:00:00Z",
            "start_local": f"{day}T07:00:00",
            "sport": "run",
            "name": f"Loop {n}",
            "distance_km": 5.0,
            "moving_time_s": 1500,
            "sources": {"garmin": {"id": 1000 + n, "raw": {}}},
        },
    )


@pytest.fixture
def app(engine, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(api.main, "today", lambda: TODAY)
    return create_app(engine=engine, settings=make_settings())


@pytest.fixture
def hub(app, engine):  # noqa: F811
    """The admin, and anna with three workouts (one before the twelve weeks)."""
    admin = as_admin(app)
    admin.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    anna, _ = register(app)
    uid = anna.get("/api/me").json()["id"]
    for n, day in enumerate(("2026-10-06", "2026-07-20", "2026-07-19")):
        workout(db.Scope(engine, uid), day, n)
    ids = {name: app.state.accounts.by_username(name)["id"] for name in ("alice", "anna")}
    return admin, anna, ids


def test_tracker_overview(hub):
    admin, _, ids = hub
    out = admin.get("/api/admin/tracker").json()
    assert out["app"] == "health" and out["betas"] == betas.BETA_FEATURES and out["measure"] == {"en": "workouts", "nl": "trainingen"}
    weeks = out["weekly"]
    assert len(weeks) == 12 and weeks[0]["week"] == "2026-07-20" and weeks[-1]["week"] == "2026-10-05"
    assert all(date.fromisoformat(w["week"]).weekday() == 0 for w in weeks)
    values = {w["week"]: w["value"] for w in weeks}
    # anna on 07-20 and 10-06, alice (tests/test_api.py) on 09-29; anna's 07-19 is before the twelve weeks
    assert values == {**{w["week"]: 0 for w in weeks}, "2026-07-20": 1, "2026-09-28": 1, "2026-10-05": 1}
    accounts = {a["account_id"]: a for a in out["accounts"]}
    assert accounts == {
        ids["alice"]: {"account_id": ids["alice"], "betas": [], "count": 1, "last_at": "2026-09-29T06:00:00+00:00", "disk_bytes": 0},
        ids["anna"]: {"account_id": ids["anna"], "betas": [], "count": 3, "last_at": "2026-10-06T05:00:00+00:00", "disk_bytes": 0},
    }
    assert out["disk_bytes_total"] == 0
    assert datetime.fromisoformat(accounts[ids["anna"]]["last_at"]).tzinfo is not None


def test_disk_bytes_are_the_stored_activity_files(hub, app, engine):  # noqa: F811
    admin, anna, ids = hub
    uid = anna.get("/api/me").json()["id"]
    db.put_fit(db.Scope(engine, uid), "upload/a", b"0" * 1000)
    db.put_fit(db.Scope(engine, uid), "upload/b", b"0" * 500)
    db.put_fit(db.Scope(engine, db.create_user(engine, "los", NO_HASH)), "upload/c", b"0" * 30)  # no account: only in the total
    out = admin.get("/api/admin/tracker").json()
    assert {a["account_id"]: a["disk_bytes"] for a in out["accounts"]} == {ids["alice"]: 0, ids["anna"]: 1500}
    assert out["disk_bytes_total"] == 1530


def test_weekly_zero_fills_twelve_weeks():
    weeks = tracker_admin.weekly({}, date(2026, 1, 1))  # a Thursday in ISO week 2026-W01, which starts in 2025
    assert [w["week"] for w in weeks][-2:] == ["2025-12-22", "2025-12-29"] and len(weeks) == 12
    assert all(w["value"] == 0 for w in weeks)
    weeks = tracker_admin.weekly({"2025-12-29": 2, "2026-01-04": 1, "2025-10-05": 9, "bad": 4}, date(2026, 1, 4))
    assert weeks[-1] == {"week": "2025-12-29", "value": 3} and sum(w["value"] for w in weeks) == 3


def test_an_account_without_activities_or_a_health_user(app, engine):  # noqa: F811
    admin = as_admin(app)
    admin.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    bob, _ = register(app, username="bob")
    bob.get("/api/me")
    bob_id = app.state.accounts.by_username("bob")["id"]
    entry = next(a for a in admin.get("/api/admin/tracker").json()["accounts"] if a["account_id"] == bob_id)
    assert entry == {"account_id": bob_id, "betas": [], "count": 0, "last_at": None, "disk_bytes": 0}
    # a user without a linked account is left out
    db.create_user(engine, "los", NO_HASH)
    assert len(admin.get("/api/admin/tracker").json()["accounts"]) == 2


def test_only_admins_logged_in_on_the_site(hub, app):
    admin, anna, ids = hub
    assert anna.get("/api/admin/tracker").status_code == 403
    assert anna.patch(f"/api/admin/tracker/betas/{ids['anna']}", json={"feature": "x", "enabled": True}).status_code == 403
    assert TestClient(app).get("/api/admin/tracker").status_code == 401
    token = admin.post("/api/agent-tokens", json={"name": "Claude", "scope": "write"}).json()["token"]
    assert TestClient(app).get("/api/admin/tracker", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_beta_errors(hub):
    admin, _, ids = hub
    r = admin.patch("/api/admin/tracker/betas/9999", json={"feature": "new_trends", "enabled": True})
    assert r.status_code == 404 and r.json()["code"] == "account_not_found"
    r = admin.patch(f"/api/admin/tracker/betas/{ids['anna']}", json={"feature": "new_trends", "enabled": True})
    assert r.status_code == 422 and r.json()["code"] == "unknown_beta"  # not one of health-tracker's beta features
    assert admin.patch(f"/api/admin/tracker/betas/{ids['anna']}", json={"feature": "new_trends"}).status_code == 422


def test_beta_toggle(hub, app, engine, monkeypatch):  # noqa: F811
    admin, anna, ids = hub
    feature = {"id": "new_trends", "name": {"en": "New trends page", "nl": "Nieuwe trendspagina"}}
    monkeypatch.setattr(betas, "BETA_FEATURES", [feature, {"id": "later", "name": {"en": "Later", "nl": "Later"}}])
    assert anna.get("/api/me").json()["betas"] == []
    r = admin.patch(f"/api/admin/tracker/betas/{ids['anna']}", json={"feature": "new_trends", "enabled": True})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "account_id": ids["anna"],
        "betas": ["new_trends"],
        "count": 3,
        "last_at": "2026-10-06T05:00:00+00:00",
        "disk_bytes": 0,
    }
    out = admin.get("/api/admin/tracker").json()
    assert out["betas"][0] == feature
    assert {a["account_id"]: a["betas"] for a in out["accounts"]} == {ids["alice"]: [], ids["anna"]: ["new_trends"]}
    me = anna.get("/api/me").json()
    assert me["betas"] == ["new_trends"] and betas.enabled(engine, me["id"], "new_trends")
    assert admin.get("/api/me").json()["betas"] == []
    audit = db.list_audit(engine)[0]
    assert (audit["actor"], audit["action"], audit["target"], audit["detail"]) == ("alice", "set_beta", "anna", "new_trends on")
    # twice on stays one; off again
    admin.patch(f"/api/admin/tracker/betas/{ids['anna']}", json={"feature": "new_trends", "enabled": True})
    assert db.user_betas(engine, me["id"]) == ["new_trends"]
    r = admin.patch(f"/api/admin/tracker/betas/{ids['anna']}", json={"feature": "new_trends", "enabled": False})
    assert r.json()["betas"] == [] and anna.get("/api/me").json()["betas"] == []
    # a feature taken out of the registry is off for everyone, whatever was stored
    admin.patch(f"/api/admin/tracker/betas/{ids['anna']}", json={"feature": "later", "enabled": True})
    monkeypatch.setattr(betas, "BETA_FEATURES", [feature])
    assert anna.get("/api/me").json()["betas"] == [] and not betas.enabled(engine, me["id"], "later")


def test_betas_column_is_added_to_an_existing_database(tmp_path):
    e = db.connect(new_database_url())
    db.create_schema(e)
    uid = db.create_user(e, "anna", NO_HASH)
    with e.begin() as c:  # a schema 6 database: no betas yet
        c.execute(text("ALTER TABLE users DROP COLUMN betas"))
        c.execute(db.app_settings.update().where(db.app_settings.c.key == "schema_version").values(value=6))
    db.create_schema(e)
    assert "betas" in {c["name"] for c in inspect(e).get_columns("users")}
    assert db.user_betas(e, uid) == [] and db.get_user(e, uid)["betas"] == []
    assert db.set_user_beta(e, uid, "x", True) == ["x"] and db.user_betas(e, uid) == ["x"]
    assert db.get_app_setting(e, "schema_version") == db.SCHEMA_VERSION


# --- feedback in the hub's shape ------------------------------------------------------------------------------


def test_feedback_has_the_hub_shape_everywhere(app, engine):  # noqa: F811
    admin = as_admin(app)
    admin.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    db.create_user(engine, "anna", NO_HASH)  # an old local user with the same name: anna's own becomes "anna-2" here
    anna, _ = register(app)
    assert db.get_user(engine, anna.get("/api/me").json()["id"])["username"] == "anna-2"
    aid = app.state.accounts.by_username("anna")["id"]
    sent = send(anna).json()
    items = [
        sent,
        anna.get("/api/feedback").json()[0],
        admin.get("/api/admin/feedback").json()[0],
        admin.patch(f"/api/admin/feedback/{sent['id']}", json={"status": "planned"}).json(),
    ]
    for f in items:
        assert set(f) == FEEDBACK_FIELDS
        assert f["app"] == "health" and f["account_id"] == aid and f["username"] == "anna" and f["id"] == sent["id"]
        assert datetime.fromisoformat(f["created_at"]).tzinfo is not None
    assert items[0]["updated_at"] is None and datetime.fromisoformat(items[-1]["updated_at"]).tzinfo is not None


def test_feedback_of_an_unlinked_user_keeps_the_local_name(app, engine):  # noqa: F811
    admin = as_admin(app)
    uid = db.create_user(engine, "oud", NO_HASH)
    db.add_feedback(engine, uid, "idea", "Meer grafieken", None, None)
    f = admin.get("/api/admin/feedback").json()[0]
    assert f["account_id"] is None and f["username"] == "oud" and f["app"] == "health"


# --- CSRF: the front door -------------------------------------------------------------------------------------


def test_front_door_origins_may_post(engine, tmp_path):  # noqa: F811
    shared = Config(
        database_url=new_database_url(),
        session_secret="s" * 40,
        encryption_key=crypto.new_key(),
        cookie_domain="trackerai.nl",
        cookie_secure=False,
        require_totp="off",
    )
    c = TestClient(create_app(engine=engine, settings=make_settings(accounts=shared)))
    wrong = {"username": "alice", "password": "not-" + "the-pw"}
    c.cookies.set(api.main.account_session.COOKIE, "x")  # a cookie in the browser: the check applies
    for origin in ("https://trackerai.nl", "https://www.trackerai.nl"):
        assert c.post("/api/login", json=wrong, headers={"Origin": origin}).status_code == 401  # past the origin check
    for origin in ("https://evil.example", "https://trackerai.nl.evil.example", "https://health.trackerai.nl"):
        r = c.post("/api/login", json=wrong, headers={"Origin": origin})
        assert r.status_code == 403 and r.json()["code"] == "csrf_origin", origin
    # and the site knows where the front door is, to link to its admin page
    assert c.get("/api/auth/config").json()["front_door_url"] == "https://www.trackerai.nl"
    assert c.get("/api/auth/registration-status").json()["front_door_url"] == "https://www.trackerai.nl"
