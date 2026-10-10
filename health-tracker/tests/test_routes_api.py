from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes_api import make_router, route_detail, route_summary, suggest
from tests.helpers import HOME, FakeStore, fake_user_dep, square_loop

ROUTES = [
    {"id": "r1", "name": "Park", "distance_km": 4.0, "is_loop": True, "runs": 2, "last_run": "2026-09-10", "start": list(HOME), "end": list(HOME), "median_pace": "5:00", "median_hr": 140, "activity_ids": ["2026-09-01T08:00:00", "b"]},
    {"id": "r2", "name": "Lang", "distance_km": 8.0, "is_loop": True, "runs": 1, "last_run": "2026-08-01", "start": list(HOME), "end": list(HOME), "median_pace": "5:10", "median_hr": 142, "activity_ids": ["c"]},
]
ACTS = [
    {"id": "a", "start_local": "2026-09-01T08:00:00", "sport": "run", "distance_km": 4.0, "moving_time_s": 1300, "avg_hr": 142},
    {"id": "b", "start_local": "2026-09-10T08:00:00", "sport": "run", "distance_km": 4.0, "moving_time_s": 1200, "avg_hr": 138},
    {"id": "c", "start_local": "2026-08-01T08:00:00", "sport": "run", "distance_km": 8.0, "moving_time_s": 2500},
]


def streams(aid):
    return {"latlng": square_loop()} if aid != "c" else None


def test_summary_best_run_and_track_from_latest_run():
    s = route_summary(ROUTES[0], ACTS, streams, points=20)
    assert s["best"]["activity_id"] == "b" and s["best"]["pace_s_per_km"] == 300
    assert len(s["track"]) == 20


def test_detail_history_oldest_first():
    d = route_detail(ROUTES[0], ACTS, streams)
    assert [h["id"] for h in d["history"]] == ["a", "b"]
    assert d["history"][1]["m_per_beat"] == round(4000 / (1200 / 60 * 138), 3)


def test_suggest_prefers_single_route_and_adds_tracks():
    opts = suggest(ROUTES, ACTS, streams, 8.0, date(2026, 9, 30))
    assert opts[0]["parts"] == ["r2"] and opts[0]["names"] == ["Lang"]
    assert any(o["parts"] == ["r1", "r1"] for o in opts)
    assert opts[0]["tracks"]["r2"] == []  # no GPS for that run


@pytest.fixture
def client(monkeypatch):
    from api import routes_api

    saved = {}
    monkeypatch.setattr(routes_api.db, "save_routes", lambda scope, items: saved.update(items=items))
    app = FastAPI()
    app.include_router(make_router(lambda: date(2026, 9, 30), fake_user_dep(FakeStore(activities=ACTS, routes=ROUTES, streams=streams))))
    c = TestClient(app)
    c.saved = saved
    return c


def test_endpoints(client):
    assert [r["id"] for r in client.get("/api/routes").json()] == ["r1", "r2"]
    assert client.get("/api/routes/suggest?km=4").json()["options"][0]["parts"] == ["r1"]
    assert client.get("/api/routes/suggest?km=0").status_code == 422
    assert client.get("/api/routes/r9").status_code == 404
    assert client.patch("/api/routes/r1", json={"name": "Vondelpark"}).json()["name"] == "Vondelpark"
    assert client.saved["items"][0]["name"] == "Vondelpark"


RIDE = {"id": "f1", "sport": "ride", "name": "Heuvelrug", "distance_km": 40.0, "is_loop": True, "runs": 2, "last_run": "2026-09-20", "start": list(HOME), "end": list(HOME), "median_pace": None, "median_speed_kmh": 30.0, "median_hr": 130, "activity_ids": ["d", "e"]}
RIDE_ACTS = [
    {"id": "d", "start_local": "2026-09-13T09:00:00", "sport": "ride", "distance_km": 40.0, "moving_time_s": 5000, "avg_hr": 128},
    {"id": "e", "start_local": "2026-09-20T09:00:00", "sport": "ride", "distance_km": 40.0, "moving_time_s": 4800, "avg_hr": 132},
]


def test_summary_carries_sport_and_speed():
    s = route_summary(RIDE, RIDE_ACTS, streams)
    assert s["sport"] == "ride" and s["median_speed_kmh"] == 30.0
    assert s["best"]["activity_id"] == "e"
    assert route_summary(ROUTES[0], ACTS, streams)["sport"] == "run"  # stored without sport: a run


