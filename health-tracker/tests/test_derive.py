from tests.helpers import square_loop
from tools import db
from tools.derive import derive

ZONES = {"run": {"bounds": [132, 147, 162, 176], "max_hr": 189}}


def run(day, seed, hr=(140, 150, 150)):
    return {
        "start_utc": f"{day}T06:00:00Z",
        "start_local": f"{day}T08:00:00",
        "sport": "run",
        "name": "Ochtendloop",
        "distance_km": 4.0,
        "moving_time_s": 1300,
        "avg_hr": 148,
        "streams": {"time": [0, 10, 20], "heartrate": list(hr), "latlng": square_loop(noise_m=5, seed=seed)},
        "sources": {"garmin": {"id": seed, "raw": {}}},
    }


def setup():
    e = db.connect("sqlite://")
    db.create_schema(e)
    e = db.Scope(e, 1)
    db.set_setting(e, "zones", ZONES)
    return e


def test_derive_stores_zone_seconds_with_own_zones():
    e = setup()
    aid = db.upsert_activity(e, run("2026-09-20", 1))
    derive(e)
    act = next(a for a in db.load_activities(e) if a["id"] == aid)
    # 140 bpm is Z2 (132-146), 150 bpm is Z3 (147-161)
    assert act["hr_zones_s"] == {"Z1": 0, "Z2": 10, "Z3": 10, "Z4": 0, "Z5": 0}


def test_derive_builds_routes_and_keeps_user_names():
    e = setup()
    for i, day in enumerate(["2026-09-20", "2026-09-24", "2026-09-28"]):
        db.upsert_activity(e, run(day, i))
    derive(e)
    routes = db.load_routes(e)
    assert len(routes) == 1 and routes[0]["runs"] == 3 and routes[0]["sport"] == "run"
    routes[0]["name"] = "Parkrondje"
    db.save_routes(e, routes)
    derive(e)
    assert db.load_routes(e)[0]["name"] == "Parkrondje"


def test_derive_without_zones_setting_leaves_activities_untouched():
    e = db.connect("sqlite://")
    db.create_schema(e)
    e = db.Scope(e, 1)
    db.upsert_activity(e, run("2026-09-20", 1))
    derive(e)
    assert "hr_zones_s" not in db.load_activities(e)[0]


def ride(day, seed, gps=True):
    return {
        "start_utc": f"{day}T07:00:00Z",
        "start_local": f"{day}T09:00:00",
        "sport": "ride",
        "name": "Fietsrit" if gps else "Indoor fietsen",
        "distance_km": 40.0,
        "moving_time_s": 4800,
        "avg_hr": 132,
        "streams": {"time": [0, 10, 20], "heartrate": [130, 132, 134], **({"latlng": square_loop(side_m=10_000, step_m=50, noise_m=5, seed=seed)} if gps else {})},
        "sources": {"garmin": {"id": 100 + seed, "raw": {}}},
    }


def test_derive_builds_ride_routes_next_to_run_routes():
    e = setup()
    for i, day in enumerate(["2026-09-20", "2026-09-24", "2026-09-28"]):
        db.upsert_activity(e, run(day, i))
    db.upsert_activity(e, ride("2026-09-21", 1))
    db.upsert_activity(e, ride("2026-09-27", 2))
    db.upsert_activity(e, ride("2026-09-25", 3, gps=False))  # indoor: no GPS, never a route
    result = derive(e)
    assert result["routes"] == {"run": 1, "ride": 1}
    by_sport = {r["sport"]: r for r in db.load_routes(e)}
    assert by_sport["run"]["id"] == "r1" and by_sport["run"]["median_pace"]
    assert by_sport["ride"]["id"] == "f1" and by_sport["ride"]["runs"] == 2
    assert by_sport["ride"]["name"] == "40.0 km bike loop (f1)" and by_sport["ride"]["median_speed_kmh"] == 30.0


def test_derive_keeps_run_routes_and_names_when_rides_arrive():
    e = setup()
    for i, day in enumerate(["2026-09-20", "2026-09-24", "2026-09-28"]):
        db.upsert_activity(e, run(day, i))
    derive(e)
    routes = db.load_routes(e)
    routes[0]["name"] = "Parkrondje"
    db.save_routes(e, routes)
    before = db.load_routes(e)[0]

    db.upsert_activity(e, ride("2026-09-21", 1))
    db.upsert_activity(e, ride("2026-09-27", 2))
    derive(e)
    after = {r["id"]: r for r in db.load_routes(e)}
    assert set(after) == {"r1", "f1"}
    assert after["r1"] == before

    after["f1"]["name"] = "Heuvelrug"
    db.save_routes(e, list(after.values()))
    derive(e)
    assert {r["id"]: r["name"] for r in db.load_routes(e)} == {"r1": "Parkrondje", "f1": "Heuvelrug"}


def test_derive_without_recurring_rides_has_no_ride_routes():
    e = setup()
    db.upsert_activity(e, ride("2026-09-21", 1))
    assert derive(e)["routes"] == {"run": 0, "ride": 0}
    assert db.load_routes(e) == []


def lead_in_run(day, seed):
    from tests.helpers import path

    r = run(day, 50 + seed)
    r["start_utc"], r["start_local"] = f"{day}T17:00:00Z", f"{day}T19:00:00"
    r["distance_km"] = 5.6
    r["streams"]["latlng"] = path([(-800, 0), (0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0), (-800, 0)])
    return r


def test_derive_stores_candidates_and_applies_decisions():
    e = setup()
    for i, day in enumerate(["2026-09-20", "2026-09-24", "2026-09-28"]):
        db.upsert_activity(e, run(day, i))
        db.upsert_activity(e, lead_in_run(day, i))
    result = derive(e)
    assert result["routes"]["run"] == 2 and result["candidates"] == 1
    pending = db.get_setting(e, "route_candidates")["candidates"]
    assert [(c["a"]["id"], c["b"]["id"]) for c in pending] == [("r1", "r2")]

    db.set_setting(e, "route_decisions", {"merge": [["r1", "r2"]], "separate": []})
    result = derive(e)
    assert result["routes"]["run"] == 1 and result["candidates"] == 0
    route = db.load_routes(e)[0]
    assert route["id"] == "r1" and route["runs"] == 6 and len(route["distance_variants"]) == 2
    assert db.get_setting(e, "route_candidates") == {"candidates": []}
