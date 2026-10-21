from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from api.connections import GarminLoginError
from api.main import create_app
from api.settings_api import bounds_for, suggested_max
from api.sync_runner import TZ, SyncRunner
from tests.test_api import engine, login, make_settings  # noqa: F401  (engine is a fixture)
from tests.test_sync_db import FakeClientWithTokens, streams
from tools import db
from tools.secretbox import decrypt, encrypt

KEY = "x" * 32


class FakeAuth:
    def __init__(self, mfa=False):
        self.mfa = mfa

    def start(self, email, password):
        if password != "garmin-pw":
            raise GarminLoginError("Garmin weigert de inlog: controleer e-mail en wachtwoord (of de MFA-code).")
        return ("mfa", {"email": email}) if self.mfa else ("ok", f"tokens-{email}")

    def finish(self, handle, code):
        if code != "123456":
            raise GarminLoginError("Garmin weigert de inlog: controleer e-mail en wachtwoord (of de MFA-code).")
        return f"tokens-{handle['email']}"


@pytest.fixture
def make(engine, tmp_path, monkeypatch):  # noqa: F811
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", key)

    def build(auth=None):
        app = create_app(
            engine=engine,
            settings=make_settings(),
            garmin_auth=auth or FakeAuth(),
            garmin_client=FakeClientWithTokens,
            read_streams=streams,
        )
        c = TestClient(app)
        login(c)
        return app, c, key

    return build


def test_connect_without_mfa_stores_only_encrypted_session(make, engine, monkeypatch):  # noqa: F811
    app, c, key = make()
    started = []
    monkeypatch.setattr(app.state.sync, "start_user", lambda uid, since=None: started.append((uid, since)) or True)
    assert c.get("/api/connections").json()["garmin"]["connected"] is False
    assert c.post("/api/connections/garmin", json={"email": "j@x.nl", "password": "fout"}).status_code == 400
    assert c.post("/api/connections/garmin", json={"email": "j@x.nl", "password": "garmin-pw"}).json() == {"status": "connected"}
    stored = db.get_setting(db.Scope(engine, 1), "garmin_tokens")
    assert "garmin-pw" not in stored and decrypt(stored, key) == "tokens-j@x.nl"
    st = c.get("/api/connections").json()["garmin"]
    assert st["connected"] and st["readable"] is True
    assert started and started[0][0] == 1
    assert c.delete("/api/connections/garmin").json() == {"ok": True}
    assert c.get("/api/connections").json()["garmin"]["connected"] is False


def test_connect_with_mfa(make, monkeypatch):
    app, c, _ = make(FakeAuth(mfa=True))
    monkeypatch.setattr(app.state.sync, "start_user", lambda uid, since=None: True)
    assert c.post("/api/connections/garmin", json={"email": "j@x.nl", "password": "garmin-pw"}).json() == {"status": "mfa"}
    assert c.post("/api/connections/garmin/mfa", json={"code": "000000"}).status_code == 400
    assert c.post("/api/connections/garmin/mfa", json={"code": "123456"}).status_code == 410  # one try per login
    c.post("/api/connections/garmin", json={"email": "j@x.nl", "password": "garmin-pw"})
    assert c.post("/api/connections/garmin/mfa", json={"code": "123456"}).json() == {"status": "connected"}


def test_session_from_another_key_says_reconnect(make, engine):  # noqa: F811
    _, c, _ = make()
    from cryptography.fernet import Fernet

    db.set_setting(db.Scope(engine, 1), "garmin_tokens", encrypt("t", Fernet.generate_key().decode()))
    assert c.get("/api/connections").json()["garmin"]["readable"] is False


