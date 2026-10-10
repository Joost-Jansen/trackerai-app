from datetime import date

from api.trends import (
    sleep_stages,
    build_trends,
    goal_from_plan,
    hr_flags,
    insights,
    longest_runs,
    predictions,
    races,
    recent_records,
    records,
    recovery_daily,
    recovery_normals,
    recovery_weekly,
    standalone_runs,
    vo2max,
    weekly_volume,
    z2_pace,
)
from tests.test_hrquality import run_streams

ZONES = {"run": {"bounds": [132, 147, 162, 176], "max_hr": 189}}


def act(aid, start, sport="run", raw=None, **kw):
    a = {"id": aid, "start_local": start, "sport": sport, "distance_km": 10.0, "moving_time_s": 3000, "avg_hr": 140, **kw}
    if raw:
        a["sources"] = {"garmin": {"raw": raw}}
    return a


def z2_streams(speed=3.0, hr=140, n=200):
    return {"time": list(range(0, n * 5, 5)), "heartrate": [hr] * n, "velocity": [speed] * n}


def test_weekly_volume_fills_empty_weeks():
    out = weekly_volume([act("a", "2026-09-01T08:00:00"), act("b", "2026-09-16T08:00:00", sport="swim", distance_km=2.0)])
    assert [w["week"] for w in out] == ["2026-08-31", "2026-09-07", "2026-09-14"]
    assert out[1]["sports"] == {}
    assert out[2]["sports"]["swim"]["km"] == 2.0


def test_run_after_swim_is_not_standalone():
    acts = [act("s", "2026-06-07T08:00:00", sport="swim"), act("r", "2026-06-07T12:00:00"), act("r2", "2026-06-08T08:00:00")]
    assert [a["id"] for a in standalone_runs(acts)] == ["r2"]


def test_z2_pace_uses_only_z2_samples():
    acts = [act("a", "2026-09-01T08:00:00"), act("b", "2026-09-02T08:00:00")]
    streams = {"a": z2_streams(3.0), "b": z2_streams(4.0, hr=165)}
    out = z2_pace(acts, streams.get, ZONES)
    assert out == [{"week": "2026-08-31", "pace_s_per_km": 333, "runs": 1, "z2_seconds": 995}]


def test_records_progression_and_vo2max():
    acts = [
        act("a", "2026-01-01T08:00:00", raw={"fastestSplit_5000": 1500.4, "vO2MaxValue": 52}),
        act("b", "2026-02-01T08:00:00", raw={"fastestSplit_5000": 1550.0}),
        act("c", "2026-03-01T08:00:00", raw={"fastestSplit_5000": 1400.0, "vO2MaxValue": 54}),
    ]
    rec = records(acts)
    assert [r["activity_id"] for r in rec["5k"]] == ["a", "c"]
    assert rec["1k"] == []
    assert vo2max(acts) == [{"date": "2026-01-01", "value": 52}, {"date": "2026-03-01", "value": 54}]


def test_races_detect_triathlon_day_and_named_races():
    acts = [
        act("s", "2026-06-07T08:00:00", sport="swim"),
        act("b", "2026-06-07T09:00:00", sport="ride"),
        act("r", "2026-06-07T12:00:00"),
        act("x", "2026-07-01T08:00:00", name="Amsterdam - Benchmark Run"),
    ]
    out = races(acts)
    assert [r["sport"] for r in out] == ["triathlon", "run"]
    assert out[0]["activity_ids"] == ["s", "b", "r"]


NEW_NONE = {"sleep_resp": None, "sleep_stress": None, "bb_charged_sleep": None, "spo2_avg": None}


def test_recovery_weekly_averages():
    out = recovery_weekly({"2026-09-28": {"resting_hr": 48, "sleep_h": 6.0}, "2026-09-29": {"resting_hr": 50}})
    assert out == [{"week": "2026-09-28", "resting_hr": 49.0, "sleep_h": 6.0, "body_battery_high": None, "stress_avg": None, "hrv": None, **NEW_NONE}]


