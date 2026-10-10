from api.history import activity_detail, decoupling, heatmap, km_splits, list_activities, track
from tests.helpers import square_loop

ZONES = {"run": {"bounds": [132, 147, 162, 176], "max_hr": 189}}


def run(aid, start, sport="run", **kw):
    return {"id": aid, "start_local": start, "sport": sport, "distance_km": 5.0, "moving_time_s": 1500, **kw}


def streams_for(n=200):
    loop = square_loop()[:n]
    return {
        "time": list(range(0, n * 5, 5)),
        "heartrate": [120 if i < n // 2 else 150 for i in range(n)],
        "velocity": [3.0] * n,
        "altitude": [1.0] * n,
        "distance": [i * 15.0 for i in range(n)],
        "latlng": loop,
    }


def test_list_filters_and_sorts_newest_first():
    acts = [run("a", "2026-09-01T08:00:00"), run("b", "2026-09-10T08:00:00"), run("c", "2026-09-05T08:00:00", sport="swim")]
    assert [a["id"] for a in list_activities(acts)] == ["b", "c", "a"]
    assert [a["id"] for a in list_activities(acts, sport="run")] == ["b", "a"]
    assert [a["id"] for a in list_activities(acts, start="2026-09-02", end="2026-09-09")] == ["c"]


def test_track_downsamples_and_colours_by_zone():
    t = track(streams_for(200), ZONES, "run", limit=50)
    assert len(t["latlng"]) == len(t["zone"]) == 50
    assert t["zone"][0] == "Z1" and t["zone"][-1] == "Z3"


def test_track_without_gps_is_none():
    assert track({"latlng": []}, ZONES, "run") is None


def test_km_splits_from_distance_stream():
    splits = km_splits(streams_for(200))  # 15 m per 5 s -> 1 km per ~333 s
    assert [s["km"] for s in splits] == [1, 2]
    assert 330 <= splits[0]["seconds"] <= 340


def test_decoupling_positive_when_hr_drifts_up_at_same_speed():
    s = streams_for(400)
    assert decoupling(s) == 20.0  # 3/120 vs 3/150
    assert decoupling(streams_for(20)) is None  # too short


def test_detail_has_track_route_neighbours_and_same_day():
    acts = [
        run("swim1", "2026-06-07T08:00:00", sport="swim"),
        run("r1", "2026-06-07T12:00:00"),
        run("r2", "2026-06-10T08:00:00"),
    ]
    routes = [{"id": "r9", "name": "Park", "distance_km": 5.0, "activity_ids": ["r1", "2026-06-10T08:00:00"]}]
    d = activity_detail("r1", acts, lambda aid: streams_for(), ZONES, routes)
    assert d["track"] and d["series"]["heartrate"]
    assert d["prev_id"] == "swim1" and d["next_id"] == "r2"
    assert [x["id"] for x in d["same_day"]] == ["swim1"]
    assert [h["id"] for h in d["route"]["history"]] == ["r1", "r2"]
    assert activity_detail("nope", acts, lambda aid: None, ZONES) is None


def test_heatmap_limits_points_and_skips_tracks_without_gps():
    acts = [run("a", "2026-09-01T08:00:00"), run("b", "2026-09-02T08:00:00")]
    out = heatmap(acts, lambda aid: streams_for() if aid == "a" else {}, limit=30)
    assert len(out["tracks"]) == 1 and len(out["tracks"][0]) == 30


def test_list_marks_runs_with_implausible_wrist_hr():
    acts = [run("a", "2026-09-01T08:00:00"), run("b", "2026-09-02T08:00:00")]
    out = {a["id"]: a for a in list_activities(acts, hr_flags={"b": ["low_start"]})}
    assert out["b"]["hr_flags"] == ["low_start"] and "hr_flags" not in out["a"]
    assert "hr_flags" not in list_activities(acts)[0]
