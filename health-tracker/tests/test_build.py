import json
from datetime import date

from tests.helpers import square_loop
from tools.build import build
from tools.store import upsert_activity


def _run(day, seed):
    return {
        "start_utc": f"{day}T06:00:00Z",
        "start_local": f"{day}T08:00:00",
        "sport": "run",
        "name": "Ochtendloop",
        "distance_km": 4.0,
        "moving_time_s": 1300,
        "avg_hr": 148,
        "streams": {"latlng": square_loop(noise_m=5, seed=seed)},
        "sources": {"strava": {"id": seed, "raw": {}}},
    }


def _seed(root):
    for i, day in enumerate(["2026-09-20", "2026-09-24", "2026-09-28"]):
        upsert_activity(root, _run(day, i))
    (root / "data" / "sync_state.json").write_text(json.dumps({"last_sync_local": "2026-09-30 06:02"}))


def test_build_writes_routes_and_summaries(tmp_path):
    _seed(tmp_path)
    build(tmp_path, today=date(2026, 9, 30))
    routes = json.loads((tmp_path / "routes" / "routes.json").read_text())
    assert len(routes) == 1 and routes[0]["runs"] == 3
    assert "4.0 km loop (r1)" in (tmp_path / "routes" / "routes.md").read_text()
    assert "Laatste sync: 2026-09-30 06:02" in (tmp_path / "summary" / "this-week.md").read_text()
    assert (tmp_path / "summary" / "last-90-days.md").exists()


def test_build_keeps_route_names_given_by_user(tmp_path):
    _seed(tmp_path)
    build(tmp_path, today=date(2026, 9, 30))
    path = tmp_path / "routes" / "routes.json"
    routes = json.loads(path.read_text())
    routes[0]["name"] = "Parkrondje"
    path.write_text(json.dumps(routes))
    build(tmp_path, today=date(2026, 9, 30))
    assert json.loads(path.read_text())[0]["name"] == "Parkrondje"
    assert "Parkrondje" in (tmp_path / "routes" / "routes.md").read_text()


def test_build_without_data_still_writes_files(tmp_path):
    build(tmp_path, today=date(2026, 9, 30))
    assert "nog geen" in (tmp_path / "routes" / "routes.md").read_text().lower()
    assert "Laatste sync: nog nooit" in (tmp_path / "summary" / "this-week.md").read_text()


def test_build_stores_own_zone_seconds_on_each_activity(tmp_path):
    rec = _run("2026-09-20", 1)
    rec["streams"]["heartrate"] = [140, 150, 150]
    rec["streams"]["time"] = [0, 10, 20]
    path = upsert_activity(tmp_path, rec)
    (tmp_path / "zones.json").write_text(json.dumps({"run": {"bounds": [149, 158, 166, 175]}}))
    build(tmp_path, today=date(2026, 9, 30))
    assert json.loads(path.read_text())["hr_zones_s"] == {"Z1": 10, "Z2": 10, "Z3": 0, "Z4": 0, "Z5": 0}
