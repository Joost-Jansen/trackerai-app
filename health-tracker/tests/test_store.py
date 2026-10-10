import json

from tools.store import from_garmin, from_strava, load_activities, load_wellness, upsert_activity, write_wellness, wellness_from_garmin

STRAVA_ACTIVITY = {
    "id": 111,
    "name": "Ochtendloop",
    "sport_type": "Run",
    "start_date": "2026-09-28T07:30:05Z",
    "start_date_local": "2026-09-28T09:30:05Z",
    "distance": 10012.3,
    "moving_time": 3240,
    "elapsed_time": 3300,
    "total_elevation_gain": 12.4,
    "average_heartrate": 149.6,
    "max_heartrate": 163.0,
    "average_cadence": 86.0,
}
STRAVA_STREAMS = {
    "time": {"data": [0, 1, 2]},
    "latlng": {"data": [[52.09, 5.12], [52.0901, 5.12], [52.0902, 5.12]]},
    "heartrate": {"data": [120, 121, 122]},
    "velocity_smooth": {"data": [3.0, 3.1, 3.1]},
}
GARMIN_ACTIVITY = {
    "activityId": 999,
    "activityName": "Utrecht Hardlopen",
    "activityType": {"typeKey": "running"},
    "startTimeGMT": "2026-09-28 07:30:00",
    "startTimeLocal": "2026-09-28 09:30:00",
    "distance": 10005.0,
    "duration": 3301.0,
    "movingDuration": 3238.0,
    "elevationGain": 14.0,
    "averageHR": 150.0,
    "maxHR": 164.0,
    "averageRunningCadenceInStepsPerMinute": 172.0,
    "aerobicTrainingEffect": 3.1,
}
GARMIN_SPLITS = {"lapDTOs": [{"distance": 1000.0, "duration": 321.0, "averageHR": 145.0, "averageSpeed": 3.115, "elevationGain": 2.0}]}


def test_strava_record_is_normalised():
    rec = from_strava(STRAVA_ACTIVITY, STRAVA_STREAMS)
    assert rec["sport"] == "run"
    assert rec["start_utc"] == "2026-09-28T07:30:05Z"
    assert rec["start_local"] == "2026-09-28T09:30:05"
    assert rec["distance_km"] == 10.01
    assert rec["avg_hr"] == 150
    assert rec["avg_cadence_spm"] == 172  # strava gives one-foot rpm for runs
    assert rec["streams"]["latlng"][0] == [52.09, 5.12]
    assert rec["streams"]["velocity"] == [3.0, 3.1, 3.1]


def test_garmin_record_is_normalised_with_laps():
    rec = from_garmin(GARMIN_ACTIVITY, GARMIN_SPLITS)
    assert rec["sport"] == "run"
    assert rec["start_utc"] == "2026-09-28T07:30:00Z"
    assert rec["moving_time_s"] == 3238
    assert rec["laps"][0] == {"distance_km": 1.0, "time_s": 321, "avg_hr": 145, "pace": "5:21", "elevation_gain_m": 2.0}
    assert rec["sources"]["garmin"]["id"] == 999


def test_same_activity_from_both_sources_is_merged_into_one_file(tmp_path):
    p1 = upsert_activity(tmp_path, from_strava(STRAVA_ACTIVITY, STRAVA_STREAMS))
    p2 = upsert_activity(tmp_path, from_garmin(GARMIN_ACTIVITY, GARMIN_SPLITS))
    assert p1 == p2
    rec = json.loads(p1.read_text())
    assert set(rec["sources"]) == {"garmin", "strava"}
    assert rec["avg_hr"] == 150  # garmin wins for metrics
    assert rec["name"] == "Ochtendloop"  # strava name is the one the user edits
    assert rec["streams"]["latlng"]  # strava streams kept
    assert rec["laps"]  # garmin laps kept


