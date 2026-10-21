import io
import time
import zipfile
from datetime import date

import pytest

from scripts.make_apple_export import make
from tests.test_api import client, engine, login  # noqa: F401  (fixtures)
from tools import apple_health as ah
from tools import db
from tools.apple_import import apply, remove
from tools.sports import apple_sport
from trackerai_testing import new_database_url

END = date(2026, 10, 5)


@pytest.fixture(scope="module")
def export_zip() -> bytes:
    return make(END, 45)  # the oldest 15 days in the pre-iOS 16 shapes


@pytest.fixture(scope="module")
def parsed(export_zip):
    return ah.read_export(io.BytesIO(export_zip))


def test_time_keeps_the_phone_clock_and_its_offset():
    utc, off = ah.parse_time("2026-10-05 07:12:03 +0200")
    assert off == 7200 and ah.local_day(utc, off) == "2026-10-05"
    assert ah.local_minute(utc, off, "2026-10-05") == 7 * 60 + 12
    assert ah.local_minute(*ah.parse_time("2026-10-04 23:30:00 +0200"), "2026-10-05") == -30  # the evening before
    winter = ah.parse_time("2026-01-10 07:00:00 +0100")
    assert ah.local_minute(*winter, "2026-01-10") == 420


def test_apple_workout_types():
    assert apple_sport("HKWorkoutActivityTypeRunning") == "run"
    assert apple_sport("HKWorkoutActivityTypeTraditionalStrengthTraining") == "strength_training"
    assert apple_sport("HKWorkoutActivityTypeSomethingNew") == "something_new"


def test_workouts_new_and_old_shapes(parsed):
    acts = ah.activities(parsed, "export.zip")
    by_day = {a["start_local"][:10]: a for a in acts}
    assert {a["sport"] for a in acts} == {"run", "ride", "swim", "strength_training"}
    new_run = next(a for a in acts if a["sport"] == "run" and a["start_local"] > "2026-09-25" and not a.get("indoor"))
    assert new_run["streams"]["latlng"] and new_run["streams"]["heartrate"] and new_run["avg_hr"] > 100
    assert new_run["elevation_gain_m"] > 0 and new_run["name"] == "Apple Watch Running"
    assert list(new_run["sources"]) == ["apple"]
    # the oldest workouts: distance in miles on the <Workout>, the route as <Location>s inside it
    old_run = next(a for a in sorted(acts, key=lambda a: a["start_local"]) if a["sport"] == "run")
    assert 3 < old_run["distance_km"] < 15 and old_run["streams"]["latlng"]
    swim = next(a for a in acts if a["sport"] == "swim" and a["start_local"] > "2026-09-25")
    assert 1 < swim["distance_km"] < 3  # metres in the statistics
    assert "latlng" not in swim["streams"] and swim["streams"]["heartrate"]
    assert all(a["moving_time_s"] > 0 for a in by_day.values())


def test_wellness_one_source_per_night_and_no_double_steps(parsed):
    w = ah.wellness_days(parsed)
    day = w["2026-10-05"]
    assert day["deep_sleep_h"] > 0 and day["rem_sleep_h"] > 0 and day["light_sleep_h"] > 0
    # the Watch's stages, not the iPhone's "in bed" (which is longer and would be counted twice)
    assert abs(day["sleep_h"] - (day["deep_sleep_h"] + day["light_sleep_h"] + day["rem_sleep_h"])) < 0.05
    assert day["sleep_start"].startswith("2026-10-04T") and day["sleep_end"].startswith("2026-10-05T")
    assert 40 < day["sleep_hr"] < 70 and 10 < day["sleep_resp"] < 18 and 90 <= day["spo2_avg"] <= 100
    assert day["resting_hr"] and day["hrv_sdnn"] and day["intensity_min"]
    # steps: the Watch counted 6% more than the iPhone; the sum of both would be about double
    phone_and_watch = sum(
        per_source for (d, k), src in parsed.counters.items() if d == "2026-10-05" and k == "steps" for per_source in src.values()
    )
    assert day["steps"] < phone_and_watch * 0.6
    oldest = w[min(w)]
    assert oldest["sleep_h"] > 4 and "deep_sleep_h" not in oldest  # before iOS 16: asleep without stages
    assert any("vo2max" in v for v in w.values())


def test_intraday_rows_have_series_and_the_night(parsed):
    rows = ah.intraday_days(parsed, ah.wellness_days(parsed))
    row = rows["2026-10-05"]
    assert row["source"] == "apple" and row["hr"] and row["resp"]
    assert row["sleep"]["start"] < 0 < row["sleep"]["end"]  # fell asleep the evening before
    assert {lvl for *_, lvl in row["sleep"]["stages"]} <= {0, 1, 2, 3}
    assert all(0 <= m < 1440 for m, _ in row["hr"])


