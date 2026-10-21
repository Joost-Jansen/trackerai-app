from fastapi.testclient import TestClient

from api.main import create_app
from tests.test_api import PASSWORD, make_settings
from tests.test_store import GARMIN_ACTIVITY
from tools import db
from tools.distance import counted, doubtful
from tools.store import from_garmin
from trackerai_testing import new_database_url

OWS = {"activityType": {"typeKey": "open_water_swimming", "parentTypeId": 26}}


def ows(km, moving, duration, day="2026-06-07", hh="08"):
    """A Garmin open-water swim as the activity list gives it: moving time broken, timer time right."""
    return {**GARMIN_ACTIVITY, **OWS, "activityId": hash((day, hh)) % 10**9, "activityName": "Open Water Swimming",
            "startTimeLocal": f"{day} {hh}:04:00", "startTimeGMT": f"{day} {int(hh) - 2:02d}:04:00",
            "distance": km * 1000, "movingDuration": moving, "duration": duration}


def test_an_open_water_swim_takes_the_timer_time_not_garmins_moving_time():
    a = from_garmin(ows(1.97, 223.0, 2723.0), None)
    assert (a["sport"], a["moving_time_s"], a["open_water"]) == ("swim", 2723, True)
    run = from_garmin({**GARMIN_ACTIVITY, "movingDuration": 3000.0, "duration": 3300.0}, None)
    assert run["moving_time_s"] == 3000 and "open_water" not in run


def test_an_impossible_open_water_pace_is_a_gps_error():
    good = from_garmin(ows(1.97, 223.0, 2723.0), None)  # 2:18/100m
    short = from_garmin(ows(0.02, 584.0, 584.0), None)  # 20 m in almost 10 minutes
    fast = from_garmin(ows(2.0, 600.0, 600.0), None)  # 0:30/100m
    assert (doubtful(good), doubtful(short), doubtful(fast)) == (False, True, True)
    c = counted(short)
    assert c["distance_km"] is None and c["gps_distance_km"] == 0.02 and c["distance_doubtful"] and c["moving_time_s"] == 584
    pool = {**short, "open_water": None, "sources": {"garmin": {"raw": {"activityType": {"typeKey": "lap_swimming"}}}}}
    assert counted(pool) is pool  # a pool swim measures lengths, not GPS


def test_you_correct_the_distance_and_a_new_sync_keeps_it(tmp_path):
    e = db.connect(new_database_url())
    db.create_schema(e)
    s = db.Scope(e, 1)
    aid = db.upsert_activity(s, from_garmin(ows(0.02, 584.0, 2400.0), None))
    client = TestClient(create_app(engine=e, settings=make_settings()))
    assert client.post("/api/login", json={"username": "alice", "password": PASSWORD}).status_code == 200

    listed = next(a for a in client.get("/api/activities").json() if a["id"] == aid)
    assert listed.get("distance_km") is None and listed["gps_distance_km"] == 0.02 and listed["distance_doubtful"]

    assert client.patch(f"/api/activities/{aid}", json={"distance_km": 0}).json()["code"] == "invalid_distance"
    assert client.patch("/api/activities/nope", json={"distance_km": 2}).status_code == 404
    r = client.patch(f"/api/activities/{aid}", json={"distance_km": 2.0}).json()
    assert r["distance_km"] == 2.0 and r["distance_manual"] and r["gps_distance_km"] == 0.02 and not r.get("distance_doubtful")

    db.upsert_activity(s, from_garmin(ows(0.02, 584.0, 2400.0), None))  # the next sync brings Garmin's 20 m again
    assert db.load_activities(s)[0]["distance_km"] == 2.0

    r = client.patch(f"/api/activities/{aid}", json={"distance_km": None}).json()
    assert r.get("distance_km") is None and r["gps_distance_km"] == 0.02 and not r.get("distance_manual")


def test_schema_5_gives_stored_open_water_swims_their_timer_time(tmp_path):
    e = db.connect(new_database_url())
    db.create_schema(e)
    s = db.Scope(e, 1)
    old = from_garmin(ows(1.97, 223.0, 2723.0), None)
    old.update(moving_time_s=223)  # what schema 4 stored
    old.pop("open_water")
    aid = db.upsert_activity(s, old)
    with e.begin() as c:
        c.execute(db.app_settings.update().where(db.app_settings.c.key == "schema_version").values(value=4))
    db.create_schema(e)
    a = db.load_activities(s)[0]
    assert (a["id"], a["moving_time_s"], a["open_water"], a["sources"]["garmin"]["fields"]["moving_time_s"]) == (aid, 2723, True, 2723)


def test_removing_the_only_source_also_removes_your_correction(tmp_path):
    e = db.connect(new_database_url())
    db.create_schema(e)
    s = db.Scope(e, 1)
    aid = db.upsert_activity(s, from_garmin(ows(0.02, 584.0, 2400.0), None))
    db.set_manual_distance(s, aid, 2.0)
    assert db.remove_source(s, "garmin") == {"removed": 1, "changed": 0}
    assert db.load_activities(s) == []
