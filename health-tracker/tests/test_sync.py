from datetime import date, datetime

from tests.test_store import GARMIN_ACTIVITY, GARMIN_SPLITS, STRAVA_ACTIVITY, STRAVA_STREAMS
from tools.store import load_activities, load_wellness
from tools.sync import RateLimited, fetch_metric, sync_garmin, sync_strava, write_rotated_token


class FakeStrava:
    def __init__(self, activities, fail_streams_after=None):
        self.activities = activities
        self.fail_after = fail_streams_after
        self.stream_calls = 0
        self.asked_after = None

    def list_activities(self, after_epoch):
        self.asked_after = after_epoch
        return [a for a in self.activities if _epoch(a) > after_epoch]

    def streams(self, activity_id):
        if self.fail_after is not None and self.stream_calls >= self.fail_after:
            raise RateLimited("429")
        self.stream_calls += 1
        return STRAVA_STREAMS


def _strava(i):
    return dict(STRAVA_ACTIVITY, id=i, start_date=f"2026-09-2{i}T07:30:05Z", start_date_local=f"2026-09-2{i}T09:30:05Z")


def _epoch(a):
    return int(datetime.fromisoformat(a["start_date"].replace("Z", "+00:00")).timestamp())


def test_strava_sync_is_incremental_and_saves_progress(tmp_path):
    acts = [_strava(1), _strava(2), _strava(3)]
    state = {"strava": {"last_start_epoch": _epoch(acts[0])}}
    client = FakeStrava(acts)
    n = sync_strava(tmp_path, client, state)
    assert client.asked_after == _epoch(acts[0])
    assert n == 2
    assert state["strava"]["last_start_epoch"] == _epoch(acts[2])
    assert len(load_activities(tmp_path)) == 2


def test_strava_rate_limit_keeps_what_was_done(tmp_path):
    state = {}
    acts = [_strava(1), _strava(2)]
    client = FakeStrava(acts, fail_streams_after=1)
    try:
        sync_strava(tmp_path, client, state)
        raise AssertionError("expected RateLimited")
    except RateLimited:
        pass
    assert state["strava"]["last_start_epoch"] == _epoch(acts[0])
    assert len(load_activities(tmp_path)) == 1


class FakeGarmin:
    def __init__(self):
        self.wellness_days = []

    def activities(self, start, end):
        return [GARMIN_ACTIVITY]

    def splits(self, activity_id):
        return GARMIN_SPLITS

    def fit(self, activity_id):
        return b"PK-fake-zip"

    def wellness(self, day):
        self.wellness_days.append(day)
        return {"sleep_h": 7.0}


def test_garmin_sync_stores_activity_fit_and_wellness(tmp_path):
    state = {"garmin": {"last_activity_day": "2026-09-28", "last_wellness_day": "2026-09-28"}}
    client = FakeGarmin()
    sync_garmin(tmp_path, client, state, today=date(2026, 9, 30))
    acts = load_activities(tmp_path)
    assert len(acts) == 1 and acts[0]["fit_file"] == "data/raw/fit/2026/999.zip"
    assert (tmp_path / "data/raw/fit/2026/999.zip").read_bytes() == b"PK-fake-zip"
    # re-fetches the last day (it may have been partial) up to today
    assert client.wellness_days == ["2026-09-28", "2026-09-29", "2026-09-30"]
    assert set(load_wellness(tmp_path)) == {"2026-09-28", "2026-09-29", "2026-09-30"}
    assert state["garmin"] == {"last_activity_day": "2026-09-30", "last_wellness_day": "2026-09-30"}


def test_garmin_backfill_honours_explicit_since(tmp_path):
    state = {"garmin": {"last_activity_day": "2026-09-30", "last_wellness_day": "2026-09-30"}}
    client = FakeGarmin()
    sync_garmin(tmp_path, client, state, today=date(2026, 9, 30), since=date(2025, 6, 1))
    assert client.wellness_days[0] == "2025-06-01"
    assert len(client.wellness_days) == 487


def test_fetch_metric_records_ok_empty_and_errors():
    stats = {}
    assert fetch_metric(stats, "hrv", lambda d: {"x": 1}, "2026-09-30") == {"x": 1}
    assert fetch_metric(stats, "hrv", lambda d: None, "2026-09-30") is None

    def boom(d):
        raise KeyError("hrvSummary")

    assert fetch_metric(stats, "hrv", boom, "2026-09-30") is None
    assert stats == {"hrv": {"ok": 1, "leeg": 1, "fout KeyError": 1}}


def test_fetch_metric_lets_rate_limit_through():
    def limited(d):
        raise RateLimited("429")

    try:
        fetch_metric({}, "hrv", limited, "2026-09-30")
        raise AssertionError("expected RateLimited")
    except RateLimited:
        pass


def test_rotated_token_is_written_only_when_changed(tmp_path):
    write_rotated_token(tmp_path, "X", old="same", new="same")
    assert not (tmp_path / "X").exists()
    write_rotated_token(tmp_path, "X", old="old", new="new")
    assert (tmp_path / "X").read_text() == "new"


def test_rotated_token_ignored_without_out_dir():
    write_rotated_token(None, "X", old="old", new="new")  # must not raise


def test_garmin_sync_stores_gps_streams_from_fit(tmp_path):
    state = {"garmin": {"last_activity_day": "2026-09-28", "last_wellness_day": "2026-09-30"}}
    seen = []

    def reader(data):
        seen.append(data)
        return {"time": [0, 1], "latlng": [[52.09, 5.12], [52.0901, 5.12]]}

    sync_garmin(tmp_path, FakeGarmin(), state, today=date(2026, 9, 30), read_streams=reader)
    assert seen == [b"PK-fake-zip"]
    assert load_activities(tmp_path)[0]["streams"]["latlng"][0] == [52.09, 5.12]


def test_garmin_sync_survives_unreadable_fit(tmp_path):
    state = {"garmin": {"last_activity_day": "2026-09-28", "last_wellness_day": "2026-09-30"}}

    def broken(data):
        raise ValueError("unreadable FIT file")

    sync_garmin(tmp_path, FakeGarmin(), state, today=date(2026, 9, 30), read_streams=broken)
    acts = load_activities(tmp_path)
    assert len(acts) == 1 and "streams" not in acts[0]
