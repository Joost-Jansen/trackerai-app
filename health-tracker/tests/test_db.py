from tests.test_store import GARMIN_ACTIVITY, GARMIN_SPLITS, STRAVA_ACTIVITY, STRAVA_STREAMS
from tools import db
from tools.store import from_garmin, from_strava


def fresh():
    engine = db.connect("sqlite://")
    db.create_schema(engine)
    return db.Scope(engine, 1)


def test_upsert_merges_same_activity_from_two_sources():
    e = fresh()
    a = db.upsert_activity(e, from_strava(STRAVA_ACTIVITY, STRAVA_STREAMS))
    b = db.upsert_activity(e, from_garmin(GARMIN_ACTIVITY, GARMIN_SPLITS))
    assert a == b == "2026-09-28_0930_run"
    acts = db.load_activities(e)
    assert len(acts) == 1
    assert acts[0]["avg_hr"] == 150 and acts[0]["name"] == "Ochtendloop"
    assert set(acts[0]["sources"]) == {"garmin", "strava"}


def test_streams_are_stored_separately_and_loaded_on_demand():
    e = fresh()
    aid = db.upsert_activity(e, from_strava(STRAVA_ACTIVITY, STRAVA_STREAMS))
    assert "streams" not in db.load_activities(e)[0]
    assert db.load_streams(e, aid)["latlng"][0] == [52.09, 5.12]
    assert db.load_activities(e, with_streams=True)[0]["streams"]["heartrate"] == [120, 121, 122]


def test_activities_far_apart_stay_separate():
    e = fresh()
    later = dict(STRAVA_ACTIVITY, id=112, start_date="2026-09-28T17:00:00Z", start_date_local="2026-09-28T19:00:00Z")
    db.upsert_activity(e, from_strava(STRAVA_ACTIVITY, None))
    db.upsert_activity(e, from_strava(later, None))
    assert len(db.load_activities(e)) == 2


def test_derived_fields_can_be_updated():
    e = fresh()
    aid = db.upsert_activity(e, from_strava(STRAVA_ACTIVITY, None))
    db.set_derived(e, aid, hr_zones_s={"Z1": 1, "Z2": 2, "Z3": 0, "Z4": 0, "Z5": 0})
    assert db.load_activities(e)[0]["hr_zones_s"]["Z2"] == 2


def test_wellness_replaces_the_day_and_empty_removes_it():
    e = fresh()
    db.write_wellness(e, "2026-09-28", {"resting_hr": 131})
    db.write_wellness(e, "2026-09-28", {"steps": 500})
    assert db.load_wellness(e) == {"2026-09-28": {"steps": 500}}
    db.write_wellness(e, "2026-09-28", {})
    assert db.load_wellness(e) == {}


def test_settings_roundtrip():
    e = fresh()
    assert db.get_setting(e, "zones") is None
    db.set_setting(e, "zones", {"run": {"bounds": [1, 2, 3, 4]}})
    db.set_setting(e, "zones", {"run": {"bounds": [5, 6, 7, 8]}})
    assert db.get_setting(e, "zones") == {"run": {"bounds": [5, 6, 7, 8]}}


def test_documents_keep_body_and_author():
    e = fresh()
    db.put_document(e, "profile", "# Profiel", author="alice")
    doc = db.get_document(e, "profile")
    assert doc["body"] == "# Profiel" and doc["updated_by"] == "alice"
    assert db.get_document(e, "missing") is None


def test_entries_newest_first_and_filtered_by_kind():
    e = fresh()
    db.add_entry(e, kind="log", title="HM", body="1:50:00", author="agent", day="2026-09-27")
    db.add_entry(e, kind="analysis", title="Fitheid", body="...", author="agent", day="2026-09-30")
    db.add_entry(e, kind="log", title="Rust", body="...", author="alice", day="2026-09-30")
    logs = db.list_entries(e, kind="log")
    assert [x["title"] for x in logs] == ["Rust", "HM"]
    assert len(db.list_entries(e)) == 3


def test_plan_with_sessions():
    e = fresh()
    pid = db.create_plan(e, title="Marathon 3:45", goal="marathon onder 3:45", race="Rotterdam 2027-04-11", author="agent")
    db.add_sessions(e, pid, [
        {"date": "2026-10-06", "sport": "run", "kind": "duurloop", "distance_km": 16, "target_zone": "Z2"},
        {"date": "2026-10-04", "sport": "run", "kind": "recover", "duration_min": 40, "target_zone": "Z1"},
    ])
    plan = db.get_plan(e, pid)
    assert plan["status"] == "active"
    assert [s["date"] for s in plan["sessions"]] == ["2026-10-04", "2026-10-06"]
    assert db.active_plan(e)["id"] == pid


def test_new_active_plan_retires_the_previous_one():
    e = fresh()
    first = db.create_plan(e, title="A", author="agent")
    second = db.create_plan(e, title="B", author="agent")
    assert db.get_plan(e, first)["status"] == "finished"
    assert db.active_plan(e)["id"] == second


