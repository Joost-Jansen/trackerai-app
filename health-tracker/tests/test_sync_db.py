from datetime import date

from cryptography.fernet import Fernet

from tests.test_sync import FakeGarmin
from tools import db
from tools.secretbox import decrypt, encrypt
from tools.sync import DbSink, run_db_sync, sync_garmin


def engine():
    e = db.connect("sqlite://")
    db.create_schema(e)
    e = db.Scope(e, 1)
    db.set_setting(e, "zones", {"run": {"bounds": [132, 147, 162, 176], "max_hr": 189}})
    return e


def streams(_data):
    return {"time": [0, 10, 20], "heartrate": [140, 150, 150], "latlng": [[52.09, 5.12], [52.0901, 5.12], [52.0902, 5.12]]}


def test_garmin_sync_into_database():
    e = engine()
    state = {"garmin": {"last_activity_day": "2026-09-28", "last_wellness_day": "2026-09-30"}}
    sync_garmin(DbSink(e), FakeGarmin(), state, today=date(2026, 9, 30), read_streams=streams)
    acts = db.load_activities(e)
    assert len(acts) == 1 and acts[0]["fit_file"] == "garmin-999"
    assert db.get_fit(e, "garmin-999") == b"PK-fake-zip"
    assert db.load_streams(e, acts[0]["id"])["latlng"]
    # yesterday again too: the watch may have uploaded its evening and night after the last sync
    assert db.load_wellness(e) == {"2026-09-29": {"sleep_h": 7.0}, "2026-09-30": {"sleep_h": 7.0}}


def test_fit_already_stored_is_not_downloaded_again():
    e = engine()
    db.put_fit(e, "garmin-999", b"stored")
    client = FakeGarmin()
    client.fit = lambda _id: (_ for _ in ()).throw(AssertionError("downloaded again"))
    seen = []
    sync_garmin(DbSink(e), client, {"garmin": {"last_activity_day": "2026-09-30", "last_wellness_day": "2026-09-30"}},
                today=date(2026, 9, 30), read_streams=lambda d: seen.append(d) or {})
    assert seen == [b"stored"]


def test_secretbox_roundtrip_and_key_required():
    key = Fernet.generate_key().decode()
    token = encrypt("garmin-tokens-json", key)
    assert token != "garmin-tokens-json" and decrypt(token, key) == "garmin-tokens-json"


class FakeClientWithTokens(FakeGarmin):
    def __init__(self, tokens):
        super().__init__()
        self.login_tokens = tokens

    def tokens(self):
        return "rotated-" + self.login_tokens


def test_run_db_sync_uses_stored_tokens_saves_rotation_state_and_derives():
    e = engine()
    key = Fernet.generate_key().decode()
    db.set_setting(e, "garmin_tokens", encrypt("from-db", key))
    made = []

    def factory(tokens):
        made.append(tokens)
        return FakeClientWithTokens(tokens)

    result = run_db_sync(e, key, env_tokens="from-env", client_factory=factory, today=date(2026, 9, 30), read_streams=streams)
    assert made == ["from-db"]  # the database copy wins over the (older) environment variable
    assert decrypt(db.get_setting(e, "garmin_tokens"), key) == "rotated-from-db"
    state = db.get_setting(e, "sync_state")
    assert state["garmin"]["last_activity_day"] == "2026-09-30" and "last_sync_local" in state and "last_failed" not in state
    assert db.load_activities(e)[0]["hr_zones_s"]["Z3"] == 10  # derive ran
    assert result == 0


def test_run_db_sync_falls_back_to_env_tokens_and_records_failure():
    e = engine()
    key = Fernet.generate_key().decode()

    def broken(tokens):
        assert tokens == "from-env"
        raise RuntimeError("login failed")

    assert run_db_sync(e, key, env_tokens="from-env", client_factory=broken, today=date(2026, 9, 30)) == 1
    assert db.get_setting(e, "sync_state")["last_failed"] == ["garmin"]


def test_stale_database_tokens_fall_back_to_fresh_env_tokens():
    # after Garmin invalidates the session, the admin re-runs setup_garmin which only updates GARMINTOKENS
    e = engine()
    key = Fernet.generate_key().decode()
    db.set_setting(e, "garmin_tokens", encrypt("stale", key))
    tried = []

    def factory(tokens):
        tried.append(tokens)
        if tokens == "stale":
            raise RuntimeError("401 from Garmin")
        return FakeClientWithTokens(tokens)

    assert run_db_sync(e, key, env_tokens="fresh", client_factory=factory, today=date(2026, 9, 30), read_streams=streams) == 0
    assert tried == ["stale", "fresh"]
    assert decrypt(db.get_setting(e, "garmin_tokens"), key) == "rotated-fresh"


