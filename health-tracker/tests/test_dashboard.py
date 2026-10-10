from datetime import date, timedelta

from api.dashboard import (
    ACWR_HIGH,
    ACWR_LOW,
    LOAD_MIN_DAYS,
    RAMP_HIGH,
    build_dashboard,
    form_status,
    load_indicator,
    next_race,
    plan_week,
    recent_items,
    today_tsb,
)
from api.plans import match_sessions

TODAY = date(2026, 9, 30)  # Wednesday; week = 2026-09-28 .. 2026-10-04
ZONES = {"run": {"bounds": [132, 147, 162, 176], "max_hr": 189}, "ride": {"bounds": [127, 141, 156, 169], "max_hr": 182}}


def act(day, sport="run", km=10.0, secs=3600, hr=140, z=None, name="Loop"):
    return {
        "id": f"{day}_0800_{sport}",
        "start_local": f"{day}T08:00:00",
        "sport": sport,
        "name": name,
        "distance_km": km,
        "moving_time_s": secs,
        "avg_hr": hr,
        "hr_zones_s": z or {"Z1": 0, "Z2": secs, "Z3": 0, "Z4": 0, "Z5": 0},
    }


def test_zone_share_this_week_and_month_per_sport():
    acts = [
        act("2026-09-29", z={"Z1": 600, "Z2": 1800, "Z3": 600, "Z4": 600, "Z5": 0}),
        act("2026-09-10", z={"Z1": 0, "Z2": 3600, "Z3": 0, "Z4": 0, "Z5": 0}),
        act("2026-09-30", sport="ride", z={"Z1": 3600, "Z2": 0, "Z3": 0, "Z4": 0, "Z5": 0}),
    ]
    d = build_dashboard(acts, {}, ZONES, TODAY, last_sync="x")
    assert d["zones"]["week"]["run"]["pct"]["Z2"] == 50.0
    assert d["zones"]["week"]["run"]["total_s"] == 3600
    assert d["zones"]["month"]["run"]["total_s"] == 7200
    assert d["zones"]["month"]["run"]["pct"]["Z2"] == 75.0
    assert d["zones"]["week"]["ride"]["pct"]["Z1"] == 100.0


def test_last_months_activities_are_not_in_this_month():
    d = build_dashboard([act("2026-08-31")], {}, ZONES, TODAY, last_sync="x")
    assert d["zones"]["month"] == {}


def test_volume_this_week_against_4_week_average():
    acts = [act("2026-09-29", km=10)] + [act(d, km=20) for d in ("2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22")]
    v = build_dashboard(acts, {}, ZONES, TODAY, last_sync="x")["volume"]
    assert v["week"]["run"] == {"count": 1, "km": 10.0, "seconds": 3600}
    assert v["avg4w"]["run"]["km"] == 20.0


def test_form_has_current_values_and_peak():
    acts = [act(f"2026-09-{d:02d}", hr=160) for d in range(1, 20)]
    f = build_dashboard(acts, {}, ZONES, TODAY, last_sync="x")["form"]
    assert f["ctl"] > 0 and f["atl"] > 0
    assert f["ctl_peak_date"] <= "2026-09-30"
    assert len(f["series"]) <= 91
    assert f["status"] in {"transition", "fresh", "neutral", "optimal", "high_risk"}
    assert f["pct"] == f["series"][-1]["form_pct"] == round(f["tsb"] / f["series"][-2]["ctl"] * 100)


def test_form_status_bands_are_a_share_of_fitness():
    assert [form_status(p) for p in (25, 10, 0, -10, -27, -31, None)] == ["transition", "fresh", "neutral", "optimal", "optimal", "high_risk", "neutral"]


def test_recent_activities_newest_first_without_streams():
    acts = [act("2026-09-20"), act("2026-09-29"), dict(act("2026-09-25"), streams={"latlng": [[1, 2]]})]
    recent = build_dashboard(acts, {}, ZONES, TODAY, last_sync="x")["recent"]
    assert [r["start_local"][:10] for r in recent] == ["2026-09-29", "2026-09-25", "2026-09-20"]
    assert all("streams" not in r for r in recent)