def test_entities_are_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE HealthData [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]><HealthData>&b;</HealthData>'
    with pytest.raises(ah.NotAnExport):
        ah.read_export(io.BytesIO(bomb))


def test_not_an_export():
    with pytest.raises(ah.NotAnExport):
        ah.read_export(io.BytesIO(b'<?xml version="1.0"?><gpx></gpx>'))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("photo.jpg", b"x")
    with pytest.raises(ah.NotAnExport):
        ah.read_export(io.BytesIO(buf.getvalue()))


def test_the_old_simple_export_xml_alone():
    """The shape of an export from 2016-2019 (from simonw/healthkit-to-sqlite's test data): inline route, miles."""
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_US">
 <ExportDate value="2019-07-19 10:36:11 -0700"/>
 <Record type="HKQuantityTypeIdentifierHeartRate" sourceName="Apple Watch" unit="count/min" creationDate="2016-11-14 07:30:35 -0700" startDate="2016-11-14 07:28:55 -0700" endDate="2016-11-14 07:28:55 -0700" value="142"/>
 <Workout workoutActivityType="HKWorkoutActivityTypeRunning" duration="5.19412346680959" durationUnit="min" totalDistance="0.4971749504535062" totalDistanceUnit="mi" totalEnergyBurned="48.74" totalEnergyBurnedUnit="kcal" sourceName="Apple Watch" sourceVersion="3.1" creationDate="2016-11-14 07:33:49 -0700" startDate="2016-11-14 07:25:41 -0700" endDate="2016-11-14 07:30:52 -0700">
  <MetadataEntry key="HKTimeZone" value="America/Los_Angeles"/>
  <WorkoutRoute sourceName="iPhone" sourceVersion="10.1.1" creationDate="2016-11-14 07:33:54 -0700" startDate="2016-11-14 07:25:44 -0700" endDate="2016-11-14 07:30:51 -0700">
   <Location date="2016-11-14 07:25:44 -0700" latitude="37.7777" longitude="-122.426" altitude="21.2694" horizontalAccuracy="2.4" verticalAccuracy="1.6" course="-1" speed="2.48"/>
   <Location date="2016-11-14 07:26:44 -0700" latitude="37.7790" longitude="-122.426" altitude="21.0" horizontalAccuracy="2.4" verticalAccuracy="1.6" course="-1" speed="2.48"/>
  </WorkoutRoute>
 </Workout>