def test_suggest_is_per_sport():
    routes = ROUTES + [RIDE]
    acts = ACTS + RIDE_ACTS
    assert all(p.startswith("r") for o in suggest(routes, acts, streams, 8.0, date(2026, 9, 30)) for p in o["parts"])
    opts = suggest(routes, acts, streams, 80.0, date(2026, 9, 30), sport="ride")
    assert opts[0]["parts"] == ["f1", "f1"] and opts[0]["names"] == ["Heuvelrug", "Heuvelrug"]
    assert suggest(ROUTES, ACTS, streams, 40.0, date(2026, 9, 30), sport="ride") == []


@pytest.fixture
def mixed_client():
    app = FastAPI()
    app.include_router(make_router(lambda: date(2026, 9, 30), fake_user_dep(FakeStore(activities=ACTS + RIDE_ACTS, routes=ROUTES + [RIDE], streams=streams))))
    return TestClient(app)


def test_endpoints_per_sport(mixed_client):
    c = mixed_client
    assert [r["id"] for r in c.get("/api/routes?sport=ride").json()] == ["f1"]
    assert [r["id"] for r in c.get("/api/routes?sport=run").json()] == ["r1", "r2"]
    assert c.get("/api/routes/suggest?km=4").json()["options"][0]["parts"] == ["r1"]
    ride = c.get("/api/routes/suggest?km=120&sport=ride").json()
    assert ride["km"] == 120.0 and ride["options"][0]["parts"] == ["f1", "f1", "f1"]
    assert c.get("/api/routes/suggest?km=301&sport=ride").status_code == 422
    assert c.get("/api/routes/suggest?km=40&sport=ride&start=r1").status_code == 404  # start must be a route of that sport
    assert c.get("/api/routes/f1").json()["history"][0]["id"] == "d"


def test_medoid_is_the_main_track_and_others_are_variants():
    route = {**ROUTES[0], "medoid_id": "a"}
    s = route_summary(route, ACTS, streams, points=20)
    assert s["medoid_id"] == "a" and len(s["track"]) == 20
    assert [v["id"] for v in s["variants"]] == ["b"] and v_len(s) == 80


def v_len(s):
    return len(s["variants"][0]["track"])


# --- candidate pairs: "is this the same loop?" ----------------------------------------------------------

CAND_ROUTES = [
    {**ROUTES[0], "sport": "run", "name": "4.0 km loop (r1)", "activity_ids": ["a", "b"], "medoid_id": "a"},
    {"id": "r3", "sport": "run", "name": "Met de brug", "distance_km": 5.0, "is_loop": True, "runs": 1, "first_run": "2026-09-20", "last_run": "2026-09-20", "start": list(HOME), "end": list(HOME), "median_pace": "5:20", "median_hr": 140, "activity_ids": ["g"], "medoid_id": "g"},
]
CAND_ACTS = ACTS + [
    {"id": "g", "start_local": "2026-09-20T08:00:00", "sport": "run", "distance_km": 5.0, "moving_time_s": 1600, "avg_hr": 140},
    {"id": "h", "start_local": "2026-09-25T08:00:00", "sport": "run", "name": "Avondloop", "distance_km": 4.6, "moving_time_s": 1500, "avg_hr": 141},
]
PENDING = {
    "candidates": [
        {"a": {"id": "r1", "kind": "route", "name": "4.0 km loop (r1)", "distance_km": 4.0, "runs": 2}, "b": {"id": "r3", "kind": "route", "name": "Met de brug", "distance_km": 5.0, "runs": 1}, "sport": "run", "outcome": "candidate", "confidence": 0.7, "reason": "zelfde rondje met een extra lus of omweg"},
        {"a": {"id": "r1", "kind": "route", "name": "4.0 km loop (r1)", "distance_km": 4.0, "runs": 2}, "b": {"id": "h", "kind": "activity", "name": None, "distance_km": 4.6, "runs": 1, "date": "2026-09-25"}, "sport": "run", "outcome": "candidate", "confidence": 0.6, "reason": "zelfde rondje, ander startpunt"},
    ]
}


def _cand_streams(aid):
    return {"latlng": square_loop()}


@pytest.fixture
def cand_client(monkeypatch):
    from api import routes_api

    settings = {"route_candidates": PENDING}
    saved = {}
    monkeypatch.setattr(routes_api.db, "get_setting", lambda scope, key: settings.get(key))
    monkeypatch.setattr(routes_api.db, "set_setting", lambda scope, key, value: settings.update({key: value}))
    monkeypatch.setattr(routes_api.db, "save_routes", lambda scope, items: saved.update(items=items))
    app = FastAPI()
    app.include_router(make_router(lambda: date(2026, 9, 30), fake_user_dep(FakeStore(activities=CAND_ACTS, routes=CAND_ROUTES + [RIDE], streams=_cand_streams))))
    c = TestClient(app)
    c.settings, c.saved = settings, saved
    return c


