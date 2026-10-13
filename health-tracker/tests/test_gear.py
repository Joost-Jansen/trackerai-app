"""Gear (api/gear.py, tools/db.py): what wears out, how far it went and when to replace it.

The engine fixture holds one 10 km run on 2026-09-29 that came from Garmin (Garmin id 1).
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from api.gear import summarize
from api.main import create_app
from tests.test_api import engine, login, make_settings  # noqa: F401  (engine is a fixture)
from tools import db
from tools.sync import garmin_gear


def _run(s, day, km, garmin_id=None, sport="run"):
    return db.upsert_activity(s, {
        "start_utc": f"{day}T06:00:00Z", "start_local": f"{day}T08:00:00", "sport": sport, "name": f"{sport} {day}",
        "distance_km": km, "moving_time_s": int(km * 330), "sources": {"garmin" if garmin_id else "wahoo": {"id": garmin_id or day, "raw": {}}},
    })


@pytest.fixture
def client(engine):  # noqa: F811
    c = TestClient(create_app(engine=engine, settings=make_settings()))
    assert login(c).status_code == 200
    return c


def _gear(client, gid):
    return next(g for g in client.get("/api/gear").json()["gear"] if g["id"] == gid)


def test_own_shoes_count_the_runs_from_their_first_day_and_say_when_to_replace(client, engine):  # noqa: F811
    s = db.Scope(engine, 1)
    _run(s, "2026-08-01", 5)  # before the shoes
    _run(s, "2026-10-01", 12)
    r = client.post("/api/gear", json={"kind": "shoes", "name": "Pegasus 41", "start_km": 600, "since": "2026-09-01", "default_for": ["run"]})
    assert r.status_code == 201
    g = r.json()
    # 600 before + the 10 km run of 29 Sep + 12 km on 1 Oct; the run of 1 Aug was before them
    assert g["total_km"] == 622 and g["linked_km"] == 22 and g["uses"] == 2 and g["default_for"] == ["run"]
    assert (g["limit_km"], g["limit_from"], g["state"]) == (700, "default", "soon")
    g = client.patch(f"/api/gear/{g['id']}", json={"max_km": 620}).json()
    assert (g["state"], g["left_km"], g["limit_from"]) == ("replace", -2, "own")
    assert [a["distance_km"] for a in client.get(f"/api/gear/{g['id']}/activities").json()] == [12, 10]
    bike = client.post("/api/gear", json={"kind": "bike", "name": "Canyon"}).json()
    assert bike["limit_km"] is None and bike["state"] == "ok"  # a bike has no default limit


def test_a_choice_on_an_activity_wins_and_can_be_undone(client, engine):  # noqa: F811
    s = db.Scope(engine, 1)
    aid = db.load_activities(s)[0]["id"]
    a = client.post("/api/gear", json={"kind": "shoes", "name": "A", "default_for": ["run"]}).json()
    b = client.post("/api/gear", json={"kind": "shoes", "name": "B"}).json()
    assert [x["name"] for x in client.get(f"/api/activities/{aid}").json()["gear"]] == ["A"]
    r = client.put(f"/api/activities/{aid}/gear", json={"gear_ids": [b["id"]]}).json()
    assert [x["name"] for x in r["gear"]] == ["B"] and not r["automatic"]
    assert (_gear(client, a["id"])["linked_km"], _gear(client, b["id"])["linked_km"]) == (0, 10)
    detail = client.get(f"/api/activities/{aid}").json()
    assert detail["gear_chosen"] and [x["source"] for x in detail["gear"]] == ["manual"]
    assert client.put(f"/api/activities/{aid}/gear", json={"gear_ids": []}).json()["gear"] == []  # none, not even the default
    assert client.put(f"/api/activities/{aid}/gear", json={"gear_ids": None}).json()["gear"][0]["name"] == "A"


def test_a_default_moves_to_the_newer_shoes_and_retired_ones_stop_counting(client, engine):  # noqa: F811
    s = db.Scope(engine, 1)
    _run(s, "2026-10-05", 8)
    old = client.post("/api/gear", json={"kind": "shoes", "name": "Old", "default_for": ["run"]}).json()
    new = client.post("/api/gear", json={"kind": "shoes", "name": "New", "since": "2026-10-01", "default_for": ["run"]}).json()
    # one default per sport: New took it over, so only runs from 1 Oct are New's; the 29 Sep run has no gear now
    assert (_gear(client, old["id"])["default_for"], _gear(client, new["id"])["linked_km"]) == ([], 8)
    client.patch(f"/api/gear/{old['id']}", json={"default_for": ["run"], "retired_on": "2026-09-30"})
    assert _gear(client, old["id"])["linked_km"] == 10 and _gear(client, old["id"])["state"] == "retired"


def test_garmin_gear_with_its_history_and_links(client, engine):  # noqa: F811
    s = db.Scope(engine, 1)
    _run(s, "2026-10-02", 6, garmin_id=2)
    raw = {"uuid": "u1", "gearTypeName": "Shoes", "gearMakeName": "Nike", "gearModelName": "Pegasus 41", "displayName": "Pegasus",
           "gearStatusName": "active", "dateBegin": "2026-03-01T00:00:00.0", "maximumMeters": 800000.0}
    item = garmin_gear(raw, {"totalDistance": 316000.0, "totalActivities": 40}, [{"activityId": 1}, {"activityId": 2}])
    assert (item["kind"], item["brand"], item["max_km"], item["total_km"]) == ("shoes", "Nike", 800, 316)
    assert db.save_garmin_gear(s, [item]) == {"added": 1, "linked": 2}
    g = client.get("/api/gear").json()["gear"][0]
    # Garmin counted 316 km over 40 activities; 16 km of those are the two runs here
    assert (g["source"], g["total_km"], g["before_km"], g["linked_km"], g["uses"]) == ("garmin", 316, 300, 16, 40)
    assert (g["limit_km"], g["limit_from"], g["since"]) == (800, "garmin", "2026-03-01")
    assert client.delete(f"/api/gear/{g['id']}").json()["code"] == "garmin_gear"
    # renamed here: Garmin's name no longer overwrites it; retired in Garmin: retired here too, links stay
    client.patch(f"/api/gear/{g['id']}", json={"name": "Race shoes"})
    db.save_garmin_gear(s, [{**item, "name": "Pegasus 2", "status": "retired", "date_end": "2026-10-10"}])
    g = client.get("/api/gear").json()["gear"][0]
    assert (g["name"], g["retired_on"], g["state"], g["linked_km"]) == ("Race shoes", "2026-10-10", "retired", 16)


def test_the_sync_brings_garmin_gear(engine, monkeypatch):  # noqa: F811
    from cryptography.fernet import Fernet

    from tests.test_sync_db import FakeClientWithTokens, streams
    from tools.secretbox import encrypt
    from tools.sync import run_db_sync

    class WithGear(FakeClientWithTokens):
        def gear(self):
            return [garmin_gear({"uuid": "u9", "gearTypeName": "Bike", "displayName": "Canyon", "gearStatusName": "active"},
                                {"totalDistance": 1500000.0, "totalActivities": 30}, [])]

    key = Fernet.generate_key().decode()
    s = db.Scope(engine, 1)
    db.set_setting(s, "garmin_tokens", encrypt("tok", key))
    run_db_sync(s, key, None, client_factory=WithGear, read_streams=streams, today=date(2026, 10, 1))
    (bike,) = db.list_gear(s)
    assert (bike["kind"], bike["name"], bike["garmin"]["total_km"]) == ("bike", "Canyon", 1500)


def test_gear_is_in_the_export_and_goes_with_the_account(client, engine):  # noqa: F811
    s = db.Scope(engine, 1)
    client.post("/api/gear", json={"kind": "shoes", "name": "A", "default_for": ["run"]})
    tables = dict(db.export_tables(s))
    assert [g["name"] for g in tables["gear"]] == ["A"] and len(list(tables["activity_gear"])) == 1
    db.delete_user(engine, 1)
    assert db.list_gear(s) == [] and db.gear_links(s) == []


def test_checks_on_input(client):
    assert client.post("/api/gear", json={"kind": "boat", "name": "X"}).json()["code"] == "invalid_choice"
    assert client.post("/api/gear", json={"kind": "shoes", "name": " "}).json()["code"] == "gear_name_required"
    assert client.post("/api/gear", json={"kind": "shoes", "name": "X", "since": "gisteren"}).json()["code"] == "invalid_date"
    assert client.patch("/api/gear/999", json={"name": "Y"}).status_code == 404
    assert client.put("/api/activities/nope/gear", json={"gear_ids": []}).status_code == 404


def test_summary_orders_what_needs_attention_first():
    items = [{"id": i, "kind": "shoes", "name": n, "start_km": km, "max_km": 100, "retired_on": r} for i, (n, km, r) in
             enumerate([("ok", 10, None), ("old", 500, "2026-01-01"), ("worn", 120, None), ("nearly", 90, None)])]
    names = [g["name"] for g in summarize(items, [], [], {}, date(2026, 10, 1))]
    assert names == ["worn", "nearly", "ok", "old"]