def test_merge_order_does_not_matter(tmp_path):
    upsert_activity(tmp_path, from_garmin(GARMIN_ACTIVITY, GARMIN_SPLITS))
    path = upsert_activity(tmp_path, from_strava(STRAVA_ACTIVITY, STRAVA_STREAMS))
    rec = json.loads(path.read_text())
    assert rec["avg_hr"] == 150 and rec["name"] == "Ochtendloop"


def test_activities_far_apart_in_time_stay_separate(tmp_path):
    later = dict(STRAVA_ACTIVITY, id=112, start_date="2026-09-28T17:00:00Z", start_date_local="2026-09-28T19:00:00Z")
    upsert_activity(tmp_path, from_strava(STRAVA_ACTIVITY, None))
    upsert_activity(tmp_path, from_strava(later, None))
    assert len(load_activities(tmp_path)) == 2


def test_resync_same_source_overwrites_not_duplicates(tmp_path):
    upsert_activity(tmp_path, from_strava(STRAVA_ACTIVITY, None))
    upsert_activity(tmp_path, from_strava(dict(STRAVA_ACTIVITY, name="Nieuwe naam"), None))
    acts = load_activities(tmp_path)
    assert len(acts) == 1 and acts[0]["name"] == "Nieuwe naam"


def test_wellness_from_garmin_extracts_core_metrics():
    w = wellness_from_garmin(
        sleep={"dailySleepDTO": {"sleepTimeSeconds": 27000, "deepSleepSeconds": 5400, "remSleepSeconds": 6000, "sleepScores": {"overall": {"value": 82}}}},
        hrv={"hrvSummary": {"lastNightAvg": 58, "weeklyAvg": 55, "status": "BALANCED"}},
        summary={"restingHeartRate": 48, "bodyBatteryHighestValue": 85, "bodyBatteryLowestValue": 20, "averageStressLevel": 27, "totalSteps": 12000},
        readiness=[{"score": 71, "level": "MODERATE"}],
    )
    assert w == {
        "sleep_h": 7.5,
        "deep_sleep_h": 1.5,
        "rem_sleep_h": 1.67,
        "sleep_score": 82,
        "hrv_last_night": 58,
        "hrv_weekly_avg": 55,
        "hrv_status": "BALANCED",
        "resting_hr": 48,
        "body_battery_high": 85,
        "body_battery_low": 20,
        "stress_avg": 27,
        "steps": 12000,
        "readiness_score": 71,
        "readiness_level": "MODERATE",
    }


def test_wellness_tolerates_missing_data():
    assert wellness_from_garmin(sleep={}, hrv=None, summary={}, readiness=[]) == {}


def test_wellness_refetch_replaces_the_day(tmp_path):
    # a refetch must drop values that newer cleaning rules no longer keep (seen: stale resting HR 131)
    write_wellness(tmp_path, "2026-09-28", {"resting_hr": 131, "stress_avg": -1})
    write_wellness(tmp_path, "2026-09-28", {"steps": 500})
    assert load_wellness(tmp_path) == {"2026-09-28": {"steps": 500}}


def test_negative_values_mean_no_data():
    w = wellness_from_garmin(sleep={}, hrv=None, summary={"averageStressLevel": -1, "totalSteps": 500}, readiness=[])
    assert w == {"steps": 500}


def test_resting_hr_only_kept_on_days_with_sleep_data():
    # without an overnight recording Garmin estimates resting HR from daytime data (seen: 124, 131)
    no_sleep = wellness_from_garmin(sleep={}, hrv=None, summary={"restingHeartRate": 124}, readiness=[])
    assert "resting_hr" not in no_sleep
    with_sleep = wellness_from_garmin(
        sleep={"dailySleepDTO": {"sleepTimeSeconds": 25000}}, hrv=None, summary={"restingHeartRate": 45}, readiness=[]
    )
    assert with_sleep["resting_hr"] == 45


def test_wellness_refetch_without_data_removes_stale_day(tmp_path):
    write_wellness(tmp_path, "2026-07-03", {"stress_avg": -1})
    write_wellness(tmp_path, "2026-07-03", {})
    assert load_wellness(tmp_path) == {}
