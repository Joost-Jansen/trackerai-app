import bcrypt
import pytest
from fastapi.testclient import TestClient

from api.main import Settings, create_app
from tests.helpers import square_loop
from tools import db
from trackerai_testing import new_database_url

PASSWORD = "test-wachtwoord-123"


@pytest.fixture
def engine(tmp_path):
    e = db.connect(new_database_url())
    db.create_schema(e)
    s = db.Scope(e, 1)  # user 1 = the admin that bootstrap creates from make_settings()
    db.upsert_activity(
        s,
        {
            "start_utc": "2026-09-29T06:00:00Z",
            "start_local": "2026-09-29T08:00:00",
            "sport": "run",
            "name": "Ochtendloop",
            "distance_km": 10.0,
            "moving_time_s": 3300,
            "avg_hr": 140,
            "streams": {"time": [0, 1], "heartrate": [140, 141], "latlng": square_loop()[:5]},
            "sources": {"garmin": {"id": 1, "raw": {}}},
        },
    )
    db.set_setting(s, "zones", {"run": {"bounds": [132, 147, 162, 176], "max_hr": 189}})
    db.set_setting(s, "sync_state", {"last_sync_local": "2026-09-30 06:02"})
    return e


def make_settings(**kw):
    return Settings(
        user="alice",
        password_hash=bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode(),
        jwt_secret="x" * 32,
        cookie_secure=False,
        **kw,
    )


@pytest.fixture
def client(engine, tmp_path):
    return TestClient(create_app(engine=engine, settings=make_settings()))


def login(client, password=PASSWORD, user="alice"):
    return client.post("/api/login", json={"username": user, "password": password})