def test_sleep_stages_per_night_skip_days_without_stages():
    out = sleep_stages({
        "2026-10-05": {"sleep_h": 7.6, "deep_sleep_h": 1.8, "light_sleep_h": 4.0, "rem_sleep_h": 1.7, "awake_h": 0.7},
        "2026-10-04": {"steps": 9000},  # no night: left out
        "2026-10-03": {"deep_sleep_h": 1.5, "light_sleep_h": 4.5},  # no REM or awake recorded: 0
        "2026-09-14": {"sleep_h": 6.7, "deep_sleep_h": 0.8, "rem_sleep_h": 0.7},  # synced before light was stored
    })
    assert out == [
        {"date": "2026-09-14", "deep": 0.8, "light": 5.2, "rem": 0.7, "awake": 0},  # light = total - deep - REM
        {"date": "2026-10-03", "deep": 1.5, "light": 4.5, "rem": 0, "awake": 0},
        {"date": "2026-10-05", "deep": 1.8, "light": 4.0, "rem": 1.7, "awake": 0.7},
    ]


def test_recovery_daily_keeps_each_day_and_skips_empty_days():
    out = recovery_daily(
        {
            "2026-09-29": {"resting_hr": 50, "sleep_h": 7.256, "extra": 1},
            "2026-09-28": {"resting_hr": 48, "body_battery_high": 80},
            "2026-09-30": {"steps": 1000},
        }
    )
    assert out == [
        {"date": "2026-09-28", "resting_hr": 48, "sleep_h": None, "body_battery_high": 80, "stress_avg": None, "hrv": None, **NEW_NONE},
        {"date": "2026-09-29", "resting_hr": 50, "sleep_h": 7.26, "body_battery_high": None, "stress_avg": None, "hrv": None, **NEW_NONE},
    ]


def test_recovery_normals_are_the_median_of_the_last_60_days():
    wellness = {f"2026-09-{d:02d}": {"sleep_resp": 14.0 + d % 2, "resting_hr": 50} for d in range(1, 31)}
    out = recovery_normals(wellness, date(2026, 9, 30))
    assert out["sleep_resp"] == 14.5 and out["resting_hr"] == 50 and out["spo2_avg"] is None


def test_build_trends_shape():
    out = build_trends([act("a", "2026-09-01T08:00:00")], {}, ZONES, lambda aid: None, date(2026, 9, 3))
    assert set(out) >= {"form", "weekly", "z2_pace", "vo2max", "recovery_weekly", "recovery_daily", "records", "races"}
    assert out["form"][-1]["date"] == "2026-09-03"


def hard_run(aid, start, km=21.1, secs=6300):
    return act(aid, start, distance_km=km, moving_time_s=secs, hr_zones_s={"Z1": 0, "Z2": 0, "Z3": 300, "Z4": 5000, "Z5": 1000})


def test_hard_run_is_detected_as_race_but_tempo_run_is_not():
    tempo = act("t", "2026-09-20T08:00:00", hr_zones_s={"Z1": 600, "Z2": 600, "Z3": 600, "Z4": 1800, "Z5": 0})
    out = races([hard_run("h", "2026-09-27T11:30:00"), tempo])
    assert [r["activity_ids"] for r in out] == [["h"]] and out[0]["detected"] == "heart_rate"


def test_predictions_use_riegel_from_longest_recent_effort():
    acts = [hard_run("h", "2026-09-27T11:30:00", km=21.0975, secs=6000), act("s", "2026-09-01T08:00:00", raw={"fastestSplit_5000": 1260})]
    p = predictions(acts, date(2026, 9, 30))
    assert p["42k"]["from"]["activity_id"] == "h"
    assert p["42k"]["seconds"] == round(6000 * 2 ** 1.06)
    assert p["5k"]["seconds"] == 1260 and p["5k"]["from"]["source"] == "split"
    assert predictions(acts, date(2027, 9, 30)) == {}  # nothing in the last 180 days


def test_insights_flag_low_easy_share():
    acts = [hard_run("h", "2026-09-27T11:30:00")]
    out = insights([], [], acts, date(2026, 9, 30))
    assert out[0]["level"] == "watch" and out[0]["code"] == "easy_share"
    assert out[0]["params"]["easy_pct"] == 0 and out[0]["params"]["hard_pct"] == 95


