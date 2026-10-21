"""/api/onboarding: the welcome tour, the checklist and the start banner, per user, with steps derived from real data.

Stored with the account, not the browser. An existing user with activities is already on the way and gets no tour.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from tests.test_api import engine, login, make_settings  # noqa: F401  (engine is a fixture)
from tools import db

ANNA_PW = "anna-wachtwoord-1"


@pytest.fixture
def app(engine, tmp_path):  # noqa: F811
    return create_app(engine=engine, settings=make_settings())


@pytest.fixture
def admin(app):
    c = TestClient(app)
    login(c)
    return c


@pytest.fixture
def anna(app, admin):
    admin.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    c = TestClient(app)
    assert (
        c.post("/api/register", json={"username": "anna", "email": "anna@example.org", "password": ANNA_PW, "consent": True}).status_code
        == 200
    )
    c.get("/api/me")  # the first visit makes health-tracker's own user
    return c


def test_needs_login(app):
    assert TestClient(app).get("/api/onboarding").status_code == 401
    assert TestClient(app).put("/api/onboarding", json={"done": True}).status_code == 401


def test_new_user_gets_the_tour_with_nothing_done(anna):
    r = anna.get("/api/onboarding").json()
    assert r["done"] is False and r["choice"] is None and r["step"] == 0
    assert r["hidden"] == [] and r["visited"] == []
    assert r["required_done"] is False
    assert not any(r["steps"].values())
    st = r["status"]
    assert st["garmin"] == {"connected": False, "connected_at": None}
    assert st["sync"]["last_sync"] is None and st["sync"]["running"] is False
    assert st["activities"] == {"count": 0, "first": None, "last": None, "sports": []}
    assert st["zones"]["set"] == [] and st["zones"]["suggested_max"] == {"run": None, "ride": None, "swim": None}
    assert st["agents"] == {"tokens": 0} and st["goals"] is False and st["plan"] == {"count": 0, "active": False}


def test_existing_user_with_data_is_not_shown_the_tour(admin):
    r = admin.get("/api/onboarding").json()
    assert r["done"] is True
    assert r["status"]["activities"]["count"] == 1 and r["status"]["activities"]["sports"] == ["run"]
    assert r["steps"]["sync"] and r["steps"]["zones"]
    assert r["status"]["zones"]["set"] == ["run"]
    # Help can start it again
    assert admin.put("/api/onboarding", json={"done": False, "step": 0}).json()["done"] is False
    assert admin.get("/api/onboarding").json()["done"] is False


def test_steps_follow_the_users_data(app, anna, engine):  # noqa: F811
    anna_id = db.get_user_by_name(engine, "anna")["id"]
    s = db.Scope(engine, anna_id)

    db.set_setting(s, "garmin_tokens", "encrypted-session")
    db.set_setting(s, "garmin_meta", {"connected_at": "2026-10-03 10:00"})
    r = anna.get("/api/onboarding").json()
    assert r["steps"]["garmin"] and not r["steps"]["sync"]
    assert r["status"]["garmin"]["connected_at"] == "2026-10-03 10:00"

    db.upsert_activity(
        s,
        {
            "start_utc": "2026-09-30T06:00:00Z",
            "start_local": "2026-09-30T08:00:00",
            "sport": "run",
            "name": "Rondje",
            "distance_km": 8.0,
            "moving_time_s": 2800,
            "avg_hr": 145,
            "max_hr": 181,
            "sources": {"garmin": {"id": 7, "raw": {}}},
        },
    )
    db.set_setting(s, "sync_state", {"last_sync_local": "2026-10-03 10:05"})
    app.state.stores.get(anna_id).invalidate()
    r = anna.get("/api/onboarding").json()
    assert r["steps"]["sync"] and r["status"]["activities"]["count"] == 1
    assert r["status"]["zones"]["suggested_max"]["run"] == 181
    assert not r["steps"]["zones"] and not r["required_done"]

    assert anna.put("/api/settings/zones", json={"sports": {"run": {"max_hr": 185}}}).status_code == 200
    r = anna.get("/api/onboarding").json()
    assert r["steps"]["zones"] and r["required_done"] and r["status"]["zones"]["set"] == ["run"]

    anna.put("/api/settings/profile", json={"birth_year": 1990})
    anna.post("/api/agent-tokens", json={"name": "Claude"})
    anna.put("/api/docs/goals", json={"body": "Halve marathon"})
    anna.post("/api/plans", json={"title": "Basis", "sessions": [{"date": "2026-10-10", "sport": "run"}]})
    r = anna.get("/api/onboarding").json()
    assert r["steps"]["profile"] and r["steps"]["agent"] and r["steps"]["goals"] and r["steps"]["plan"]
    assert r["status"]["profile"]["filled"] == ["birth_year"] and r["status"]["plan"] == {"count": 1, "active": True}


def test_choice_step_done_and_hidden_are_stored(anna):
    r = anna.put("/api/onboarding", json={"choice": "claude", "step": 3}).json()
    assert r["choice"] == "claude" and r["step"] == 3 and r["done"] is False
    anna.put("/api/onboarding", json={"hide": "checklist"})
    anna.put("/api/onboarding", json={"hide": "checklist"})
    r = anna.put("/api/onboarding", json={"done": True}).json()
    assert r["done"] is True and r["choice"] == "claude" and r["step"] == 3 and r["hidden"] == ["checklist"]
    again = anna.get("/api/onboarding").json()
    assert again["done"] is True and again["hidden"] == ["checklist"]


def test_visited_pages_complete_the_explore_step(anna):
    for page in ("trends", "routes", "trends"):
        r = anna.put("/api/onboarding", json={"visit": page}).json()
    assert r["visited"] == ["trends", "routes"] and r["steps"]["explore"] is False
    r = anna.put("/api/onboarding", json={"visit": "historie"}).json()  # the Dutch id from before schema 3 still counts
    assert r["steps"]["explore"] is True


def test_nonsense_is_400(anna):
    assert anna.put("/api/onboarding", json={"choice": "strava"}).status_code == 400
    assert anna.put("/api/onboarding", json={"step": -1}).status_code == 400
    assert anna.put("/api/onboarding", json={"step": True}).status_code == 400
    assert anna.put("/api/onboarding", json={"done": "ja"}).status_code == 400
    assert anna.put("/api/onboarding", json={"hide": "alles"}).status_code == 400
    assert anna.put("/api/onboarding", json={"visit": "beheer"}).status_code == 400
    assert anna.put("/api/onboarding", json={"iets": 1}).status_code == 400
    assert anna.get("/api/onboarding").json()["step"] == 0


def test_each_user_their_own_onboarding(admin, anna):
    anna.put("/api/onboarding", json={"done": True, "choice": "site", "hide": "data", "visit": "trends"})
    admin.put("/api/onboarding", json={"done": False, "step": 2})
    j = admin.get("/api/onboarding").json()
    a = anna.get("/api/onboarding").json()
    assert j["done"] is False and j["step"] == 2 and j["choice"] is None and j["hidden"] == [] and j["visited"] == []
    assert a["done"] is True and a["step"] == 0 and a["choice"] == "site" and a["hidden"] == ["data"]
    # The admin's activity, zones and sync are not Anna's
    assert a["status"]["activities"]["count"] == 0 and a["status"]["zones"]["set"] == [] and a["status"]["sync"]["last_sync"] is None


def test_agent_token_sees_its_own_user(app, anna):
    tok = anna.post("/api/agent-tokens", json={"name": "Claude"}).json()["token"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {tok}"})
    r = agent.get("/api/onboarding").json()
    assert r["status"]["agents"]["tokens"] == 1 and r["status"]["activities"]["count"] == 0


def test_dutch_page_ids_stored_before_schema_3_still_count(engine, anna):  # noqa: F811
    # The schema 3 migration renames them (tests/test_multiuser_db.py); reading converts any that are left.
    me = anna.get("/api/me").json()
    db.set_setting(
        db.Scope(engine, me["id"]), "onboarding", {"done": True, "visited": ["dashboard", "trends", "rondjes", "historie", "routes"]}
    )
    r = anna.get("/api/onboarding").json()
    assert r["visited"] == ["dashboard", "trends", "routes", "history"] and r["steps"]["explore"] is True
