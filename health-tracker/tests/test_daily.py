from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api.daily import as_markdown, day_view, normal_resting_hr
from api.main import create_app
from api.readiness import readiness
from tests.test_api import engine, login, make_settings  # noqa: F401  (engine is a fixture)
from tests.test_mcp import TOKEN, call
from tests.test_sync import FakeGarmin
from tools import db
from tools.intraday import intraday_from_garmin, night_summary
from tools.store import wellness_from_garmin
from tools.sync import DbSink, GarminClient, sync_garmin, today_report


def ms(iso_utc: str) -> int:
    return int(datetime.fromisoformat(iso_utc).replace(tzinfo=timezone.utc).timestamp() * 1000)


# Garmin's answers for 5 October 2026 (summer time, UTC+2), shaped like garminconnect 0.3 returns them.
DAY = {"calendarDate": "2026-10-05", "startTimestampGMT": "2026-10-04T22:00:00.0", "startTimestampLocal": "2026-10-05T00:00:00.0"}
GARMIN_HR = {
    **DAY,
    "restingHeartRate": 46,
    "minHeartRate": 43,
    "maxHeartRate": 151,
    "heartRateValueDescriptors": [{"key": "timestamp", "index": 0}, {"key": "heartrate", "index": 1}],
    "heartRateValues": [
        [ms("2026-10-04T22:00:00"), 47],  # 00:00 local
        [ms("2026-10-04T22:02:00"), None],  # no reading
        [ms("2026-10-05T02:00:00"), 44],  # 04:00
        [ms("2026-10-05T04:30:00"), 79],  # 06:30
        [ms("2026-10-05T16:00:00"), 151],  # 18:00
    ],
}
GARMIN_STRESS = {
    **DAY,
    "avgStressLevel": 27,
    "stressValueDescriptorsDTOList": [{"key": "timestamp", "index": 0}, {"key": "stressLevel", "index": 1}],
    "stressValuesArray": [[ms("2026-10-04T22:00:00"), 12], [ms("2026-10-04T22:03:00"), -1], [ms("2026-10-05T16:00:00"), -2], [ms("2026-10-05T17:00:00"), 0]],
    "bodyBatteryValueDescriptorsDTOList": [
        {"bodyBatteryValueDescriptorIndex": 0, "bodyBatteryValueDescriptorKey": "timestamp"},
        {"bodyBatteryValueDescriptorIndex": 1, "bodyBatteryValueDescriptorKey": "bodyBatteryStatus"},
        {"bodyBatteryValueDescriptorIndex": 2, "bodyBatteryValueDescriptorKey": "bodyBatteryLevel"},
        {"bodyBatteryValueDescriptorIndex": 3, "bodyBatteryValueDescriptorKey": "bodyBatteryVersion"},
    ],
    "bodyBatteryValuesArray": [[ms("2026-10-04T22:00:00"), "MEASURED", 31, 2.0], [ms("2026-10-05T04:40:00"), "MEASURED", 88, 2.0], [ms("2026-10-05T05:00:00"), "MEASURED", None, 2.0]],
}
GARMIN_RESPIRATION = {
    **DAY,
    "avgSleepRespirationValue": 14.0,
    "respirationValueDescriptorsDTOList": [{"key": "timestamp", "index": 0}, {"key": "respiration", "index": 1}],
    "respirationValuesArray": [[ms("2026-10-04T22:00:00"), 14.04], [ms("2026-10-04T22:02:00"), -1.0], [ms("2026-10-05T02:00:00"), 13.0]],
}
GARMIN_SPO2 = {**DAY, "averageSpO2": 95, "continuousReadingDTOList": [{"epochTimestamp": ms("2026-10-04T23:00:00"), "spo2Reading": 94}, {"epochTimestamp": ms("2026-10-04T23:01:00"), "spo2Reading": None}]}
GARMIN_SLEEP = {
    "bodyBatteryChange": 57,
    "dailySleepDTO": {
        "calendarDate": "2026-10-05",
        "sleepTimeSeconds": 26400,
        "lightSleepSeconds": 14400,
        "awakeSleepSeconds": 900,
        "avgSleepStress": 14.2,
        "averageRespirationValue": 14.1,
        "lowestRespirationValue": 11.0,
        "averageSpO2Value": 95.0,
        "lowestSpO2Value": 89.0,
        "sleepStartTimestampGMT": ms("2026-10-04T21:10:00"),  # 23:10 local, the evening before
        "sleepEndTimestampGMT": ms("2026-10-05T04:40:00"),  # 06:40
        "sleepStartTimestampLocal": ms("2026-10-04T23:10:00"),
        "sleepEndTimestampLocal": ms("2026-10-05T06:40:00"),
    },
    "sleepLevels": [
        {"startGMT": "2026-10-04T21:10:00.0", "endGMT": "2026-10-04T21:40:00.0", "activityLevel": 1.0},
        {"startGMT": "2026-10-04T21:40:00.0", "endGMT": "2026-10-04T22:10:00.0", "activityLevel": 1.0},  # merged
        {"startGMT": "2026-10-04T22:10:00.0", "endGMT": "2026-10-04T23:00:00.0", "activityLevel": 0.0},
        {"startGMT": "2026-10-05T03:50:00.0", "endGMT": "2026-10-05T04:40:00.0", "activityLevel": 2.0},
        {"startGMT": "2026-10-05T04:40:00.0", "endGMT": "2026-10-05T04:40:00.0", "activityLevel": 3.0},  # empty: dropped
    ],
}
GARMIN_SUMMARY = {
    "restingHeartRate": 46, "totalSteps": 9000, "bodyBatteryChargedValue": 60, "bodyBatteryDrainedValue": 55,
    "restStressDuration": 30000, "lowStressDuration": 12000, "mediumStressDuration": 3600, "highStressDuration": 600,
    "moderateIntensityMinutes": 20, "vigorousIntensityMinutes": 10, "floorsAscended": 7.0, "activeKilocalories": 512.0,
    "averageStressLevel": -1,
}