def test_agents_cannot_change_connections(make, engine):  # noqa: F811
    app, c, _ = make()
    tok = c.post("/api/agent-tokens", json={"name": "x"}).json()["token"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {tok}"})
    assert agent.post("/api/connections/garmin", json={"email": "a", "password": "b"}).status_code == 403


def test_sync_now_runs_the_users_sync(make, engine):  # noqa: F811
    app, c, key = make()
    assert c.post("/api/connections/sync").status_code == 409  # not connected
    db.set_setting(db.Scope(engine, 1), "garmin_tokens", encrypt("tok", key))
    runner = app.state.sync
    assert runner.sync_user(1) == 0
    names = [a["name"] for a in db.load_activities(db.Scope(engine, 1))]
    assert "Ochtendloop" in names and len(names) == 2  # the fake Garmin run was added
    assert db.get_setting(db.Scope(engine, 1), "sync_state")["last_sync_local"]


def test_an_agent_can_sync_through_mcp(make, engine):  # noqa: F811
    app, c, key = make()

    def sync_now(token):
        agent = TestClient(app, headers={"Authorization": f"Bearer {token}"})
        res = agent.post(
            "/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "sync_now", "arguments": {}}}
        ).json()["result"]
        return res["content"][0]["text"], res["isError"]

    write = c.post("/api/agent-tokens", json={"name": "w"}).json()["token"]  # a read-only connection is OAuth (test_mcp_oauth)
    text, err = sync_now(write)
    assert err and "Koppelingen" in text  # nothing connected yet
    db.set_setting(db.Scope(engine, 1), "garmin_tokens", encrypt("tok", key))
    text, err = sync_now(write)
    assert not err and text.startswith("Sync klaar") and "nieuwe activiteit" in text
    assert "Ochtendloop" in [a["name"] for a in db.load_activities(db.Scope(engine, 1))]


def test_daily_runner_picks_connected_users_not_synced_today(engine):  # noqa: F811
    from api.users import Stores

    db.create_user(engine, "alice", "h", is_admin=True, user_id=1)
    anna = db.create_user(engine, "anna", "h")
    db.set_setting(db.Scope(engine, 1), "garmin_tokens", "x")
    db.set_setting(db.Scope(engine, anna), "garmin_tokens", "x")
    db.set_setting(db.Scope(engine, anna), "sync_state", {"last_sync_local": "2026-10-03 06:01"})
    r = SyncRunner(engine, Stores(engine), key="k")
    assert r.due_users(datetime(2026, 10, 3, 5, 0, tzinfo=TZ)) == []  # before 06:00
    assert r.due_users(datetime(2026, 10, 3, 7, 0, tzinfo=TZ)) == [1]  # anna already synced today


def test_zone_bounds_match_the_old_zones_file():
    assert bounds_for(189, [70, 77, 85, 92.5]) == [132, 147, 162, 176]
    assert bounds_for(182, [70, 77, 85, 92.5]) == [127, 141, 156, 169]
    assert bounds_for(177, [70, 77, 85, 92.5]) == [124, 137, 151, 165]


def test_suggested_max_ignores_a_single_spike():
    acts = [{"sport": "run", "max_hr": 180 + (i % 5)} for i in range(60)] + [{"sport": "run", "max_hr": 230}]
    assert suggested_max(acts)["run"] == 184 and suggested_max([])["ride"] is None


def test_zones_and_profile_settings(make, engine):  # noqa: F811
    _, c, _ = make()
    got = c.get("/api/settings/zones").json()
    assert got["percent"] == [70, 77, 85, 92.5] and got["zones"]["run"]["bounds"] == [132, 147, 162, 176]
    out = c.put("/api/settings/zones", json={"sports": {"run": {"max_hr": 190}, "ride": {"max_hr": 183, "estimate": True}}}).json()
    assert out["zones"]["run"]["bounds"] == bounds_for(190, [70, 77, 85, 92.5]) and out["zones"]["ride"]["estimate"] is True
    assert c.put("/api/settings/zones", json={"percent": [70, 60, 85, 92], "sports": {}}).status_code == 422
    assert c.put("/api/settings/zones", json={"sports": {"run": {"max_hr": 300}}}).status_code == 422
    assert c.put("/api/settings/profile", json={"birth_year": 1990, "weight_kg": 78}).json() == {"birth_year": 1990, "weight_kg": 78}
    assert c.put("/api/settings/profile", json={"weight_kg": 10}).status_code == 422
    assert c.get("/api/settings/profile").json()["birth_year"] == 1990


def test_wahoo_login_round_trip_stores_encrypted_tokens_and_starts_a_sync(make, engine, monkeypatch):  # noqa: F811
    from urllib.parse import parse_qs, urlparse

    from tools import wahoo

    monkeypatch.setenv("WAHOO_CLIENT_ID", "cid")
    monkeypatch.setenv("WAHOO_CLIENT_SECRET", "secret")
    monkeypatch.setenv("WAHOO_REDIRECT_URI", "https://app.example/api/connections/wahoo/callback")
    exchanged = []
    monkeypatch.setattr(
        wahoo,
        "exchange_code",
        lambda code, uri, creds: exchanged.append((code, uri)) or {"access_token": "a", "refresh_token": "r", "expires_at": 1},
    )
    app, c, key = make()
    started = []
    monkeypatch.setattr(app.state.sync, "start_user", lambda uid, since=None: started.append(uid) or True)
    assert c.get("/api/connections").json()["wahoo"] == {
        "available": True,
        "connected": False,
        "readable": None,
        "connected_at": None,
        "last_workout_day": None,
        "failed": False,
    }
    url = c.get("/api/connections/wahoo/start").json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["cid"] and q["redirect_uri"] == ["https://app.example/api/connections/wahoo/callback"]
    # a wrong state does not connect, and uses up the login
    r = c.get("/api/connections/wahoo/callback", params={"code": "c1", "state": "wrong"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("?wahoo=expired") and not exchanged
    url = c.get("/api/connections/wahoo/start").json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    r = c.get("/api/connections/wahoo/callback", params={"code": "c1", "state": state}, follow_redirects=False)
    assert r.headers["location"] == "/settings/connections/?wahoo=connected" and exchanged == [
        ("c1", "https://app.example/api/connections/wahoo/callback")
    ]
    stored = db.get_setting(db.Scope(engine, 1), "wahoo_tokens")
    assert "refresh_token" not in stored and wahoo.load_tokens(stored, key)["refresh_token"] == "r" and started == [1]
    st = c.get("/api/connections").json()["wahoo"]
    assert st["connected"] and st["readable"] is True and st["connected_at"]


def test_wahoo_denied_at_wahoo_and_not_configured(make, monkeypatch):  # noqa: F811
    monkeypatch.delenv("WAHOO_CLIENT_ID", raising=False)
    app, c, key = make()
    assert c.get("/api/connections/wahoo/start").json()["code"] == "wahoo_not_configured"
    assert c.get("/api/connections").json()["wahoo"]["available"] is False
    r = c.get("/api/connections/wahoo/callback", params={"error": "access_denied"}, follow_redirects=False)
    assert r.headers["location"].endswith("?wahoo=denied")


def test_disconnecting_wahoo_revokes_access_and_removes_only_what_came_through_it(make, engine, monkeypatch):  # noqa: F811
    from tools import wahoo

    monkeypatch.setenv("WAHOO_CLIENT_ID", "cid")
    monkeypatch.setenv("WAHOO_CLIENT_SECRET", "secret")
    revoked = []
    monkeypatch.setattr(wahoo.WahooClient, "deauthorize", lambda self: revoked.append(self.tokens()["access_token"]))
    app, c, key = make()
    s = db.Scope(engine, 1)
    wahoo.save_tokens(s, {"access_token": "a", "refresh_token": "r", "expires_at": 9e9}, key)
    db.upsert_activity(
        s,
        {
            "start_utc": "2026-09-20T08:00:00Z",
            "start_local": "2026-09-20T10:00:00",
            "sport": "ride",
            "distance_km": 40.0,
            "sources": {"wahoo_api": {"id": 2}},
        },
    )
    before = len(db.load_activities(s))
    r = c.delete("/api/connections/wahoo").json()
    assert r["ok"] and r["removed"] == 1 and revoked == ["a"]
    assert db.get_setting(s, "wahoo_tokens") is None and len(db.load_activities(s)) == before - 1
    assert c.get("/api/connections").json()["wahoo"]["connected"] is False