def by_code(items):
    return {i["code"]: i for i in items}


def test_predictions_skip_triathlon_runs():
    acts = [act("s", "2026-09-27T08:00:00", sport="swim"), hard_run("h", "2026-09-27T11:30:00")]
    assert predictions(acts, date(2026, 9, 30)) == {}


# --- records from races, recent records ---------------------------------------------------------------------------


def test_race_measured_just_short_counts_for_the_record():
    acts = [
        act("s", "2026-08-01T08:00:00", raw={"fastestSplit_10000": 2700}),
        hard_run("r", "2026-09-06T09:00:00", km=9.85, secs=2580),  # watch measured 1.5% short
        hard_run("far", "2026-09-13T09:00:00", km=9.7, secs=2400),  # 3% short: not a 10 km
    ]
    rec = records(acts)
    assert [(r["activity_id"], r["source"]) for r in rec["10k"]] == [("s", "split"), ("r", "race")]
    assert rec["10k"][-1]["seconds"] == 2580 and rec["10k"][-1]["distance_km"] == 9.85


def test_slower_race_does_not_replace_a_faster_split():
    acts = [act("s", "2026-08-01T08:00:00", raw={"fastestSplit_10000": 2500}), hard_run("r", "2026-09-06T09:00:00", km=9.9, secs=2580)]
    assert [r["activity_id"] for r in records(acts)["10k"]] == ["s"]


def test_recent_records_only_improvements_in_the_last_two_weeks():
    acts = [
        act("a", "2026-06-01T08:00:00", raw={"fastestSplit_5000": 1500, "fastestSplit_1000": 280}),
        act("b", "2026-09-25T08:00:00", raw={"fastestSplit_5000": 1450}),
        act("c", "2026-09-26T08:00:00", raw={"fastestSplit_10000": 3000}),  # first 10 km ever: not an improvement
    ]
    out = recent_records(records(acts), date(2026, 9, 30))
    assert out == [{"key": "5k", "date": "2026-09-25", "seconds": 1450, "previous_seconds": 1500, "activity_id": "b", "source": "split"}]
    assert recent_records(records(acts), date(2026, 10, 20)) == []


def test_record_insight_for_a_recent_record():
    acts = [act("a", "2026-06-01T08:00:00", raw={"fastestSplit_5000": 1500}), act("b", "2026-09-25T08:00:00", raw={"fastestSplit_5000": 1450})]
    out = by_code(build_trends(acts, {}, ZONES, lambda aid: None, date(2026, 9, 30))["insights"])
    assert out["record_set"]["params"] == {"key": "5k", "seconds": 1450, "previous_seconds": 1500, "date": "2026-09-25", "activity_id": "b"}


# --- the user's own goal -------------------------------------------------------------------------------------------


def test_goal_from_plan_reads_distance_time_and_date():
    today = date(2026, 9, 1)
    g = goal_from_plan({"race": "Stadsmarathon, 2026-10-18", "goal": "onder 3:30"}, today)
    assert g == {"km": 42.195, "seconds": 3 * 3600 + 30 * 60, "date": "2026-10-18", "text": "onder 3:30 · Stadsmarathon, 2026-10-18"}
    assert goal_from_plan({"goal": "10 km onder 50 minuten"}, today)["seconds"] == 3000
    assert goal_from_plan({"goal": "10 km in 48:30"}, today)["seconds"] == 48 * 60 + 30  # m:ss for a 10 km
    assert goal_from_plan({"race": "Halve marathon 18-10-2026", "goal": "sub 1:45"}, today)["km"] == 21.0975
    assert goal_from_plan({"goal": "5 km"}, today) == {"km": 5.0, "seconds": None, "date": None, "text": "5 km"}


def test_no_goal_without_a_distance_or_after_the_race():
    today = date(2026, 9, 1)
    assert goal_from_plan(None, today) is None
    assert goal_from_plan({"goal": "fitter worden", "race": None}, today) is None
    assert goal_from_plan({"race": "Stadsloop 10 km, 2026-08-01"}, today) is None  # already past