def garmin_day():
    return intraday_from_garmin("2026-10-05", GARMIN_HR, GARMIN_SLEEP, GARMIN_STRESS, GARMIN_RESPIRATION, GARMIN_SPO2)


def test_garmin_series_become_minutes_after_local_midnight():
    out = garmin_day()
    assert out["hr"] == [[0, 47], [240, 44], [390, 79], [1080, 151]]
    assert (out["resting"], out["min"], out["max"]) == (46, 43, 151)
    assert out["stress"] == [[0, 12], [1140, 0]]  # -1 (off wrist) and -2 (activity) dropped, 0 is a reading
    assert out["bb"] == [[0, 31], [400, 88]]
    assert out["resp"] == [[0, 14.0], [240, 13.0]]
    assert out["spo2"] == [[60, 94]]
    assert out["sleep"] == {"start": -50, "end": 400, "stages": [[-50, 10, 1], [10, 60, 0], [350, 400, 2]]}


def test_garmin_day_without_data_is_empty_and_sleep_alone_is_kept():
    assert intraday_from_garmin("2026-10-05") == {}
    assert intraday_from_garmin("2026-10-05", {"heartRateValues": None}, {"dailySleepDTO": {}}, {"stressValuesArray": [[1, -1]]}) == {}
    # without the day's own timestamps the offset comes from the sleep (winter time here: UTC+1)
    sleep = {"dailySleepDTO": {"sleepStartTimestampGMT": ms("2026-12-01T22:00:00"), "sleepStartTimestampLocal": ms("2026-12-01T23:00:00"),
                               "sleepEndTimestampLocal": ms("2026-12-02T07:00:00")}}
    out = intraday_from_garmin("2026-12-02", {"heartRateValues": [[ms("2026-12-01T23:30:00"), 50]]}, sleep)
    assert out["hr"] == [[30, 50]] and out["sleep"] == {"start": -60, "end": 420, "stages": []}
    hourly = intraday_from_garmin("2026-10-05", spo2={**DAY, "spO2HourlyAverages": [[ms("2026-10-05T00:00:00"), 96]]})
    assert hourly == {"spo2": [[120, 96]]}


