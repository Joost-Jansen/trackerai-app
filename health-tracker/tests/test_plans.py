from datetime import date

from api.plans import match_sessions, parse_date, parse_minutes, parse_table, parse_zone, weekly_summary, zone_compliance

MD = """
| Datum | Sport | Type | Km | Zone | Omschrijving |
|---|---|---|---|---|---|
| 6-10-2026 | Lopen | Duurloop | 14 | Z2 | rustig |
| 7 okt | rust | | | | |
| 2026-10-08 | fietsen | | 40,5 | 2-3 | |
| morgen | lopen | | 5 | | |
"""


def test_parse_markdown_table():
    items, warnings = parse_table(MD, 2026)
    assert [(s["date"], s["sport"]) for s in items] == [("2026-10-06", "run"), ("2026-10-07", "rest"), ("2026-10-08", "ride")]
    assert items[0]["distance_km"] == 14 and items[0]["target_zone"] == "Z2" and items[0]["description"] == "rustig"
    assert items[2]["distance_km"] == 40.5 and items[2]["target_zone"] == "Z2-Z3"
    assert len(warnings) == 1 and "morgen" in warnings[0]


def test_parse_csv_semicolon_and_sport_from_type():
    items, _ = parse_table("datum;type;duur\n06/10/2026;Duurloop;1:10\n07/10/2026;Zwemmen techniek;45 min", 2026)
    assert [(s["sport"], s["duration_min"]) for s in items] == [("run", 70), ("swim", 45)]


def test_parse_without_date_column():
    items, warnings = parse_table("a,b\n1,2")
    assert items == [] and "datum" in warnings[0]


def test_small_parsers():
    assert parse_date("ma 12 jan", 2027) == "2027-01-12"
    assert parse_minutes("1,5 uur") == 90
    assert parse_zone("Z4") == "Z4" and parse_zone("") is None


def act(aid, day, sport="run", km=10.0, zones=None):
    return {"id": aid, "start_local": f"{day}T08:00:00", "sport": sport, "distance_km": km, "moving_time_s": 3000, "hr_zones_s": zones or {}}


def test_match_statuses_and_split_runs():
    sessions = [
        {"date": "2026-10-05", "sport": "run", "distance_km": 10},
        {"date": "2026-10-06", "sport": "run", "distance_km": 8},
        {"date": "2026-10-07", "sport": "rest"},
        {"date": "2026-10-08", "sport": "swim"},
        {"date": "2026-10-09", "sport": "run"},
    ]
    acts = [act("a", "2026-10-05", km=6), act("b", "2026-10-05", km=4), act("c", "2026-10-08", sport="swim", km=2)]
    out = match_sessions(sessions, acts, date(2026, 10, 8))
    assert [s["status"] for s in out] == ["done", "missed", "rest", "done", "planned"]
    assert out[0]["done"]["distance_km"] == 10 and set(out[0]["activity_ids"]) == {"a", "b"}
    weeks = weekly_summary(out, acts)
    assert weeks[0]["planned"] == 4 and weeks[0]["done"] == 2 and weeks[0]["missed"] == 1


def test_a_session_done_a_day_or_two_early_or_late_counts():
    # the swim planned for Tuesday was done on Monday, the run planned for Wednesday on Friday
    sessions = [{"date": "2026-10-06", "sport": "swim", "distance_km": 2}, {"date": "2026-10-07", "sport": "run", "distance_km": 10}]
    acts = [act("s", "2026-10-05", sport="swim", km=2.15), act("r", "2026-10-09", km=10)]
    out = match_sessions(sessions, acts, date(2026, 10, 9))
    assert [(s["status"], s["match"], s["done"]["date"]) for s in out] == [("done", "near", "2026-10-05"), ("done", "near", "2026-10-09")]


def test_same_day_wins_and_three_days_off_is_no_match():
    sessions = [
        {"date": "2026-10-05", "sport": "run", "distance_km": 10},
        {"date": "2026-10-06", "sport": "run", "distance_km": 8},
        {"date": "2026-10-10", "sport": "swim"},
    ]
    acts = [act("a", "2026-10-06", km=8), act("s", "2026-10-07", sport="swim", km=2)]
    out = match_sessions(sessions, acts, date(2026, 10, 7))
    # the Tuesday run is Tuesday's session, not Monday's; the swim is three days before Saturday
    assert [(s["status"], s.get("match")) for s in out] == [("missed", None), ("done", "day"), ("planned", None)]
    assert [c["id"] for c in out[2]["candidates"]] == ["s"]  # but can be linked by hand
    assert out[0]["candidates"] == []  # the run is already used