</HealthData>"""
    x = ah.read_export(io.BytesIO(xml))
    (run,) = ah.activities(x)
    assert run["start_local"] == "2016-11-14T07:25:41" and run["start_utc"] == "2016-11-14T14:25:41Z"
    assert run["distance_km"] == 0.8 and run["moving_time_s"] == 312 and run["avg_hr"] == 142
    assert len(run["streams"]["latlng"]) == 2


def scope():
    e = db.connect(new_database_url())
    db.create_schema(e)
    return db.Scope(e, 1)


def test_apply_stores_everything_and_again_changes_nothing(parsed):
    s = scope()
    first = apply(s, parsed, "export.zip")
    assert first["added"] == first["workouts"] > 30 and first["merged"] == 0
    assert first["nights"] > 40 and first["staged_nights"] > 20 and first["intraday_days"] == 46
    acts = db.load_activities(s)
    assert len(acts) == first["workouts"]
    # the stored values, not only the parsed ones: every source needs a place in tools/store.py's priorities
    run = next(a for a in acts if a["sport"] == "run" and not a.get("indoor"))
    assert run["distance_km"] > 3 and run["moving_time_s"] > 600 and run["avg_hr"] > 100 and run["name"] == "Apple Watch Running"
    w = db.load_wellness(s)
    assert w["2026-10-05"]["source"] == "apple"
    assert db.get_intraday(s, "2026-10-05")["source"] == "apple"
    again = apply(s, parsed, "export.zip")
    assert again["added"] == 0 and again["merged"] == again["workouts"]
    assert len(db.load_activities(s)) == len(acts)


def test_garmin_stays_leading(parsed):
    s = scope()
    db.write_wellness(s, "2026-10-05", {"sleep_h": 7.1, "resting_hr": 47, "body_battery_high": 88})
    db.write_intraday(s, "2026-10-05", {"hr": [[0, 50]]})
    run = next(a for a in ah.activities(parsed) if a["sport"] == "run" and a["start_local"] > "2026-09-25")
    run_day = run["start_local"][:10]
    db.upsert_activity(
        s,
        {
            "start_utc": run["start_utc"].replace(":00Z", ":30Z"),
            "start_local": run["start_local"],
            "sport": "run",
            "name": "Amsterdam Running",
            "distance_km": 10.0,
            "sources": {"garmin": {"id": 1}},
        },
    )
    out = apply(s, parsed)
    assert out["kept_garmin_days"] == 1
    day = db.load_wellness(s)["2026-10-05"]
    assert day["sleep_h"] == 7.1 and day["resting_hr"] == 47 and day["hrv_sdnn"]  # Garmin kept, Apple filled the gap
    assert "source" not in day
    assert db.get_intraday(s, "2026-10-05") == {"hr": [[0, 50]]}
    merged = next(a for a in db.load_activities(s) if a["start_local"][:10] == run_day and a["sport"] == "run")
    assert merged["name"] == "Amsterdam Running" and set(merged["sources"]) == {"garmin", "apple"}

    gone = remove(s)
    assert gone["removed"] == out["workouts"] - 1 and gone["changed"] == 1
    assert [a["sources"].keys() for a in db.load_activities(s)] == [{"garmin": {}}.keys()]
    assert set(db.load_wellness(s)) == {"2026-10-05"}  # Garmin's day stays
    assert db.intraday_days(s) == ["2026-10-05"]


def test_upload_through_the_api(client, engine, export_zip):  # noqa: F811
    login(client)
    r = client.post(
        "/api/apple/import", params={"name": "export.zip"}, content=export_zip, headers={"content-type": "application/octet-stream"}
    )
    assert r.status_code == 202, r.text
    for _ in range(200):
        state = client.get("/api/apple/import").json()
        if not state["running"]:
            break
        time.sleep(0.1)
    last = state["last"]
    assert last["status"] == "done" and last["workouts"] > 30 and last["file"] == "export.zip", last
    assert last["first"] <= "2026-08-22" and last["last"] == "2026-10-05"
    o = client.get("/api/onboarding").json()
    assert o["status"]["apple"]["imported"] and o["steps"]["garmin"] and o["device"] == "apple"
    trends = client.get("/api/trends").json()
    assert trends["sleep_stages"] and trends["vo2max"]
    day = client.get("/api/wellness/day", params={"day": "2026-10-05"}).json()
    assert day["series"]["hr"] and day["sleep"]["stages"]
    assert day["night"] and 40 < day["night"]["avg"] < 70  # a reading every 4-7 minutes is enough for the night

    assert client.delete("/api/apple/import").json()["removed"] > 30
    assert client.get("/api/apple/import").json()["last"] is None


def test_wrong_files_are_refused(client):  # noqa: F811
    login(client)
    post = lambda data: client.post("/api/apple/import", content=data, headers={"content-type": "application/octet-stream"})  # noqa: E731
    assert post(b"").status_code == 400
    assert post(b"\x89PNG not an export").status_code == 422
    r = post(b"PK\x03\x04 broken zip")  # refused before the background work: the zip is checked first
    assert r.status_code == 422 and r.json()["code"] == "not_an_export"
    r = post(b"<?xml version='1.0'?><Broken")
    assert r.status_code == 202
    for _ in range(100):
        state = client.get("/api/apple/import").json()
        if not state["running"]:
            break
        time.sleep(0.05)
    assert state["last"]["status"] == "failed" and state["last"]["error"] == "not_an_export"


def wait_done(c):
    for _ in range(300):
        state = c.get("/api/apple/import").json()
        if not state["running"]:
            return state
        time.sleep(0.1)
    raise AssertionError("import still running")


@pytest.fixture
def chunked(engine, tmp_path):  # noqa: F811
    """An app whose Apple uploads go in 64 kB parts, so the test export needs many."""
    from fastapi.testclient import TestClient

    from api.apple import AppleImports
    from api.main import create_app
    from tests.test_api import make_settings

    app = create_app(engine=engine, settings=make_settings())
    imports = app.state.apple
    imports.chunk_size, imports.dir = 64 * 1024, tmp_path / "uploads"
    assert isinstance(imports, AppleImports)
    c = TestClient(app)
    login(c)
    return c, imports


def put(c, upload_id, index, data):
    return c.put(f"/api/apple/upload/{upload_id}/{index}", content=data, headers={"content-type": "application/octet-stream"})


def test_chunked_upload_imports_like_the_single_one(chunked, export_zip):
    c, imports = chunked
    start = c.post("/api/apple/upload", json={"name": "export.zip", "size": len(export_zip)})
    assert start.status_code == 201
    up, size = start.json()["upload_id"], start.json()["chunk_size"]
    parts = [export_zip[i : i + size] for i in range(0, len(export_zip), size)]
    assert len(parts) > 3
    assert c.post(f"/api/apple/upload/{up}/finish").json()["code"] == "upload_incomplete"
    assert put(c, up, 1, parts[1]).json() == {
        "detail": "verkeerd deel; verwacht deel 0",
        "code": "upload_out_of_order",
        "params": {"expected": 0},
    }
    for i, part in enumerate(parts):
        assert put(c, up, i, part).status_code == 200
        if i == 1:  # the answer got lost: the browser sends the same part again
            assert put(c, up, 1, part).json()["received"] == 2 * size
    r = c.post(f"/api/apple/upload/{up}/finish")
    assert r.status_code == 202, r.text
    last = wait_done(c)["last"]
    assert last["status"] == "done" and last["workouts"] > 30 and last["file"] == "export.zip"
    assert not list(imports.dir.glob("*"))  # the parts are gone once imported
    assert c.post(f"/api/apple/upload/{up}/finish").status_code == 404


def test_chunk_sizes_and_totals_are_checked(chunked):
    c, imports = chunked
    size = imports.chunk_size
    assert c.post("/api/apple/upload", json={"size": 0}).json()["code"] == "upload_empty"
    r = c.post("/api/apple/upload", json={"size": imports.max_bytes + 1})
    assert r.status_code == 413 and r.json()["code"] == "upload_too_large"
    up = c.post("/api/apple/upload", json={"size": size + 10}).json()["upload_id"]
    r = put(c, up, 0, b"PK" + b"x" * (size - 10))  # short part
    assert r.status_code == 422 and r.json()["code"] == "upload_size_mismatch"
    assert put(c, up, 0, b"x" * (size + 1)).json()["code"] == "upload_size_mismatch"  # longer than a part
    assert put(c, up, 0, b"x" * size).status_code == 200
    assert put(c, up, 1, b"x" * 11).json()["code"] == "upload_size_mismatch"  # beyond the declared size
    assert put(c, up, 1, b"x" * 10).status_code == 200
    assert put(c, up, 2, b"x").json()["code"] == "upload_out_of_order"
    r = c.post(f"/api/apple/upload/{up}/finish")
    assert r.status_code == 422 and r.json()["code"] == "not_an_export"
    assert not list(imports.dir.glob("*"))


def test_uploads_belong_to_their_user_and_expire(chunked, engine):  # noqa: F811
    from fastapi.testclient import TestClient

    c, imports = chunked
    up = c.post("/api/apple/upload", json={"size": 100}).json()["upload_id"]
    c.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    other = TestClient(c.app)
    other.post("/api/register", json={"username": "anna", "email": "anna@example.org", "password": "anna-wachtwoord-1", "consent": True})
    assert other.get("/api/me").json()["username"] == "anna"
    assert put(other, up, 0, b"x" * 100).status_code == 404  # someone else's id is as good as none
    assert other.post(f"/api/apple/upload/{up}/finish").status_code == 404
    assert other.delete(f"/api/apple/upload/{up}").status_code == 404
    # a second upload of the same user replaces the first
    up2 = c.post("/api/apple/upload", json={"size": 100}).json()["upload_id"]
    assert put(c, up, 0, b"x" * 100).status_code == 404 and len(list(imports.dir.glob("*.part"))) == 1
    imports.ttl_s = 0  # abandoned: removed on the next look
    time.sleep(0.01)
    assert put(c, up2, 0, b"x" * 100).status_code == 404
    assert not list(imports.dir.glob("*.part"))


def test_cancel_removes_the_parts(chunked):
    c, imports = chunked
    up = c.post("/api/apple/upload", json={"size": 100}).json()["upload_id"]
    assert c.delete(f"/api/apple/upload/{up}").json() == {"ok": True}
    assert not list(imports.dir.glob("*.part"))


def test_apple_zip_bomb_is_refused(client):  # noqa: F811
    login(client)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("apple_health_export/export.xml", b"<HealthData>" + b" " * (50 * 1024 * 1024))
    r = client.post("/api/apple/import", content=buf.getvalue(), headers={"content-type": "application/octet-stream"})
    assert r.status_code == 422 and r.json()["code"] == "not_an_export"


def test_onboarding_device_choice(client):  # noqa: F811
    login(client)
    assert client.put("/api/onboarding", json={"device": "apple"}).json()["device"] == "apple"
    assert client.put("/api/onboarding", json={"device": "fitbit"}).status_code == 400