def test_candidates_come_with_tracks_and_current_names(cand_client):
    out = cand_client.get("/api/routes/candidates").json()
    assert out["last_sync"] == "2026-10-01 06:00"
    pairs = out["candidates"]
    assert [(p["a"]["id"], p["b"]["id"]) for p in pairs] == [("r1", "r3"), ("r1", "h")]
    assert pairs[1]["reason_code"] is None and pairs[0]["confidence"] == 0.7
    assert pairs[0]["b"]["name"] == "Met de brug" and pairs[0]["a"]["last_run"] == "2026-09-10"
    assert pairs[1]["b"]["name"] == "Avondloop" and pairs[1]["b"]["date"] == "2026-09-25"
    assert len(pairs[0]["a"]["track"]) == 150 and len(pairs[1]["b"]["track"]) == 150
    assert cand_client.get("/api/routes/candidates?sport=ride").json()["candidates"] == []


def test_candidate_for_a_route_that_is_gone_is_left_out(cand_client):
    cand_client.settings["route_candidates"] = {"candidates": [dict(PENDING["candidates"][0], b={"id": "r9", "kind": "route"})]}
    assert cand_client.get("/api/routes/candidates").json()["candidates"] == []


def test_merge_answer_is_recorded_and_applied_right_away(cand_client):
    out = cand_client.post("/api/routes/candidates", json={"a": "r3", "b": "r1", "same": True}).json()
    assert out["applied"] is True and out["applied_on_next_sync"] is False and out["route"]["id"] == "r1"
    assert cand_client.settings["route_decisions"] == {"merge": [["r3", "r1"]], "separate": []}
    saved = {r["id"]: r for r in cand_client.saved["items"]}
    assert set(saved) == {"r1", "f1"}
    assert saved["r1"]["runs"] == 3 and saved["r1"]["name"] == "Met de brug" and [g["id"] for g in saved["r1"]["groups"]] == ["r1", "r3"]
    assert [(c["a"]["id"], c["b"]["id"]) for c in cand_client.settings["route_candidates"]["candidates"]] == [("r1", "h")]


def test_merge_of_a_single_activity(cand_client):
    out = cand_client.post("/api/routes/candidates", json={"a": "r1", "b": "h", "same": True}).json()
    assert out["applied"] is True
    r1 = next(r for r in cand_client.saved["items"] if r["id"] == "r1")
    assert r1["runs"] == 3 and "h" in r1["activity_ids"]


def test_separate_answer_is_recorded(cand_client):
    out = cand_client.post("/api/routes/candidates", json={"a": "r1", "b": "r3", "same": False}).json()
    assert out == {"applied": True, "applied_on_next_sync": False, "route": None, "remaining": 1}
    assert cand_client.settings["route_decisions"] == {"merge": [], "separate": [["r1", "r3"]]}
    assert "items" not in cand_client.saved


def test_answer_for_an_unknown_pair_is_404(cand_client):
    assert cand_client.post("/api/routes/candidates", json={"a": "r1", "b": "f1", "same": True}).status_code == 404


def test_merge_that_cannot_be_applied_now_waits_for_the_next_sync(cand_client):
    # the activity is gone from the list (e.g. cache): the decision is kept for derive
    cand_client.settings["route_candidates"] = {"candidates": [dict(PENDING["candidates"][1], b={"id": "zz", "kind": "activity"})]}
    out = cand_client.post("/api/routes/candidates", json={"a": "r1", "b": "zz", "same": True}).json()
    assert out["applied"] is False and out["applied_on_next_sync"] is True
    assert cand_client.settings["route_decisions"]["merge"] == [["r1", "zz"]]


def test_summary_has_length_variants():
    route = {**ROUTES[0], "distance_variants": [{"distance_km": 4.0, "runs": 2, "activity_ids": ["a", "b"], "last_run": "2026-09-10"}]}
    assert route_summary(route, ACTS, streams)["distance_variants"][0]["runs"] == 2
    # routes stored before length variants existed get them computed from their runs
    assert route_summary(ROUTES[0], ACTS, streams)["distance_variants"] == [{"distance_km": 4.0, "runs": 2, "activity_ids": ["a", "b"], "last_run": "2026-09-10"}]