def test_the_nearest_day_then_the_closest_distance_wins():
    sessions = [{"date": "2026-10-06", "sport": "run", "distance_km": 10}, {"date": "2026-10-08", "sport": "run", "distance_km": 5}]
    acts = [act("a", "2026-10-07", km=5.2)]
    out = match_sessions(sessions, acts, date(2026, 10, 9))
    assert [s["status"] for s in out] == ["missed", "done"]


def test_links_by_hand_overrule_the_automatic_match():
    sessions = [{"date": "2026-10-06", "sport": "swim", "distance_km": 2}, {"date": "2026-10-12", "sport": "swim", "distance_km": 1.5}]
    acts = [act("s", "2026-10-05", sport="swim", km=2)]
    # not part of the plan: the Tuesday swim stays open, the activity is offered as a candidate
    out = match_sessions(sessions, acts, date(2026, 10, 5), {"s": None})
    assert out[0]["status"] == "planned" and [c["id"] for c in out[0]["candidates"]] == ["s"]
    # linked to the swim a week later, further than the automatic two days
    out = match_sessions(sessions, acts, date(2026, 10, 5), {"s": "2026-10-12"})
    assert [(s["status"], s.get("match")) for s in out] == [("planned", None), ("done", "manual")]
    # a link to a day without a swim session is ignored: automatic matching again
    out = match_sessions(sessions, acts, date(2026, 10, 5), {"s": "2026-10-09", "gone": "2026-10-06"})
    assert out[0]["match"] == "near"


def test_weeks_count_every_activity_of_a_plan_sport():
    sessions = [{"date": "2026-10-06", "sport": "run", "distance_km": 10}, {"date": "2026-10-20", "sport": "swim", "distance_km": 2}]
    acts = [act("a", "2026-10-06", km=10), act("b", "2026-10-08", km=6), act("s", "2026-10-14", sport="swim", km=1), act("x", "2026-10-07", sport="ride", km=40)]
    weeks = weekly_summary(match_sessions(sessions, acts, date(2026, 10, 21)), acts)
    assert [w["week"] for w in weeks] == ["2026-10-05", "2026-10-12", "2026-10-19"]  # the week in between too
    assert weeks[0]["done_km"] == 16 and weeks[0]["sports"] == {"run": {"planned_km": 10, "done_km": 16}}  # no ride in the plan
    assert weeks[1]["sports"] == {"swim": {"planned_km": 0, "done_km": 1}}


def test_zone_compliance_easy_counts_z1_too():
    a = {"hr_zones_s": {"Z1": 600, "Z2": 2400, "Z3": 1000, "Z4": 0, "Z5": 0}}
    assert zone_compliance(a, "Z2") == 75
    assert zone_compliance(a, "Z3-Z4") == 25


def test_route_suggestions_follow_the_session_sport():
    from datetime import date as _date

    from api.plans import suggest_routes

    def route(rid, sport, km):
        return {"id": rid, "name": rid, "sport": sport, "distance_km": km, "is_loop": True, "last_run": "2026-09-01", "start": [52.0, 5.0], "end": [52.0, 5.0]}

    routes = [route("r1", "run", 10.0), route("f1", "ride", 40.0)]
    sessions = [
        {"date": "2026-10-05", "sport": "run", "distance_km": 10.0, "status": "planned"},
        {"date": "2026-10-06", "sport": "ride", "distance_km": 40.0, "status": "planned"},
        {"date": "2026-10-07", "sport": "swim", "distance_km": 2.0, "status": "planned"},
    ]
    suggest_routes(sessions, routes, _date(2026, 10, 3))
    assert sessions[0]["route_suggestion"]["parts"] == ["r1"]
    assert sessions[1]["route_suggestion"]["parts"] == ["f1"]
    assert "route_suggestion" not in sessions[2]


def test_chosen_route_replaces_the_suggestion():
    from datetime import date as _date

    from api.plans import suggest_routes

    routes = [
        {"id": "r1", "name": "Park", "sport": "run", "distance_km": 10.0, "is_loop": True, "last_run": "2026-09-01", "start": [52.0, 5.0], "end": [52.0, 5.0]},
        {"id": "r2", "name": "Dijk", "sport": "run", "distance_km": 14.2, "is_loop": True, "last_run": "2026-09-01", "start": [52.0, 5.0], "end": [52.0, 5.0]},
    ]
    sessions = [
        {"date": "2026-10-05", "sport": "run", "distance_km": 10.0, "status": "planned", "route_id": "r2"},
        {"date": "2026-10-06", "sport": "run", "distance_km": 10.0, "status": "planned", "route_id": "unknown"},
    ]
    suggest_routes(sessions, routes, _date(2026, 10, 3))
    assert sessions[0]["route"] == {"id": "r2", "name": "Dijk", "distance_km": 14.2}
    assert "route_suggestion" not in sessions[0]
    assert "route" not in sessions[1] and sessions[1]["route_suggestion"]["parts"] == ["r1"]