def test_wellness_takes_the_new_daily_values_from_responses_already_fetched():
    w = wellness_from_garmin(GARMIN_SLEEP, None, GARMIN_SUMMARY, None)
    assert w["light_sleep_h"] == 4.0 and w["awake_h"] == 0.25
    assert (w["sleep_start"], w["sleep_end"]) == ("2026-10-04T23:10", "2026-10-05T06:40")
    assert (w["sleep_stress"], w["sleep_resp"], w["sleep_resp_low"], w["spo2_avg"], w["spo2_low"]) == (14.2, 14.1, 11.0, 95, 89)
    assert (w["bb_charged_sleep"], w["bb_charged"], w["bb_drained"]) == (57, 60, 55)
    assert (w["stress_rest_min"], w["stress_low_min"], w["stress_medium_min"], w["stress_high_min"]) == (500, 200, 60, 10)
    assert (w["intensity_min"], w["intensity_moderate_min"], w["intensity_vigorous_min"]) == (40, 20, 10)
    assert (w["floors"], w["active_kcal"]) == (7, 512)
    assert "stress_avg" not in w  # -1: no data
    assert "sleep_start" not in wellness_from_garmin(None, None, GARMIN_SUMMARY, None)


class FakeGarminDay(FakeGarmin):
    def __init__(self):
        super().__init__()
        self.intraday_days = []

    def intraday(self, day):
        self.intraday_days.append(day)
        if day == "2026-09-29":
            return {}
        return {"hr": [[m, 50] for m in range(-60, 420, 2)], "sleep": {"start": -60, "end": 420, "stages": []}}


def scope():
    e = db.connect("sqlite://")
    db.create_schema(e)
    return db.Scope(e, 1)


def test_sync_fetches_two_weeks_of_series_the_first_time_then_continues():
    s, client = scope(), FakeGarminDay()
    state = {"garmin": {"last_activity_day": "2026-09-30", "last_wellness_day": "2026-09-30"}}
    sync_garmin(DbSink(s), client, state, today=date(2026, 9, 30), read_streams=lambda _: None)
    assert client.intraday_days[0] == "2026-09-16" and client.intraday_days[-1] == "2026-09-30" and len(client.intraday_days) == 15
    assert client.wellness_days == client.intraday_days  # wellness again for those days: it gained fields
    assert state["garmin"]["last_intraday_day"] == state["garmin"]["last_wellness_day"] == "2026-09-30"
    days = db.intraday_days(s)
    assert "2026-09-29" not in days and len(days) == 14  # a day without data is not stored
    assert db.load_wellness(s)["2026-09-30"] == {"sleep_h": 7.0, "sleep_hr": 50}  # heart rate while asleep, from the series

    client = FakeGarminDay()
    sync_garmin(DbSink(s), client, state, today=date(2026, 10, 1), read_streams=lambda _: None)
    assert client.intraday_days == ["2026-09-30", "2026-10-01"]  # the last day again: it was not finished yet


def test_today_report_tells_an_empty_garmin_day_from_one_with_data():
    assert "nog niets bij Garmin" in today_report({}, {})  # the watch has not uploaded today yet
    assert today_report({"steps": 4000}, {"hr": [[-30, 50], [745, 70]], "sleep": {"start": -60}}) == "1 dagwaarden, laatste meting 12:25"
    assert today_report({"steps": 4000}, None) == "1 dagwaarden"


def test_a_long_backfill_caps_the_series_at_90_days_but_not_wellness():
    s, client = scope(), FakeGarminDay()
    state = {"garmin": {"last_activity_day": "2026-09-30"}}
    sync_garmin(DbSink(s), client, state, today=date(2026, 9, 30), since=date(2025, 9, 30), read_streams=lambda _: None)
    assert client.wellness_days[0] == "2025-09-30"
    assert client.intraday_days[0] == "2026-07-02" and len(client.intraday_days) == 91


def test_sync_without_intraday_client_still_works(tmp_path):
    state = {"garmin": {"last_activity_day": "2026-09-30", "last_wellness_day": "2026-09-30"}}
    sync_garmin(tmp_path, FakeGarmin(), state, today=date(2026, 9, 30), read_streams=lambda _: None)
    assert "last_intraday_day" not in state["garmin"]