def long_easy(aid, start, km):
    return act(aid, start, distance_km=km, moving_time_s=round(km * 330), hr_zones_s={"Z2": round(km * 330)})


def test_no_goal_means_no_goal_based_long_run_advice():
    acts = [long_easy("l", "2026-09-20T08:00:00", 18.0)]
    out = by_code(insights([], [], acts, date(2026, 9, 30)))
    assert "longest_run" in out and out["longest_run"]["params"] == {"km": 18.0}
    assert "long_run_goal" not in out and "goal_prediction" not in out


def test_goal_sets_the_long_run_target_and_compares_the_prediction():
    acts = [long_easy("l", "2026-09-20T08:00:00", 18.0), hard_run("h", "2026-09-27T11:30:00", km=21.0975, secs=6000)]
    goal = {"km": 42.195, "seconds": 12600, "date": "2026-10-18", "text": "x"}
    out = by_code(insights([], [], acts, date(2026, 9, 30), goal=goal))
    assert out["long_run_goal"]["params"] == {"km": 21.1, "target_km": 30, "goal_km": 42.195}
    assert out["long_run_goal"]["level"] == "info"
    p = out["goal_prediction"]["params"]
    assert p["goal_seconds"] == 12600 and p["predicted_seconds"] == round(6000 * 2**1.06) and p["goal_km"] == 42.195
    half = by_code(insights([], [], acts, date(2026, 9, 30), goal={"km": 21.0975, "seconds": None, "date": None, "text": "x"}))
    assert half["long_run_goal"]["params"]["target_km"] == 18 and half["long_run_goal"]["level"] == "good"
    assert "goal_prediction" not in half  # no goal time


# --- this week so far ----------------------------------------------------------------------------------------------


def test_run_volume_uses_the_current_week_not_the_last_week_with_activity():
    acts = [act(f"w{i}", f"2026-09-{d:02d}T08:00:00", distance_km=10.0) for i, d in enumerate((1, 8, 15, 22))]
    # today is Thursday 1 Oct; the current week (from Mon 28 Sep) has no run yet
    out = by_code(insights([], weekly_volume(acts), acts, date(2026, 10, 1)))
    assert out["run_volume"]["params"] == {"avg_km": 10.0, "week_km": 0.0, "week_start": "2026-09-28"}
    acts.append(act("now", "2026-09-29T08:00:00", distance_km=6.0))
    out = by_code(insights([], weekly_volume(acts), acts, date(2026, 10, 1)))
    assert out["run_volume"]["params"]["week_km"] == 6.0 and out["run_volume"]["params"]["avg_km"] == 10.0


# --- longest run per week ------------------------------------------------------------------------------------------


def test_longest_run_per_week_merges_split_runs():
    acts = [
        act("a1", "2026-09-06T08:00:00", distance_km=12.0, moving_time_s=3600, elapsed_time_s=3600),
        act("a2", "2026-09-06T09:10:00", distance_km=8.0, moving_time_s=2400),  # 10 min later: same session
        act("b", "2026-09-03T08:00:00", distance_km=15.0, moving_time_s=4500),
        act("c", "2026-09-10T08:00:00", distance_km=7.0, moving_time_s=2100),
        act("x", "2026-09-11T08:00:00", sport="ride", distance_km=60.0),
    ]
    out = longest_runs(acts)
    assert out == [
        {"week": "2026-08-31", "date": "2026-09-06", "km": 20.0, "seconds": 6000, "parts": 2, "activity_id": "a1"},
        {"week": "2026-09-07", "date": "2026-09-10", "km": 7.0, "seconds": 2100, "parts": 1, "activity_id": "c"},
    ]


# --- HRV ------------------------------------------------------------------------------------------------------------


def test_hrv_comes_from_last_night_average():
    out = recovery_daily({"2026-09-28": {"hrv_last_night": 61, "resting_hr": 48}})
    assert out[0]["hrv"] == 61
    assert recovery_weekly({"2026-09-28": {"hrv_last_night": 60}, "2026-09-29": {"hrv_last_night": 64}})[0]["hrv"] == 62.0


# --- wrist HR quality -----------------------------------------------------------------------------------------------