def test_recovery_last_7_days_and_resting_hr_baseline():
    wellness = {"2026-09-20": {"resting_hr": 50}, "2026-09-29": {"resting_hr": 44, "sleep_h": 7.5}}
    d = build_dashboard([], wellness, ZONES, TODAY, last_sync="2026-09-30 06:02")
    assert [r["date"] for r in d["recovery"]["days"]] == ["2026-09-29"]
    assert d["last_sync"] == "2026-09-30 06:02"


def test_empty_data_does_not_crash():
    d = build_dashboard([], {}, ZONES, TODAY, last_sync="nog nooit")
    assert d["zones"] == {"week": {}, "month": {}}
    assert d["form"] is None


def test_all_sports_total_sums_zone_time_of_each_sport():
    # each activity's hr_zones_s is already computed with its own sport's zones; "all" adds them up
    acts = [
        act("2026-09-29", z={"Z1": 600, "Z2": 1800, "Z3": 600, "Z4": 600, "Z5": 0}),
        act("2026-09-30", sport="ride", z={"Z1": 3600, "Z2": 0, "Z3": 0, "Z4": 0, "Z5": 0}),
    ]
    week = build_dashboard(acts, {}, ZONES, TODAY, last_sync="x")["zones"]["week"]
    assert week["all"]["total_s"] == 7200
    assert week["all"]["seconds"]["Z1"] == 4200
    assert week["all"]["pct"]["Z2"] == 25.0
    assert set(week) == {"all", "run", "ride"}


def test_all_sports_absent_without_heart_rate_data():
    assert "all" not in build_dashboard([], {}, ZONES, TODAY, last_sync="x")["zones"]["week"]


# --- form after the last sync -----------------------------------------------------------------

DAILY = [act(f"2026-09-{d:02d}", hr=160) for d in range(1, 21)]


def test_form_stops_at_the_last_synced_day_when_the_sync_is_older_than_yesterday():
    f = build_dashboard(DAILY, {}, ZONES, TODAY, last_sync="2026-09-20 06:02")["form"]
    assert f["series"][-1]["date"] == "2026-09-20"
    assert f["until"] == "2026-09-20" and f["stopped_at_sync"] is True
    # the unsynced days are not counted as rest: fatigue is the value at the last synced day
    fresh = build_dashboard(DAILY, {}, ZONES, date(2026, 9, 20), last_sync="2026-09-20 06:02")["form"]
    assert f["atl"] == fresh["atl"] and f["tsb"] == fresh["tsb"]


def test_form_runs_to_today_when_the_sync_is_from_yesterday_or_today():
    for sync in ("2026-09-29 06:02", "2026-09-30 06:02"):
        f = build_dashboard(DAILY, {}, ZONES, TODAY, last_sync=sync)["form"]
        assert f["series"][-1]["date"] == "2026-09-30" and f["until"] == "2026-09-30" and f["stopped_at_sync"] is False


def test_form_ignores_a_failure_suffix_and_unknown_sync_text():
    f = build_dashboard(DAILY, {}, ZONES, TODAY, last_sync="2026-09-20 06:02; mislukt: wellness")["form"]
    assert f["until"] == "2026-09-20"
    assert build_dashboard(DAILY, {}, ZONES, TODAY, last_sync="nog nooit")["form"]["until"] == "2026-09-30"


def test_no_form_when_the_last_sync_is_before_the_first_activity():
    assert build_dashboard([act("2026-09-25", hr=160)], {}, ZONES, TODAY, last_sync="2026-09-20 06:00")["form"] is None


# --- load indicator (acute vs chronic) ----------------------------------------------------------


