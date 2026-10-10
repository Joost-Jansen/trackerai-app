from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from tests.fitbuild import bike_ride
from tests.test_api import client, engine, login  # noqa: F401  (fixtures)
from tools import db
from tools.fit import read_fit_activity
from tools.store import from_fit

START = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)


def upload(c, data, name="ride.fit", **params):
    return c.post("/api/activities/upload", params={"name": name, **params}, content=data, headers={"content-type": "application/octet-stream"})


def test_a_wahoo_file_becomes_a_ride_with_local_time_streams_and_source():
    a = read_fit_activity(bike_ride(START))
    assert a["manufacturer"] == "wahoo_fitness" and a["sport"] == "ride"
    assert a["start_local"] == "2026-09-20T10:00:00"  # the device's own offset, from the activity message
    rec = from_fit(a, filename="ride.fit")
    assert rec["name"] == "Wahoo Cycling" and rec["distance_km"] == 4.8 and rec["moving_time_s"] == 600
    assert list(rec["sources"]) == ["wahoo"] and rec["streams"]["latlng"][0] == [52.09, 5.12]


def test_other_devices_are_source_fit():
    rec = from_fit(read_fit_activity(bike_ride(START, manufacturer=1)))  # 1 = Garmin
    assert list(rec["sources"]) == ["fit"]


def test_upload_adds_the_ride_with_zones_and_track(client, engine):  # noqa: F811
    login(client)
    db.set_setting(db.Scope(engine, 1), "zones", {"ride": {"max_hr": 180, "bounds": [126, 139, 153, 167]}})
    r = upload(client, bike_ride(START))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "added" and body["source"] == "wahoo" and body["sport"] == "ride"
    detail = client.get(f"/api/activities/{body['id']}").json()
    assert detail["distance_km"] == 4.8
    assert detail["track"]["latlng"]  # map
    assert any(a["id"] == body["id"] for a in client.get("/api/activities", params={"sport": "ride"}).json())
    assert db.get_fit(db.Scope(engine, 1), f"upload/{body['id']}") is not None


def test_the_same_ride_from_garmin_is_merged_not_doubled(client, engine):  # noqa: F811
    login(client)
    s = db.Scope(engine, 1)
    db.upsert_activity(s, {
        "start_utc": "2026-09-20T08:00:40Z", "start_local": "2026-09-20T10:00:40", "sport": "ride", "name": "Utrecht Cycling",
        "distance_km": 4.79, "moving_time_s": 598, "sources": {"garmin": {"id": 1}},
    })
    before = len(client.get("/api/activities").json())
    r = upload(client, bike_ride(START)).json()
    assert r["status"] == "merged" and r["merged_with"] == ["garmin"]
    assert len(client.get("/api/activities").json()) == before
    merged = client.get(f"/api/activities/{r['id']}").json()
    assert merged["name"] == "Utrecht Cycling"  # Garmin's values stay leading


def test_batch_skips_recompute_until_the_end(client):  # noqa: F811
    login(client)
    for i in range(2):
        start = START.replace(day=10 + i)
        assert upload(client, bike_ride(start), recompute="false").json()["status"] == "added"
    assert client.post("/api/activities/recompute").status_code == 200


def test_bad_files_are_refused(client):  # noqa: F811
    login(client)
    assert upload(client, b"").status_code == 400
    assert upload(client, b"not a fit file at all").status_code == 422


def test_upload_needs_login_and_lands_in_own_account(client, engine):  # noqa: F811
    assert upload(TestClient(client.app), bike_ride(START)).status_code == 401
    login(client)
    upload(client, bike_ride(START))
    assert db.load_activities(db.Scope(engine, 2)) == []