def test_hr_flags_and_z2_pace_leave_out_implausible_runs():
    acts = [act(f"n{i}", f"2026-09-0{i + 1}T08:00:00") for i in range(5)] + [act("bad", "2026-09-07T08:00:00", name="Ochtendloop")]
    streams = {a["id"]: run_streams(hr=140) for a in acts}
    streams["bad"] = run_streams(hr=140, start_hr=90)
    flags = hr_flags(acts, streams.get)
    assert flags == {"bad": ["low_start"]}
    weeks = z2_pace(acts, streams.get, ZONES, exclude=set(flags))
    assert sum(w["runs"] for w in weeks) == 5
    out = build_trends(acts, {}, ZONES, streams.get, date(2026, 9, 30))
    assert out["hr_flags"] == [{"id": "bad", "date": "2026-09-07", "name": "Ochtendloop", "reasons": ["low_start"]}]
    assert sum(w["runs"] for w in out["z2_pace"]) == 5


def test_build_trends_has_goal_and_longest_runs():
    plan = {"race": "Stadsloop 10 km, 2026-10-18", "goal": "onder 45:00"}
    out = build_trends([act("a", "2026-09-01T08:00:00")], {}, ZONES, lambda aid: None, date(2026, 9, 3), plan=plan)
    assert out["goal"]["km"] == 10.0 and out["goal"]["seconds"] == 2700
    assert out["longest_runs"][0]["km"] == 10.0
    assert build_trends([], {}, ZONES, lambda aid: None, date(2026, 9, 3))["goal"] is None


def test_form_stops_at_the_last_synced_day_after_a_stale_sync():
    acts = [act("a", "2026-09-01T08:00:00")]
    out = build_trends(acts, {}, ZONES, lambda aid: None, date(2026, 9, 30), last_sync="2026-09-20 06:02")
    assert out["form"][-1]["date"] == "2026-09-20"
    assert out["form_until"] == "2026-09-20" and out["stopped_at_sync"] is True
    fresh = build_trends(acts, {}, ZONES, lambda aid: None, date(2026, 9, 30), last_sync="2026-09-29 06:02")
    assert fresh["form"][-1]["date"] == "2026-09-30" and fresh["stopped_at_sync"] is False
    unknown = build_trends(acts, {}, ZONES, lambda aid: None, date(2026, 9, 30))
    assert unknown["form_until"] == "2026-09-30" and unknown["stopped_at_sync"] is False


def test_sport_performance_bests_and_weeks_for_swimming_and_cycling():
    from api.trends import sport_performance

    def a(i, day, sport, km, secs):
        return {"id": i, "start_local": f"{day}T08:00:00", "sport": sport, "distance_km": km, "moving_time_s": secs}

    acts = [
        a("s1", "2026-09-01", "swim", 1.5, 1800),  # 2:00/100m
        a("s2", "2026-09-03", "swim", 2.2, 2508),  # 1:54/100m, the longest and the fastest from 1 and 2 km
        a("s3", "2026-09-10", "swim", 0.8, 840),  # 1:45/100m but under 1 km: not a best
        a("s4", "2026-09-11", "swim", None, 3000),  # open water without a distance: left out
        a("r1", "2026-09-05", "ride", 50, 6000),  # 30 km/h
        a("r2", "2026-09-12", "ride", 95, 12600),  # 27.1 km/h, the only one from 90 km
    ]
    out = sport_performance(acts)
    swim = {b["key"]: b for b in out["swim"]["bests"]}
    assert swim["longest"]["activity_id"] == "s2" and swim["from_1"]["activity_id"] == "s2" and swim["from_2"]["value"] == 114
    assert [w["week"] for w in out["swim"]["longest"]] == ["2026-08-31", "2026-09-07"]
    assert out["swim"]["speed"][0]["value"] == round((1800 + 2508) / (3.7 * 10), 2)
    ride = {b["key"]: b for b in out["ride"]["bests"]}
    assert ride["from_40"]["activity_id"] == "r1" and ride["from_40"]["value"] == 30 and ride["from_90"]["activity_id"] == "r2"
    assert "run" not in out
