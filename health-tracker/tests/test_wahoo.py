from datetime import date

import pytest
from cryptography.fernet import Fernet

from tools import db, wahoo
from tools.sync import run_db_sync

CREDS = ("cid", "secret")


class Resp:
    def __init__(self, status, body=None, content=b""):
        self.status_code, self._body, self.content = status, body, content or (b"{}" if body is not None else b"")

    def json(self):
        return self._body


class Http:
    """Records requests; answers from a queue per (method, path)."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def _next(self, method, url):
        path = url.replace(wahoo.API, "")
        self.calls.append((method, path))
        return self.answers[(method, path)].pop(0)

    def post(self, url, data=None, timeout=None):
        self.calls.append(("POST-data", data.get("grant_type")))
        return self._next("POST", url)

    def request(self, method, url, params=None, headers=None, timeout=None):
        self.calls.append(("auth", headers["Authorization"]))
        return self._next(method, url)

    def get(self, url, timeout=None):
        return self._next("GET", url)


def test_authorize_url_asks_for_the_three_scopes():
    url = wahoo.authorize_url("cid", "https://x/api/connections/wahoo/callback", "st8")
    assert url.startswith("https://api.wahooligan.com/oauth/authorize?")
    assert "scope=workouts_read%20offline_data%20user_read" in url and "state=st8" in url and "response_type=code" in url


def test_an_expired_token_is_refreshed_first_and_a_refused_refresh_means_revoked():
    http = Http({("POST", "/oauth/token"): [Resp(200, {"access_token": "a2", "refresh_token": "r2", "expires_in": 7200})],
                 ("GET", "/v1/workouts"): [Resp(200, {"workouts": [], "total": 0})]})
    c = wahoo.WahooClient({"access_token": "a1", "refresh_token": "r1", "expires_at": 0}, CREDS, http=http, now=lambda: 1000)
    c.workouts()
    assert ("auth", "Bearer a2") in http.calls and c.tokens() == {"access_token": "a2", "refresh_token": "r2", "expires_at": 8200}
    gone = wahoo.WahooClient({"access_token": "a", "refresh_token": "r", "expires_at": 0}, CREDS,
                             http=Http({("POST", "/oauth/token"): [Resp(400, {}, b'{"error":"invalid_grant"}')]}), now=lambda: 1000)
    with pytest.raises(wahoo.WahooRevoked):
        gone.workouts()


def test_a_refused_call_with_a_fresh_token_is_an_error_not_a_revoke():
    http = Http({("POST", "/oauth/token"): [Resp(200, {"access_token": "a2", "refresh_token": "r2", "expires_in": 7200})],
                 ("GET", "/v1/workouts"): [Resp(401, {}, b'{"error":"nope"}'), Resp(401, {}, b'{"error":"nope"}')]})
    c = wahoo.WahooClient({"access_token": "a1", "refresh_token": "r1", "expires_at": 9e9}, CREDS, http=http, now=lambda: 1000)
    with pytest.raises(wahoo.WahooError) as err:
        c.workouts()
    assert not isinstance(err.value, wahoo.WahooRevoked) and "HTTP 401" in str(err.value) and "nope" in str(err.value)
    assert c.tokens()["access_token"] == "a2"  # the refreshed pair is kept (and saved by the sync)


def ride(day, hh, km, hr=130):
    return {"manufacturer": "wahoo_fitness", "sport": "ride", "start_utc": f"{day}T{hh}:00:00Z", "start_local": f"{day}T{int(hh) + 2:02d}:00:00",
            "distance_m": km * 1000, "timer_s": 3600, "elapsed_s": 3700, "avg_hr": hr, "max_hr": hr + 20, "laps": [],
            "streams": {"time": [0, 1], "heartrate": [hr, hr]}}


class FakeWahoo:
    def __init__(self, workouts, revoked=False):
        self.items, self.revoked, self.downloads = workouts, revoked, 0

    def workouts(self, page=1, per_page=30):
        if self.revoked:
            raise wahoo.WahooRevoked("gone")
        chunk = self.items[(page - 1) * 2 : page * 2]
        return {"workouts": chunk, "total": len(self.items), "page": page, "per_page": 2}

    def summary(self, wid):
        return {"file": {"url": f"https://cdn/{wid}.fit"}}

    def download(self, url):
        self.downloads += 1
        return url.encode()

    def tokens(self):
        return {"access_token": "new", "refresh_token": "new", "expires_at": 1}


RIDES = {
    b"https://cdn/3.fit": {**ride("2026-10-02", "13", 52.0), "start_utc": "2026-10-02T13:59:30Z"},  # the Garmin ride, 30 s apart
    b"https://cdn/2.fit": ride("2026-09-20", "08", 40.0),
    b"https://cdn/1.fit": ride("2025-01-01", "08", 30.0),
}
WORKOUTS = [{"id": 3, "starts": "2026-10-02T13:59:00.000Z", "name": "Zondagrit"}, {"id": 2, "starts": "2026-09-20T08:00:00.000Z"},
            {"id": 1, "starts": "2025-01-01T08:00:00.000Z"}]


def test_sync_brings_in_the_past_year_merges_with_garmin_and_keeps_the_fit_file():
    e = db.connect("sqlite://")
    db.create_schema(e)
    s = db.Scope(e, 1)
    garmin = {"start_utc": "2026-10-02T13:59:00Z", "start_local": "2026-10-02T15:59:00", "sport": "ride", "name": "Amsterdam Cycling",
              "distance_km": 52.24, "moving_time_s": 6679, "streams": {"time": [0, 1], "heartrate": [120, 121]}, "fit_file": "garmin-1",
              "sources": {"garmin": {"id": 1}}}
    gid = db.upsert_activity(s, garmin)
    client, state = FakeWahoo(WORKOUTS), {}
    n = wahoo.sync_wahoo(s, client, state, date(2026, 10, 5), read_activity=lambda b: RIDES[b])
    assert n == 2 and state["wahoo"]["last_workout_day"] == "2026-10-02"  # the 2025 workout is older than a year
    acts = {a["id"]: a for a in db.load_activities(s)}
    merged = acts[gid]
    assert set(merged["sources"]) == {"garmin", "wahoo_api"} and merged["distance_km"] == 52.24 and merged["fit_file"] == "garmin-1"
    assert db.load_streams(s, gid)["heartrate"] == [120, 121]  # Garmin's streams lead
    only = next(a for a in acts.values() if a["id"] != gid)
    assert only["fit_file"] == "wahoo_api/2" and db.get_fit(s, "wahoo_api/2") == b"https://cdn/2.fit"
    # the next sync only looks back from the last workout, and downloads nothing twice
    assert wahoo.sync_wahoo(s, client, state, date(2026, 10, 6), read_activity=lambda b: RIDES[b]) == 1 and client.downloads == 2


def test_access_revoked_at_wahoo_ends_the_connection_and_removes_its_data(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("WAHOO_CLIENT_ID", "cid")
    monkeypatch.setenv("WAHOO_CLIENT_SECRET", "secret")
    e = db.connect("sqlite://")
    db.create_schema(e)
    s = db.Scope(e, 1)
    wahoo.save_tokens(s, {"access_token": "a", "refresh_token": "r", "expires_at": 9e9}, key)
    db.upsert_activity(s, {"start_utc": "2026-09-20T08:00:00Z", "start_local": "2026-09-20T10:00:00", "sport": "ride", "distance_km": 40.0,
                           "sources": {"wahoo_api": {"id": 2}}})
    db.upsert_activity(s, {"start_utc": "2026-09-21T08:00:00Z", "start_local": "2026-09-21T10:00:00", "sport": "ride", "distance_km": 30.0,
                           "sources": {"wahoo": {"file": "upload.fit"}}})  # uploaded by the user: stays
    status = run_db_sync(s, key, None, today=date(2026, 10, 5), wahoo_factory=lambda tokens, creds: FakeWahoo([], revoked=True))
    assert status == 0
    assert db.get_setting(s, "wahoo_tokens") is None
    assert [a["distance_km"] for a in db.load_activities(s)] == [30.0]


def test_a_wahoo_sync_saves_the_newest_tokens(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("WAHOO_CLIENT_ID", "cid")
    monkeypatch.setenv("WAHOO_CLIENT_SECRET", "secret")
    e = db.connect("sqlite://")
    db.create_schema(e)
    s = db.Scope(e, 1)
    wahoo.save_tokens(s, {"access_token": "a", "refresh_token": "r", "expires_at": 9e9}, key)
    assert run_db_sync(s, key, None, today=date(2026, 10, 5), wahoo_factory=lambda tokens, creds: FakeWahoo([])) == 0
    assert wahoo.load_tokens(db.get_setting(s, "wahoo_tokens"), key)["refresh_token"] == "new"
    assert "garmin" not in (db.get_setting(s, "sync_state") or {}).get("last_failed", [])


def test_a_workout_whose_summary_wahoo_refuses_is_skipped_and_the_rest_comes_in():
    e = db.connect("sqlite://")
    db.create_schema(e)
    s = db.Scope(e, 1)

    class Refusing(FakeWahoo):
        def summary(self, wid):
            if wid == 3:
                raise wahoo.WahooError('HTTP 401 {"error":"You are not authorized to view this workout summary"}')
            return super().summary(wid)

    client, state = Refusing(WORKOUTS), {}
    assert wahoo.sync_wahoo(s, client, state, date(2026, 10, 5), read_activity=lambda b: RIDES[b]) == 1
    assert [a["fit_file"] for a in db.load_activities(s)] == ["wahoo_api/2"]


def test_a_refused_summary_does_not_refresh_the_token():
    http = Http({("GET", "/v1/workouts/7/workout_summary"): [Resp(401, {}, b'{"error":"You are not authorized to view this workout summary"}')]})
    c = wahoo.WahooClient({"access_token": "a1", "refresh_token": "r1", "expires_at": 9e9}, CREDS, http=http, now=lambda: 1000)
    with pytest.raises(wahoo.WahooError):
        c.summary(7)
    assert not any(call[0] == "POST-data" for call in http.calls) and c.tokens()["access_token"] == "a1"


def test_a_file_that_does_not_download_is_skipped_and_retried_next_sync():
    e = db.connect("sqlite://")
    db.create_schema(e)
    s = db.Scope(e, 1)

    class Flaky(FakeWahoo):
        fail = {2}

        def download(self, url):
            if int(url.split("/")[-1].split(".")[0]) in self.fail:
                raise wahoo.WahooError("FIT download: HTTP 504")
            return super().download(url)

    client, state = Flaky(WORKOUTS), {}
    assert wahoo.sync_wahoo(s, client, state, date(2026, 10, 5), read_activity=lambda b: RIDES[b]) == 1
    assert state["wahoo"]["last_workout_day"] == "2026-09-20" and state["wahoo"]["failed"] == {"2": 1}
    client.fail = set()
    assert wahoo.sync_wahoo(s, client, state, date(2026, 10, 5), read_activity=lambda b: RIDES[b]) == 2
    assert state["wahoo"]["last_workout_day"] == "2026-10-02" and state["wahoo"]["failed"] == {}
    assert {a["fit_file"] for a in db.load_activities(s)} == {"wahoo_api/3", "wahoo_api/2"}


def test_download_tries_three_times_on_a_server_error():
    http = Http({("GET", "https://cdn/x.fit"): [Resp(504), Resp(502), Resp(200, None, b"fit")]})
    slept = []
    c = wahoo.WahooClient({"access_token": "a", "refresh_token": "r", "expires_at": 9e9}, CREDS, http=http, now=lambda: 1000, sleep=slept.append)
    assert c.download("https://cdn/x.fit") == b"fit" and slept == [2, 4]


def test_progress_says_how_far_back_the_sync_is():
    e = db.connect("sqlite://")
    db.create_schema(e)
    steps = []
    wahoo.sync_wahoo(db.Scope(e, 1), FakeWahoo(WORKOUTS), {}, date(2026, 10, 5), read_activity=lambda b: RIDES[b],
                     progress=lambda step, done=None, total=None: steps.append((step, done, total)))
    assert steps == [("wahoo", 0, 365), ("wahoo", 3, 365), ("wahoo", 15, 365)]
