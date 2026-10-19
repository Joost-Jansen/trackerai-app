"""Training-aware targets (tools/nutrition/targets.py): a day's type from what was done and what is planned, the day
before a race, and Vandaag's context line."""

from datetime import date

from tools.nutrition import targets

TODAY = date(2026, 10, 19)  # a Monday


def act(day, minutes, sport="run", km=None, zones=None, start="08:00", **extra):
    return {"start_local": f"{day}T{start}:00", "sport": sport, "moving_time_s": minutes * 60, "distance_km": km,
            "hr_zones_s": zones or {}, **extra}


def session(day, sport="run", kind=None, km=None, minutes=None, zone=None, status="planned"):
    return {"date": day, "sport": sport, "kind": kind, "distance_km": km, "duration_min": minutes, "target_zone": zone, "status": status}


def kind_of(day, activities=(), sessions=()):
    return targets.for_day(date.fromisoformat(day), TODAY, list(activities), list(sessions), 78)["day_type"]


def test_day_types_from_what_was_done():
    assert kind_of("2026-10-18") == "rest"
    assert kind_of("2026-10-18", [act("2026-10-18", 40, zones={"Z2": 2400})]) == "easy"
    assert kind_of("2026-10-18", [act("2026-10-18", 40, zones={"Z2": 1200, "Z4": 1200})]) == "moderate"  # short but hard
    assert kind_of("2026-10-18", [act("2026-10-18", 55)]) == "moderate"
    assert kind_of("2026-10-18", [act("2026-10-18", 65, zones={"Z3": 3000, "Z2": 900})]) == "long"  # an hour of tempo
    assert kind_of("2026-10-18", [act("2026-10-18", 120)]) == "long"
    assert kind_of("2026-10-18", [act("2026-10-18", 224, km=42.7)]) == "race"  # over three hours
    assert kind_of("2026-10-18", [act("2026-10-18", 90, sport="walking")]) == "rest"  # daily movement, not training


def test_a_planned_day_and_a_missed_session():
    plan = [session("2026-10-21", kind="Duurloop", km=20), session("2026-10-17", kind="Interval", minutes=60)]
    assert kind_of("2026-10-21", sessions=plan) == "long"  # 20 km at the default 6 min/km
    # with a history of 5 min/km the same 20 km is 100 minutes: still long
    history = [act("2026-10-10", 50, km=10)]
    assert targets.for_day(date(2026, 10, 21), TODAY, history, plan, 78)["sessions"][0]["minutes"] == 100
    assert kind_of("2026-10-17", sessions=plan) == "rest"  # in the past only what was done counts


def test_today_counts_what_was_done_and_what_is_still_planned():
    plan = [session("2026-10-19", kind="Tempo", minutes=30, status="done"), session("2026-10-19", sport="swim", minutes=45)]
    done = [act("2026-10-19", 30, zones={"Z3": 1800})]
    t = targets.for_day(TODAY, TODAY, done, plan, 78)
    assert [x["done"] for x in t["sessions"]] == [True, False] and t["day_type"] == "long"  # 75 min, hard


def test_the_day_before_a_race_eats_for_it_and_ranges_follow_the_weight():
    plan = [session("2026-10-20", kind="Marathon", km=42.2)]
    t = targets.for_day(TODAY, TODAY, [], plan, 78)
    assert (t["own_type"], t["day_type"]) == ("rest", "race")
    assert t["carbs_per_kg"] == [8.0, 12.0] and t["carbs_g"] == [624, 936] and t["protein_g"] == [125, 156]
    assert t["tomorrow"] == {"day_type": "race", "sport": "run", "kind": "Marathon", "distance_km": 42.2, "minutes": 253}
    assert targets.context(t, [], "07:00") == {"line": "tomorrow", **t["tomorrow"], "carbs_per_kg": [8.0, 12.0]}
    # a long run tomorrow: today at least a moderate day's carbohydrate
    t = targets.for_day(TODAY, TODAY, [], [session("2026-10-20", kind="Duurloop", km=20)], None)
    assert (t["own_type"], t["day_type"]) == ("rest", "moderate") and t["carbs_per_kg"] == [5.0, 7.0] and t["carbs_g"] is None
    assert t["tomorrow"]["day_type"] == "long"
    # a long day stays long before another one
    t = targets.for_day(TODAY, TODAY, [act("2026-10-19", 120)], [session("2026-10-20", kind="Duurloop", km=20)], 70)
    assert t["day_type"] == "long"


def test_after_training_line_lasts_a_few_hours():
    done = [act("2026-10-19", 70, start="07:00", zones={"Z2": 4200})]
    t = targets.for_day(TODAY, TODAY, done, [], 78)
    assert targets.context(t, done, "09:00") == {"line": "after_training"}
    assert targets.context(t, done, "13:00") is None  # more than four hours after 08:10
    assert targets.context(t, done, "06:00") is None
    easy = [act("2026-10-19", 30, start="07:00")]
    assert targets.context(targets.for_day(TODAY, TODAY, easy, [], 78), easy, "08:00") is None


def test_per_kg():
    assert targets.per_kg(312, 78) == 4.0 and targets.per_kg(None, 78) is None and targets.per_kg(100, None) is None