def test_garmin_client_reuses_the_sleep_of_wellness_and_fetches_four_series():
    calls = []

    def answer(name, value):
        def fn(d):
            calls.append((name, d))
            return value
        return fn

    class Api:
        get_sleep_data = staticmethod(answer("sleep", GARMIN_SLEEP))
        get_heart_rates = staticmethod(answer("hr", GARMIN_HR))
        get_stress_data = staticmethod(answer("stress", GARMIN_STRESS))
        get_respiration_data = staticmethod(answer("resp", GARMIN_RESPIRATION))
        get_spo2_data = staticmethod(answer("spo2", GARMIN_SPO2))
        get_hrv_data = staticmethod(answer("hrv", None))
        get_user_summary = staticmethod(answer("summary", GARMIN_SUMMARY))
        get_training_readiness = staticmethod(answer("readiness", []))

    client = GarminClient.__new__(GarminClient)
    client.api, client.stats, client._sleep = Api(), {}, ("", None)
    client.wellness("2026-10-05")
    calls.clear()
    out = client.intraday("2026-10-05")
    assert out == garmin_day() and [c[0] for c in calls] == ["hr", "stress", "resp", "spo2"]
    client.intraday("2026-10-04")  # no wellness for this day: fetches the sleep itself
    assert calls[4] == ("sleep", "2026-10-04")
    assert client.stats["hartslag"] == {"ok": 2} and client.stats["ademhaling"] == {"ok": 2}


def test_night_summary_shows_a_rise_before_waking():
    sleep = {"start": -60, "end": 420}
    points = [[m, 45] for m in range(-60, 300, 2)] + [[m, 80] for m in range(300, 422, 2)]
    n = night_summary(points, sleep)
    assert n["lowest"] == 45 and n["lowest_at"] == -60 and n["before_avg"] == 45 and n["last_avg"] == 80 and n["rise"] == 35
    assert n["minutes"] == 480
    assert night_summary(points, {"start": 0, "end": 120}) is None  # too short
    assert night_summary(points[:20], sleep) is None  # too few values
    assert night_summary(points, None) is None


def test_normal_resting_hr_is_the_60_day_median_before_the_day():
    wellness = {f"2026-09-{d:02d}": {"resting_hr": 48 + d % 3} for d in range(1, 21)}
    wellness["2026-09-21"] = {"resting_hr": 70}  # the day itself does not count
    assert normal_resting_hr(wellness, date(2026, 9, 21)) == 49
    assert normal_resting_hr({"2026-09-01": {"resting_hr": 52}}, date(2026, 9, 2)) == 52  # little history: the last nights
    assert normal_resting_hr({}, date(2026, 9, 2), 55) == 55
    assert normal_resting_hr({}, date(2026, 9, 2)) is None


def test_day_view_joins_the_evening_before_and_finds_neighbours():
    s = scope()
    db.write_intraday(s, "2026-10-04", {"hr": [[1300, 60], [1360, 55], [1420, 50]], "stress": [[1400, 30]]})
    db.write_intraday(s, "2026-10-05", garmin_day())
    db.write_intraday(s, "2026-10-08", {"hr": [[600, 70]], "sleep": {"start": -30, "end": 400, "stages": []}})
    wellness = {f"2026-09-{d:02d}": {"sleep_resp": 14.0 + d % 2} for d in range(1, 31)} | {"2026-10-05": {"resting_hr": 47, "sleep_resp": 16.0}}
    v = day_view(s, wellness, date(2026, 10, 5))
    assert v["from"] == -120  # an hour before falling asleep at 23:10, on the hour
    assert v["series"]["hr"][:3] == [[-80, 55], [-20, 50], [0, 47]]  # 21:40 (1300 - 1440 = -140) falls outside
    assert v["series"]["stress"][0] == [-40, 30] and v["series"]["bb"] and v["series"]["spo2"]
    assert v["sleep"]["stages"][1] == {"start": 10, "end": 60, "stage": "deep"}
    assert (v["prev"], v["next"], v["latest"]) == ("2026-10-04", "2026-10-08", "2026-10-08")
    assert v["summary"]["resting_hr"] == 47 and v["normals"]["sleep_resp"] == 14.5 and v["normals"]["sleep_hr"] is None
    assert (v["hr_min"], v["hr_max"]) == (44, 151)
    assert day_view(s, {}, None)["day"] == "2026-10-08"  # without a day: the latest
    assert day_view(s, {}, date(2026, 10, 5), today=date(2026, 10, 5))["to"] == 1200  # today: up to the last reading (stress, 19:00)
    assert day_view(s, {}, date(2026, 10, 7))["next_sleep_start"] == 1410  # the night of the 8th began at 23:30
    assert day_view(s, {"2026-10-09": {"steps": 10}}, None)["day"] == "2026-10-09"  # a day with only a summary counts too
    empty = day_view(scope(), {}, None, today=date(2026, 10, 6))
    assert empty["day"] == "2026-10-06" and empty["series"] == {} and empty["night"] is None
    assert empty["today"] == "2026-10-06"  # the date picker goes up to today, also before today has data
    assert "Geen data" in as_markdown(empty)