def test_health_is_open(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_data_requires_login(client):
    assert client.get("/api/dashboard").status_code == 401
    assert client.get("/api/me").status_code == 401


def test_wrong_password_is_rejected(client):
    assert login(client, password="fout").status_code == 401
    assert login(client, user="iemand", password=PASSWORD).status_code == 401


def test_login_sets_httponly_cookie_and_unlocks_data(client):
    r = login(client)
    assert r.status_code == 200
    assert "httponly" in r.headers["set-cookie"].lower()
    me = client.get("/api/me").json()
    assert {k: me[k] for k in ("id", "username", "display_name", "is_admin", "via", "totp_enabled", "locale", "in_app")} == {
        "id": 1,
        "username": "alice",
        "display_name": None,
        "is_admin": True,
        "via": "cookie",
        "totp_enabled": False,
        "locale": None,
        "in_app": True,
    }
    d = client.get("/api/dashboard").json()
    assert d["last_sync"] == "2026-09-30 06:02"
    assert d["recent"][0]["name"] == "Ochtendloop"


def test_logout_clears_session(client):
    login(client)
    client.post("/api/logout")
    assert client.get("/api/me").status_code == 401


def test_repeated_failures_lock_the_account_for_a_while(client):
    for _ in range(10):
        login(client, password="fout")
    r = login(client)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_tampered_token_is_rejected(client):
    login(client)
    client.cookies.clear()  # replace the login's cookie (httpx2 2.16 keeps both when only the value is set)
    client.cookies.set("trackerai_session", "abc.def.ghi")
    assert client.get("/api/me").status_code == 401


def test_dashboard_lists_activity_without_gps(client):
    login(client)
    assert "streams" not in client.get("/api/dashboard").json()["recent"][0]


def test_dashboard_reads_the_database_live(client, engine):
    login(client)
    db.set_setting(db.Scope(engine, 1), "sync_state", {"last_sync_local": "2026-10-01 06:00"})
    assert client.get("/api/dashboard").json()["last_sync"] == "2026-10-01 06:00"


def test_history_and_trends_endpoints(client):
    for path in ("/api/activities", "/api/heatmap", "/api/trends"):
        assert client.get(path).status_code == 401
    login(client)
    items = client.get("/api/activities").json()
    assert [a["name"] for a in items] == ["Ochtendloop"]
    detail = client.get(f"/api/activities/{items[0]['id']}").json()
    assert detail["track"]["latlng"] and len(detail["track"]["zone"]) == len(detail["track"]["latlng"])
    assert client.get("/api/activities/bestaat-niet").status_code == 404
    assert len(client.get("/api/heatmap").json()["tracks"]) == 1
    assert "form" in client.get("/api/trends").json()


def test_plans_import_edit_and_match(client):
    assert client.get("/api/plans/active").status_code == 401
    login(client)
    assert client.get("/api/plans/active").json() == {"persistent": True, "plan": None}
    text = "datum,sport,km,zone\n2026-09-29,lopen,10,Z2\n2026-09-30,lopen,8,Z2"
    preview = client.post("/api/plans/import", json={"text": text, "preview": True}).json()
    assert preview["saved"] is False and len(preview["sessions"]) == 2
    res = client.post("/api/plans/import", json={"text": text, "title": "Test"}).json()
    plan = res["plan"]
    assert plan["title"] == "Test" and plan["status"] == "active"
    assert plan["sessions"][0]["status"] == "done"  # the 10 km run on 2026-09-29 in the fixture
    sessions = [{k: s[k] for k in ("date", "sport", "distance_km")} for s in plan["sessions"]][:1]
    edited = client.put(f"/api/plans/{plan['id']}/sessions", json=sessions).json()
    assert len(edited["sessions"]) == 1
    assert client.patch(f"/api/plans/{plan['id']}", json={"status": "fout"}).status_code == 422
    assert client.patch(f"/api/plans/{plan['id']}", json={"goal": "marathon"}).json()["goal"] == "marathon"


def test_plan_links_set_and_cleared_by_hand(client):
    login(client)
    # the fixture has a 10 km run on 2026-09-29; the plan has runs on 28 Sep (near) and 4 Oct
    plan = client.post(
        "/api/plans", json={"title": "Blok", "sessions": [{"date": "2026-09-28", "sport": "run"}, {"date": "2026-10-04", "sport": "run"}]}
    ).json()
    aid = plan["sessions"][0]["activity_ids"][0]
    assert plan["sessions"][0]["match"] == "near"
    url = f"/api/plans/{plan['id']}/links/{aid}"
    out = client.put(url, json={"session_date": None}).json()
    assert [s["status"] for s in out["sessions"]] == ["missed", "missed"] and out["weeks"][0]["done_km"] == 10
    out = client.put(url, json={"session_date": "2026-10-04"}).json()
    assert [s.get("match") for s in out["sessions"]] == [None, "manual"]
    assert client.put(url, json={"session_date": "2026-10-01"}).json()["code"] == "no_session_to_link"
    assert client.put(f"/api/plans/{plan['id']}/links/bestaat-niet", json={"session_date": None}).status_code == 404
    assert client.delete(url).json()["sessions"][0]["match"] == "near"


def test_plan_sessions_replaced_from_table(client):
    login(client)
    plan = client.post("/api/plans", json={"title": "Blok", "sessions": [{"date": "2026-10-01", "sport": "run"}]}).json()
    res = client.put(
        f"/api/plans/{plan['id']}/table",
        json={"text": "| Datum | Sport | Km |\n|---|---|---|\n| 2026-10-02 | lopen | 12 |\n| 2026-10-03 | rust | |"},
    ).json()
    assert [s["date"] for s in res["plan"]["sessions"]] == ["2026-10-02", "2026-10-03"]
    assert client.put(f"/api/plans/{plan['id']}/table", json={"text": "geen tabel"}).status_code == 422


def test_routes_endpoints_are_wired(client):
    assert client.get("/api/routes").status_code == 401
    login(client)
    assert client.get("/api/routes").json() == []
    assert client.get("/api/routes/suggest?km=10").json() == {"km": 10.0, "options": []}


def test_dashboard_has_upcoming_sessions_and_readiness(client):
    login(client)
    assert client.get("/api/dashboard").json()["upcoming"] == []
    client.post(
        "/api/plans",
        json={
            "title": "Blok",
            "sessions": [{"date": "2020-01-01", "sport": "run"}, {"date": "2099-01-01", "sport": "run", "distance_km": 10}],
        },
    )
    d = client.get("/api/dashboard").json()
    assert [s["date"] for s in d["upcoming"]] == ["2099-01-01"] and d["plan_title"] == "Blok"
    assert "readiness" in d
    assert d["plan_week"]["sessions"]["total"] == 0 and d["race"] is None
    pid = client.get("/api/plans/active").json()["plan"]["id"]
    client.patch(f"/api/plans/{pid}", json={"race": "Marathon, 2099-01-01"})
    assert client.get("/api/dashboard").json()["race"]["name"] == "Marathon"


def test_trends_uses_the_active_plan_goal_and_reports_the_sync_stop(client, engine):
    login(client)
    db.create_plan(db.Scope(engine, 1), title="Doel", author="alice", goal="halve marathon in 1:50:00", race="2099-05-01")
    t = client.get("/api/trends").json()
    assert t["goal"] and t["goal"]["km"] > 21
    assert "stopped_at_sync" in t and "form_until" in t


def test_trends_without_plan_has_no_goal(client):
    login(client)
    assert client.get("/api/trends").json()["goal"] is None


def test_a_draft_plan_leaves_the_active_plan_alone_until_activated(client):
    login(client)
    active = client.post(
        "/api/plans", json={"title": "Marathon", "sessions": [{"date": "2026-09-29", "sport": "run", "distance_km": 10}]}
    ).json()
    draft = client.post(
        "/api/plans", json={"title": "Advent", "status": "draft", "sessions": [{"date": "2026-12-01", "sport": "run"}]}
    ).json()
    assert draft["status"] == "draft" and client.get("/api/plans/active").json()["plan"]["id"] == active["id"]
    assert client.post("/api/plans", json={"title": "x", "status": "finished"}).json()["code"] == "invalid_plan_status"

    plans = {p["title"]: p for p in client.get("/api/plans").json()["plans"]}
    assert plans["Marathon"]["summary"] == {
        "start": "2026-09-29",
        "end": "2026-09-29",
        "planned": 1,
        "done": 1,
        "missed": 0,
        "open": 0,
        "planned_km": 10.0,
        "done_km": 10.0,
        "complete": True,
    }
    assert plans["Advent"]["status"] == "draft" and plans["Advent"]["summary"]["open"] == 1

    client.patch(f"/api/plans/{draft['id']}", json={"status": "active"})
    statuses = {p["title"]: p["status"] for p in client.get("/api/plans").json()["plans"]}
    assert statuses == {"Marathon": "finished", "Advent": "active"}


def test_achievements_are_your_own_plus_every_finished_plan(client):
    login(client)
    plan = client.post("/api/plans", json={"title": "Blok", "sessions": [{"date": "2026-09-29", "sport": "run", "distance_km": 10}]}).json()
    assert client.get("/api/achievements").json() == {"items": []}
    client.patch(f"/api/plans/{plan['id']}", json={"status": "finished"})
    added = client.post(
        "/api/achievements",
        json={"day": "2026-12-24", "title": "Adventskalender", "kind": "challenge", "sport": "lopen", "plan_id": plan["id"]},
    ).json()
    assert added["sport"] == "run" and added["author"] == "alice"
    items = client.get("/api/achievements").json()["items"]
    assert [(a["source"], a["title"], a["day"]) for a in items] == [
        ("manual", "Adventskalender", "2026-12-24"),
        ("plan", "Blok", "2026-09-29"),
    ]
    assert items[1]["summary"]["complete"] is True

    assert client.post("/api/achievements", json={"day": "24-12", "title": "x"}).json()["code"] == "invalid_date"
    assert (
        client.post("/api/achievements", json={"day": "2026-12-24", "title": "x", "kind": "x"}).json()["code"] == "invalid_achievement_kind"
    )
    assert client.post("/api/achievements", json={"day": "2026-12-24", "title": "x", "plan_id": 999}).json()["code"] == "plan_not_found"
    assert client.delete(f"/api/achievements/{added['id']}").json() == {"ok": True}
    assert client.delete(f"/api/achievements/{added['id']}").json()["code"] == "achievement_not_found"