def test_routes_replace_all():
    e = fresh()
    db.save_routes(e, [{"id": "r1", "sport": "run", "name": "Park", "distance_km": 6.2}])
    db.save_routes(e, [{"id": "r2", "sport": "run", "name": "Dijk", "distance_km": 10.6}])
    assert [r["id"] for r in db.load_routes(e)] == ["r2"]


# --- removing one source (ending a connection) ---------------------------------------------------------------------

GARMIN_RIDE = {
    "start_utc": "2026-09-20T08:00:40Z", "start_local": "2026-09-20T10:00:40", "sport": "ride", "name": "Utrecht Cycling",
    "distance_km": 4.79, "moving_time_s": 598, "laps": [{"distance_km": 4.79}], "sources": {"garmin": {"id": 1}},
}
WAHOO_RIDE = {
    "start_utc": "2026-09-20T08:00:00Z", "start_local": "2026-09-20T10:00:00", "sport": "ride", "name": "Wahoo Cycling",
    "distance_km": 4.8, "moving_time_s": 600, "avg_power_w": 180, "laps": [{"distance_km": 2.4}, {"distance_km": 2.4}],
    "streams": {"time": [0, 1], "watts": [170, 190]}, "sources": {"wahoo": {"id": 77}},
}
WAHOO_ONLY = dict(WAHOO_RIDE, start_utc="2026-09-22T08:00:00Z", start_local="2026-09-22T10:00:00", sources={"wahoo": {"id": 78}})


def test_a_lower_priority_source_does_not_overwrite_garmin_laps_or_streams():
    e = fresh()
    aid = db.upsert_activity(e, dict(GARMIN_RIDE, streams={"time": [0], "heartrate": [120]}))
    db.upsert_activity(e, WAHOO_RIDE)
    a = db.load_activities(e)[0]
    assert a["laps"] == GARMIN_RIDE["laps"] and a["name"] == "Utrecht Cycling"
    assert a["avg_power_w"] == 180  # only Wahoo has it, so it fills in
    assert db.load_streams(e, aid) == {"time": [0], "heartrate": [120]}


def test_remove_source_takes_out_only_what_that_source_gave():
    e = fresh()
    aid = db.upsert_activity(e, WAHOO_RIDE)  # Wahoo first: its streams and laps, until Garmin comes
    db.upsert_activity(e, GARMIN_RIDE)
    only = db.upsert_activity(e, WAHOO_ONLY)
    db.put_fit(e, f"wahoo/{only}", b"fit")
    db.put_fit(e, f"wahoo/{aid}", b"fit")

    assert db.remove_source(e, "wahoo") == {"removed": 1, "changed": 1}

    acts = db.load_activities(e)
    assert [a["id"] for a in acts] == [aid]
    a = acts[0]
    assert set(a["sources"]) == {"garmin"}
    assert a["distance_km"] == 4.79 and a["moving_time_s"] == 598 and a["laps"] == GARMIN_RIDE["laps"]
    assert "avg_power_w" not in a
    assert a["start_utc"] == "2026-09-20T08:00:40Z"
    assert db.load_streams(e, aid) is None  # the streams were Wahoo's
    assert db.get_fit(e, f"wahoo/{aid}") is None and db.get_fit(e, f"wahoo/{only}") is None


def test_remove_source_leaves_other_users_alone():
    e = fresh()
    other = db.Scope(e.engine, 2)
    db.upsert_activity(other, WAHOO_ONLY)
    db.upsert_activity(e, WAHOO_ONLY)
    db.remove_source(e, "wahoo")
    assert db.load_activities(e) == [] and len(db.load_activities(other)) == 1


def test_streams_stored_before_owners_were_kept_stay_with_the_better_source(tmp_path):
    e = db.connect(f"sqlite:///{tmp_path / 'o.db'}")
    db.create_schema(e)
    s = db.Scope(e, 1)
    garmin = {"start_utc": "2026-10-02T13:59:00Z", "start_local": "2026-10-02T15:59:00", "sport": "ride", "distance_km": 52.2,
              "streams": {"time": [0, 1], "heartrate": [120, 121]}, "sources": {"garmin": {"id": 1}}}
    aid = db.upsert_activity(s, garmin)
    with e.begin() as c:  # what an activity stored before owners were kept looks like
        data = dict(c.execute(db.select(db.activities.c.data).where(db.activities.c.id == aid)).scalar_one())
        data.pop("owners", None)
        c.execute(db.activities.update().where(db.activities.c.id == aid).values(data=data))
    wahoo = {**garmin, "distance_km": 52.0, "streams": {"time": [0, 1], "heartrate": [99, 99]}, "sources": {"wahoo_api": {"id": 7}}}
    db.upsert_activity(s, wahoo)
    assert db.load_streams(s, aid)["heartrate"] == [120, 121]
    assert set(db.load_activities(s)[0]["sources"]) == {"garmin", "wahoo_api"}