def test_readiness_adds_night_respiration_and_a_possible_cold():
    days = [f"2026-09-{d:02d}" for d in range(1, 31)]
    wellness = {d: {"resting_hr": 48, "sleep_hr": 52, "sleep_resp": 14.0, "sleep_h": 7.5} for d in days}
    wellness["2026-10-01"] = {"resting_hr": 52, "sleep_hr": 56, "sleep_resp": 15.2, "sleep_h": 7.5}
    r = readiness(wellness, date(2026, 10, 1))
    resp = next(s for s in r["signals"] if s["key"] == "respiration")
    assert resp["value"] == 15.2 and resp["level"] == "attention" and resp["note"]["params"] == {"delta": 1.2, "baseline": 14.0}
    assert r["illness_hint"] is True
    wellness["2026-10-01"]["sleep_hr"] = 53  # the heart rate while asleep is normal: no hint
    assert readiness(wellness, date(2026, 10, 1))["illness_hint"] is False


@pytest.fixture
def client(engine, tmp_path):  # noqa: F811
    import hashlib

    settings = make_settings(agent_token_hash=hashlib.sha256(TOKEN.encode()).hexdigest())
    return TestClient(create_app(engine=engine, settings=settings))


def test_endpoint_needs_login_and_returns_only_own_data(client, engine):  # noqa: F811
    assert client.get("/api/wellness/day").status_code == 401
    db.write_intraday(db.Scope(engine, 1), "2026-10-05", garmin_day())
    db.write_intraday(db.Scope(engine, 2), "2026-10-07", {"hr": [[0, 99]]})  # someone else's
    login(client)
    out = client.get("/api/wellness/day?day=2026-10-05").json()
    assert out["day"] == "2026-10-05" and out["next"] is None
    assert out["sleep"]["start"] == -50 and [0, 47] in out["series"]["hr"]
    assert client.get("/api/wellness/day?day=2026-10-07").json()["series"] == {}
    r = client.get("/api/wellness/day?day=morgen")
    assert r.status_code == 422 and r.json()["code"] == "invalid_date"


def test_mcp_get_day(client, engine):  # noqa: F811
    s = db.Scope(engine, 1)
    db.write_intraday(s, "2026-10-05", garmin_day())
    db.write_wellness(s, "2026-10-05", wellness_from_garmin(GARMIN_SLEEP, None, GARMIN_SUMMARY, None))
    text, err = call(client, "get_day", day="2026-10-05")
    assert not err and "# Dag 2026-10-05" in text and "23:10-06:40" in text and "ademhaling in de slaap 14.1/min" in text
    assert "| Tijd | HR gem | HR min-max | Stress | BB | Adem | SpO2 | Slaapfase |" in text and "| 06:30 | 79 | 79-79 |" in text
    assert call(client, "get_day", day="gisteren")[1] is True


def test_deleting_a_user_removes_their_series():
    s = scope()
    db.write_intraday(s, "2026-10-05", {"hr": [[0, 50]]})
    db.delete_user(s.engine, 1)
    assert db.intraday_days(s) == []
