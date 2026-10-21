from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from api.main import Settings, create_app
from scripts.seed_demo import link_account, seed
from tools import db
from trackerai_testing import create_database, drop_database

# Today, like the real seed default: the dashboard hides readiness when the last sync is older than yesterday,
# so a fixed date would make this test fail as soon as the calendar moves on.
END = datetime.now(ZoneInfo("Europe/Amsterdam")).date()


@pytest.fixture(scope="module")
def seeded():
    url = create_database()  # one seed for the module
    engine = db.connect(url)
    out = seed(engine, END, days=56, password="demo-password-1")
    yield engine, out
    engine.dispose()
    drop_database(url)


def test_seed_creates_demo_admin_with_data(seeded):
    engine, out = seeded
    user = db.get_user_by_name(engine, "demo")
    assert user["is_admin"] and out["admin"]
    s = db.Scope(engine, user["id"])
    acts = db.load_activities(s)
    assert len(acts) == out["activities"] > 20
    assert {a["sport"] for a in acts} == {"run", "ride", "swim"}
    assert all(a.get("hr_zones_s") for a in acts)  # derive ran
    assert max(a["start_local"] for a in acts) < END.isoformat()  # nothing done yet today
    assert db.load_routes(s) and db.active_plan(s)["sessions"]
    assert len(db.load_wellness(s)) == 57
    days = db.intraday_days(s)
    assert len(days) == out["intraday_days"] == 28 and days[-1] == END.isoformat()
    last = db.get_intraday(s, END.isoformat())
    # minutes from midnight: a start before midnight is negative, but a late night (Friday) can start after it
    assert last["sleep"]["start"] < last["sleep"]["end"] and last["sleep"]["end"] > 0
    assert last["sleep"]["stages"] and len(last["hr"]) > 100
    assert all(last.get(k) for k in ("stress", "bb", "resp", "spo2"))
    assert all(k in db.load_wellness(s)[END.isoformat()] for k in ("sleep_resp", "sleep_stress", "bb_charged_sleep", "sleep_hr", "intensity_min"))


def test_seed_refuses_existing_user_without_reset(seeded):
    engine, _ = seeded
    with pytest.raises(SystemExit):
        seed(engine, END, days=7)


def test_demo_user_can_log_in_and_see_dashboard(seeded):
    engine, _ = seeded
    app = create_app(engine=engine, settings=Settings(jwt_secret="x" * 32, cookie_secure=False))
    link_account(app.state.accounts, engine)
    c = TestClient(app)
    assert c.post("/api/login", json={"username": "demo", "password": "demo-password-1"}).status_code == 200
    dash = c.get("/api/dashboard").json()
    assert dash["upcoming"] and dash["readiness"]
    day = c.get("/api/wellness/day").json()
    assert day["day"] == END.isoformat() and day["night"]["rise"] > 0 and day["normals"]["resting_hr"] and day["normals"]["sleep_resp"]