def _detail(aid, key, parent, start, seconds, km, hr, children=()):
    return {
        "activityId": aid, "activityName": f"Triathlon - {key}", "parentId": 500 if aid != 500 else None,
        "activityTypeDTO": {"typeKey": key, "parentTypeId": parent},
        "metadataDTO": {"childIds": list(children)},
        "summaryDTO": {"startTimeLocal": f"2026-09-27T{start}.0", "startTimeGMT": f"2026-09-27T{int(start[:2]) - 2:02d}{start[2:]}.0",
                       "distance": km * 1000, "duration": seconds, "movingDuration": seconds, "elapsedDuration": seconds, "averageHR": hr, "maxHR": hr + 15},
    }


class FakeMultisport(FakeGarmin):
    """Garmin's list only has the parent (parent: True); the legs and transitions come from the detail endpoint."""

    DETAILS = {
        500: _detail(500, "multi_sport", 17, "09:00:00", 9000, 51.5, 150, children=(501, 502, 503, 504, 505)),
        501: _detail(501, "open_water_swimming", 26, "09:00:00", 1800, 1.5, 140),
        502: _detail(502, "transition_v2", 4, "09:30:00", 120, 0.2, 130),
        503: _detail(503, "road_biking", 2, "09:32:00", 4500, 40, 150),
        504: _detail(504, "bikeToRunTransition_v2", 4, "10:47:00", 60, 0.1, 150),
        505: _detail(505, "running", 17, "10:48:00", 2520, 10, 160),
    }

    def activities(self, start, end):
        return [{
            "activityId": 500, "activityName": "Triathlon", "activityType": {"typeKey": "multi_sport", "parentTypeId": 17},
            "startTimeLocal": "2026-09-27 09:00:00", "startTimeGMT": "2026-09-27 07:00:00",
            "distance": 51800.0, "duration": 9000.0, "elapsedDuration": 9000000.0, "averageHR": 150.0, "parent": True,
        }]

    def activity(self, activity_id):
        return self.DETAILS[int(activity_id)]


def test_a_multisport_activity_is_stored_as_its_legs_without_transitions():
    e = engine()
    old = FakeMultisport().activities(None, None)[0]  # how the sync stored it before: one multi_sport activity
    from tools.store import from_garmin

    db.upsert_activity(e, from_garmin(old, None))
    assert [a["sport"] for a in db.load_activities(e)] == ["multi_sport"]
    windows = []
    state = {"garmin": {"last_activity_day": "2026-09-27", "last_wellness_day": "2026-09-30"}}
    sync_garmin(DbSink(e), FakeMultisport(), state, today=date(2026, 9, 30), read_streams=lambda data, *w: windows.append(w) or {})
    acts = db.load_activities(e)
    assert [(a["sport"], a["distance_km"], a["start_utc"]) for a in acts] == [
        ("swim", 1.5, "2026-09-27T07:00:00Z"), ("ride", 40.0, "2026-09-27T07:32:00Z"), ("run", 10.0, "2026-09-27T08:48:00Z")]
    assert all(a["fit_file"] == "garmin-500" for a in acts)  # the legs share the parent's FIT file
    assert [(w[0].isoformat(), (w[1] - w[0]).seconds) for w in windows] == [
        ("2026-09-27T07:00:00+00:00", 1800), ("2026-09-27T07:32:00+00:00", 4500), ("2026-09-27T08:48:00+00:00", 2520)]


def test_a_multisport_whose_legs_fail_to_load_is_kept_whole():
    class Broken(FakeMultisport):
        def activity(self, activity_id):
            raise RuntimeError("Garmin said 500")

    e = engine()
    state = {"garmin": {"last_activity_day": "2026-09-27", "last_wellness_day": "2026-09-30"}}
    sync_garmin(DbSink(e), Broken(), state, today=date(2026, 9, 30), read_streams=lambda data, *w: {})
    assert [(a["sport"], a["elapsed_time_s"]) for a in db.load_activities(e)] == [("multi_sport", 9000)]