def rows(loads):
    """A fitness series like tools.analytics.fitness_series from a list of daily loads."""
    out, ctl, atl, day = [], 0.0, 0.0, date(2026, 1, 1)
    for x in loads:
        tsb = ctl - atl
        ctl += (x - ctl) / 42
        atl += (x - atl) / 7
        out.append({"date": day.isoformat(), "load": x, "ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(tsb, 1)})
        day += timedelta(days=1)
    return out


def test_load_needs_four_weeks_of_history():
    load = load_indicator(rows([60] * (LOAD_MIN_DAYS - 1)))
    assert load["band"] == "unknown" and load["acwr"] is None and load["ramp"] is None


def test_steady_load_is_building():
    load = load_indicator(rows([60] * 200))
    assert load["band"] == "build" and ACWR_LOW <= load["acwr"] <= ACWR_HIGH and abs(load["ramp"]) < 1
    assert load["thresholds"] == {"low": ACWR_LOW, "high": ACWR_HIGH, "ramp_high": RAMP_HIGH}


def test_a_quiet_week_after_steady_training_is_low():
    load = load_indicator(rows([60] * 200 + [0] * 7))
    assert load["band"] == "low" and load["acwr"] < ACWR_LOW


def test_a_sudden_heavy_week_is_high_because_of_the_ratio():
    load = load_indicator(rows([40] * 200 + [120] * 7))
    assert load["band"] == "high" and load["reason"] == "ratio" and load["acwr"] > ACWR_HIGH


def test_a_fast_rise_in_fitness_is_high_because_of_the_ramp():
    # a high chronic load and a week clearly above it: the ratio stays inside the band, fitness rises fast
    load = load_indicator(rows([200] * 200 + [270] * 7))
    assert load["ramp"] > RAMP_HIGH and load["acwr"] <= ACWR_HIGH
    assert load["band"] == "high" and load["reason"] == "ramp"


def test_dashboard_form_has_the_load_indicator():
    f = build_dashboard(DAILY, {}, ZONES, TODAY, last_sync="x")["form"]
    assert f["load"]["band"] in {"unknown", "low", "build", "high"}


def test_todays_form_only_when_the_series_reaches_today():
    fresh = build_dashboard(DAILY, {}, ZONES, TODAY, last_sync="2026-09-30 06:02")["form"]
    stale = build_dashboard(DAILY, {}, ZONES, TODAY, last_sync="2026-09-20 06:02")["form"]
    assert today_tsb(fresh) == fresh["tsb"]
    assert today_tsb(stale) is None and today_tsb(None) is None


# --- this week against the plan ----------------------------------------------------------------


def sess(day, sport="run", km=None, minutes=None, kind=None):
    return {"date": day, "sport": sport, "kind": kind, "distance_km": km, "duration_min": minutes, "target_zone": None}


WEEK_PLAN = [
    sess("2026-09-27", km=15),  # last week
    sess("2026-09-28", km=10, minutes=60),
    sess("2026-09-29", "ride", minutes=90),
    sess("2026-09-30", km=8),
    sess("2026-10-02", "swim", km=2, minutes=45),
    sess("2026-10-03", "rest"),
    sess("2026-10-04", km=20),
    sess("2026-10-05", km=12),  # next week
]


def test_plan_week_planned_against_done_per_sport_and_session_counts():
    done = [act("2026-09-28", km=10.2, secs=3700), act("2026-09-27", km=15)]
    w = plan_week(match_sessions(WEEK_PLAN, done, TODAY), done, TODAY)
    assert (w["start"], w["end"]) == ("2026-09-28", "2026-10-04")
    assert w["sports"]["run"] == {"planned_km": 38.0, "done_km": 10.2, "planned_s": 3600, "done_s": 3700, "sessions": 3, "done": 1}
    assert w["sports"]["ride"] == {"planned_km": 0.0, "done_km": 0.0, "planned_s": 5400, "done_s": 0, "sessions": 1, "done": 0}
    assert w["sports"]["swim"]["planned_km"] == 2.0 and w["sports"]["swim"]["planned_s"] == 2700
    assert w["sessions"] == {"total": 5, "done": 1, "missed": 1, "upcoming": 3, "unsynced": 0}


def test_plan_week_without_sessions_this_week_is_empty():
    w = plan_week(match_sessions([sess("2026-10-12", km=10)], [], TODAY), [], TODAY)
    assert w["sports"] == {} and w["sessions"] == {"total": 0, "done": 0, "missed": 0, "upcoming": 0, "unsynced": 0}


def test_plan_week_does_not_call_sessions_after_the_last_sync_missed():
    sunday = date(2026, 10, 4)
    done = [act("2026-09-28", km=10.2, secs=3700)]
    w = plan_week(match_sessions(WEEK_PLAN, done, sunday), done, sunday, synced=date(2026, 9, 29))
    # 29 Sep (synced, nothing done) is missed; 30 Sep, 2 Oct and 4 Oct are not known yet
    assert w["sessions"] == {"total": 5, "done": 1, "missed": 1, "upcoming": 1, "unsynced": 2}


def test_plan_week_counts_every_activity_of_the_week_also_outside_a_session():
    # an extra run on Tuesday (no run planned within two days of it that is still open) and a swim on Monday 28 Sep,
    # four days before the planned swim on Friday 2 Oct: neither belongs to a session, both count for the week
    done = [act("2026-09-28", km=10.2, secs=3700), act("2026-09-29", km=5, secs=1800), act("2026-09-28", "swim", km=1.5, secs=2400), act("2026-09-27", km=15)]
    sessions = match_sessions(WEEK_PLAN, done, TODAY)
    w = plan_week(sessions, done, TODAY)
    assert w["sports"]["run"]["done_km"] == 15.2 and w["sports"]["run"]["done_s"] == 5500
    assert w["sports"]["swim"]["done_km"] == 1.5 and w["sports"]["swim"]["done"] == 0


def test_plan_week_shows_a_plan_sport_without_a_session_this_week_when_it_was_done():
    plan = [sess("2026-09-28", km=10), sess("2026-10-10", "swim", km=2)]
    done = [act("2026-09-29", "swim", km=2.2, secs=2700)]
    w = plan_week(match_sessions(plan, done, TODAY), done, TODAY)
    assert w["sports"]["swim"] == {"planned_km": 0.0, "done_km": 2.2, "planned_s": 0, "done_s": 2700, "sessions": 0, "done": 0}
    assert w["sessions"]["total"] == 1  # the swim is in the volume, not a session of this week


# --- race countdown -------------------------------------------------------------------------------


def test_race_from_the_race_field_with_its_distance():
    sessions = [sess("2026-10-01", km=10), sess("2026-10-18", km=42.2, kind="wedstrijd")]
    r = next_race({"race": "Marathon, 2026-10-18"}, sessions, TODAY)
    assert r == {"date": "2026-10-18", "days": 18, "name": "Marathon", "distance_km": 42.2, "sport": "run"}


def test_race_field_with_a_short_date_takes_the_plan_year():
    r = next_race({"race": "Stadsloop 18 okt"}, [sess("2026-09-01", km=5), sess("2026-10-18", km=10)], TODAY)
    assert r["date"] == "2026-10-18" and r["name"] == "Stadsloop" and r["distance_km"] == 10


def test_race_session_without_a_date_in_the_race_field():
    r = next_race({"race": "Halve marathon"}, [sess("2026-10-11", km=21.1, kind="Wedstrijd")], TODAY)
    assert r["date"] == "2026-10-11" and r["days"] == 11 and r["name"] == "Halve marathon"


def test_the_next_race_comes_first_and_only_the_goal_race_gets_the_name():
    sessions = [sess("2026-10-04", km=10, kind="wedstrijd"), sess("2026-10-18", km=42.2, kind="wedstrijd")]
    r = next_race({"race": "Marathon, 2026-10-18"}, sessions, TODAY)
    assert r["date"] == "2026-10-04" and r["name"] is None and r["distance_km"] == 10


def test_race_today_and_past_races():
    assert next_race({"race": "Marathon 2026-09-30"}, [], TODAY)["days"] == 0
    assert next_race({"race": "Marathon 2026-09-20"}, [sess("2026-09-20", km=42.2, kind="wedstrijd")], TODAY) is None


def test_no_race_without_a_date():
    assert next_race({"race": "Marathon"}, [sess("2026-10-04", km=10)], TODAY) is None
    assert next_race({"race": None}, [], TODAY) is None
    assert next_race({"race": "Marathon 31-02"}, [], TODAY) is None


# --- recent activities: split runs as one session, races marked -------------------------------------


def at(day, time, sport="run", km=5.0, secs=1800, hr=140, name="Loop", z=None, **extra):
    return {**act(day, sport=sport, km=km, secs=secs, hr=hr, z=z, name=name), "id": f"{day}_{time.replace(':', '')}_{sport}", "start_local": f"{day}T{time}:00", **extra}


def test_runs_with_a_short_break_are_one_item_with_their_parts():
    a = at("2026-09-29", "08:00", km=5, secs=1800, hr=140, max_hr=150, elevation_gain_m=10)
    b = at("2026-09-29", "08:40", km=3, secs=1200, hr=150, max_hr=165, elevation_gain_m=5)  # 10 min after the first ended
    items = recent_items([a, b])
    assert len(items) == 1
    item = items[0]
    assert item["id"] == a["id"] and item["parts"] == 2 and item["activity_ids"] == [a["id"], b["id"]]
    assert item["distance_km"] == 8.0 and item["moving_time_s"] == 3000 and item["avg_hr"] == 144
    assert item["max_hr"] == 165 and item["elevation_gain_m"] == 15
    assert item["hr_zones_s"]["Z2"] == 3000


def test_runs_far_apart_and_other_sports_stay_separate_newest_first():
    items = recent_items([at("2026-09-29", "08:00"), at("2026-09-29", "10:00"), at("2026-09-29", "08:35", sport="ride")])
    assert [i["start_local"][11:16] for i in items] == ["10:00", "08:35", "08:00"]
    assert all("parts" not in i for i in items)


def test_recent_keeps_six_items_after_merging():
    acts = [at(f"2026-09-{d:02d}", t) for d in range(20, 30) for t in ("08:00", "08:35")]
    items = recent_items(acts)
    assert len(items) == 6 and all(i["parts"] == 2 for i in items)
    assert items[0]["start_local"].startswith("2026-09-29")


def test_races_are_marked_by_name_heart_rate_and_triathlon_day():
    hard = {"Z1": 0, "Z2": 0, "Z3": 0, "Z4": 600, "Z5": 2400}
    items = recent_items(
        [
            at("2026-09-27", "09:00", name="Stadsloop wedstrijd"),
            at("2026-09-28", "09:00", km=10, secs=3000, z=hard),
            at("2026-09-29", "09:00"),
            at("2026-09-26", "08:00", sport="swim", km=1.5),
            at("2026-09-26", "09:00", sport="ride", km=40),
            at("2026-09-26", "10:30", km=10),
        ]
    )
    marked = {i["start_local"][:16]: i.get("race", False) for i in items}
    assert marked == {
        "2026-09-29T09:00": False,
        "2026-09-28T09:00": True,
        "2026-09-27T09:00": True,
        "2026-09-26T10:30": True,
        "2026-09-26T09:00": True,
        "2026-09-26T08:00": True,
    }


def test_a_session_is_a_race_when_one_of_its_parts_is():
    items = recent_items([at("2026-09-29", "08:00", name="Race"), at("2026-09-29", "08:35")])
    assert items[0]["parts"] == 2 and items[0]["race"] is True


def test_dashboard_recent_uses_the_merged_items():
    d = build_dashboard([at("2026-09-29", "08:00"), at("2026-09-29", "08:35")], {}, ZONES, TODAY, last_sync="x")
    assert len(d["recent"]) == 1 and d["recent"][0]["parts"] == 2


def test_a_marathon_pace_session_is_not_the_next_race():
    sessions = [sess("2026-10-07", km=8, kind="marathontempo"), sess("2026-10-11", km=12, kind="race pace"), sess("2026-10-18", km=42.2, kind="wedstrijd")]
    r = next_race({"race": ""}, sessions, date(2026, 10, 5))
    assert r["date"] == "2026-10-18" and r["days"] == 13
