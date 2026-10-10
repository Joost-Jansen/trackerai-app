import json

from tests.test_store import STRAVA_ACTIVITY, STRAVA_STREAMS
from tools import db
from tools.migrate_files_to_db import migrate, split_log
from tools.store import from_strava, upsert_activity, write_wellness

LOG = """# Log september 2026

## 2026-09-30: marathonvoorspelling

- Doel 3:45.

## 2026-09-30: zones herzien

- Z2 132-146.
"""


def test_split_log_into_entries():
    items = split_log(LOG)
    assert [(i["day"], i["title"]) for i in items] == [("2026-09-30", "marathonvoorspelling"), ("2026-09-30", "zones herzien")]
    assert items[1]["body"].strip() == "- Z2 132-146."


def test_migrate_moves_files_into_database(tmp_path):
    upsert_activity(tmp_path, from_strava(STRAVA_ACTIVITY, STRAVA_STREAMS))
    write_wellness(tmp_path, "2026-09-28", {"sleep_h": 7.5})
    fit = tmp_path / "data" / "raw" / "fit" / "2026"
    fit.mkdir(parents=True)
    (tmp_path / "zones.json").write_text(json.dumps({"_note": "x", "run": {"bounds": [132, 147, 162, 176], "max_hr": 189}}))
    (tmp_path / "profile.md").write_text("# Profiel")
    (tmp_path / "goals.md").write_text("# Doelen")
    (tmp_path / "log").mkdir()
    (tmp_path / "log" / "2026-09.md").write_text(LOG)
    (tmp_path / "routes").mkdir()
    (tmp_path / "routes" / "routes.json").write_text(json.dumps([{"id": "r1", "name": "Park", "distance_km": 6.2}]))
    (tmp_path / "data" / "sync_state.json").write_text(json.dumps({"last_sync_local": "2026-09-30 20:42"}))

    engine = db.Scope(db.connect("sqlite://"), 1)
    migrate(tmp_path, engine)

    acts = db.load_activities(engine)
    assert len(acts) == 1 and db.load_streams(engine, acts[0]["id"])["latlng"]
    assert db.load_wellness(engine) == {"2026-09-28": {"sleep_h": 7.5}}
    assert db.get_setting(engine, "zones") == {"run": {"bounds": [132, 147, 162, 176], "max_hr": 189}}
    assert db.get_document(engine, "profile")["body"] == "# Profiel"
    assert db.get_document(engine, "goals")["body"] == "# Doelen"
    assert len(db.list_entries(engine, kind="log")) == 2
    assert db.load_routes(engine)[0]["sport"] == "run"
    assert db.get_setting(engine, "sync_state")["last_sync_local"] == "2026-09-30 20:42"


def test_migrate_twice_does_not_duplicate(tmp_path):
    upsert_activity(tmp_path, from_strava(STRAVA_ACTIVITY, None))
    (tmp_path / "log").mkdir()
    (tmp_path / "log" / "2026-09.md").write_text(LOG)
    engine = db.Scope(db.connect("sqlite://"), 1)
    migrate(tmp_path, engine)
    migrate(tmp_path, engine)
    assert len(db.load_activities(engine)) == 1
    assert len(db.list_entries(engine)) == 2
