"""Example mode (api/example.py): the first-run walk reads a shared, read-only example account with `X-Example-Data: 1`."""

import hashlib
import math
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from api import example
from api.main import create_app, today
from scripts.seed_demo import HOME as DEMO_HOME
from tests.test_api import engine, login, make_settings  # noqa: F401  (engine is a fixture)
from tools import db

EX = {"X-Example-Data": "1"}
TOKEN = "example-test-token"


@pytest.fixture(scope="module")
def example_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("example")  # one seed for the whole module


@pytest.fixture
def app(engine, tmp_path, example_dir):  # noqa: F811
    settings = make_settings(agent_token_hash=hashlib.sha256(TOKEN.encode()).hexdigest())
    return create_app(engine=engine, settings=settings, example_dir=example_dir)


@pytest.fixture
def alice(app):
    c = TestClient(app)
    assert login(c).status_code == 200
    return c


def snapshot(engine):  # noqa: F811
    """Every row in the users' database, to prove example mode never changes it."""
    with engine.connect() as conn:
        names = [r[0] for r in conn.execute(text("select name from sqlite_master where type='table'"))]
        return {name: sorted(map(repr, conn.execute(text(f'select * from "{name}"')).all())) for name in names}


def test_example_mode_reads_the_example_account(alice):
    real = alice.get("/api/activities").json()
    assert [a["name"] for a in real] == ["Ochtendloop"]
    acts = alice.get("/api/activities", headers=EX).json()
    assert len(acts) > 40 and "Ochtendloop" not in {a["name"] for a in acts}
    assert {a["sport"] for a in acts} == {"run", "ride", "swim"}
    detail = alice.get(f"/api/activities/{acts[0]['id']}", headers=EX).json()
    assert detail["series"]["heartrate"] and detail["laps"]
    # one account's ids are not the other's
    assert alice.get(f"/api/activities/{acts[0]['id']}").status_code == 404
    assert alice.get(f"/api/activities/{real[0]['id']}", headers=EX).status_code == 404

    dash = alice.get("/api/dashboard", headers=EX).json()
    assert dash["recent"] and dash["plan_title"] == "Marathon in 16 weeks" and dash["upcoming"]
    assert alice.get("/api/dashboard").json()["recent"][0]["name"] == "Ochtendloop"
    trends = alice.get("/api/trends", headers=EX).json()
    assert len(trends["weekly"]) > 10 and trends["recovery_daily"]
    assert alice.get("/api/plans/active", headers=EX).json()["plan"]["sessions"]
    assert alice.get("/api/plans", headers=EX).json()
    assert alice.get("/api/plans/active").json()["plan"] is None
    assert len(alice.get("/api/routes?sport=run", headers=EX).json()) >= 3
    assert alice.get("/api/routes?sport=ride", headers=EX).json()
    assert len(alice.get("/api/heatmap", headers=EX).json()["tracks"]) > 20
    assert alice.get("/api/wellness/day", headers=EX).json()["series"]["hr"]
    assert alice.get("/api/zones?period=month", headers=EX).json()["zones"]
    assert alice.get("/api/zones/history?period=week", headers=EX).json()["items"]
    assert alice.get("/api/settings/zones", headers=EX).json()["zones"]["run"]["max_hr"] == 190
    assert alice.get("/api/settings/profile", headers=EX).json()["weight_kg"] == 72.0
    assert alice.get("/api/settings/profile").json().get("weight_kg") is None
    assert "synthetic" in alice.get("/api/docs/profile", headers=EX).json()["body"]
    assert {e["title"] for e in alice.get("/api/entries?kind=log", headers=EX).json()} >= {"Weekly review"}
    assert alice.get("/api/entries").json() == []
    assert alice.get("/api/context", headers=EX).status_code == 200
    assert alice.get("/api/routes/candidates?sport=run", headers=EX).status_code == 200


def test_example_gps_is_around_its_own_made_up_area(alice):
    tracks = alice.get("/api/heatmap", headers=EX).json()["tracks"]
    points = [p for t in tracks for p in t]
    lat = sum(p[0] for p in points) / len(points)
    lon = sum(p[1] for p in points) / len(points)
    assert math.dist((lat, lon), example.HOME) < 0.1
    assert math.dist((lat, lon), DEMO_HOME) > 0.5  # not the demo's loops either


def test_personal_things_stay_the_real_user(alice):
    me = alice.get("/api/me", headers=EX).json()
    assert me["id"] == 1 and me["username"] == "alice"
    assert alice.get("/api/onboarding", headers=EX).json() == alice.get("/api/onboarding").json()
    assert alice.get("/api/connections", headers=EX).json() == alice.get("/api/connections").json()
    assert alice.get("/api/agent-tokens", headers=EX).json() == []
    assert alice.get("/api/feedback", headers=EX).json() == []


def test_every_write_is_refused_and_nothing_changes(alice, engine, app):  # noqa: F811
    before = snapshot(engine)
    aid = alice.get("/api/activities").json()[0]["id"]
    writes = [
        ("post", "/api/entries", {"kind": "log", "title": "t", "body": "b"}),
        ("put", "/api/docs/profile", {"body": "x"}),
        ("patch", f"/api/activities/{aid}", {"distance_km": 5}),
        ("put", "/api/settings/zones", {"percent": [70, 77, 85, 92.5], "sports": {}}),
        ("put", "/api/settings/profile", {"weight_kg": 60}),
        ("post", "/api/plans", {"title": "p", "sessions": []}),
        ("put", "/api/onboarding", {"step": 3}),
        ("patch", "/api/account", {"display_name": "x"}),
        ("post", "/api/connections/sync", None),
        ("delete", "/api/connections/garmin", None),
        ("post", "/api/activities/recompute", None),
        ("post", "/api/feedback", {"kind": "idea", "message": "hello there"}),
        ("patch", "/api/routes/r1", {"name": "x"}),
    ]
    for method, path, body in writes:
        r = getattr(alice, method)(path, headers=EX, **({"json": body} if body is not None else {}))
        assert r.status_code == 403 and r.json()["code"] == "example_read_only", (method, path, r.text)
    assert snapshot(engine) == before
    # the example database itself cannot be written either, not even past the API
    store = app.state.examples.store()
    with pytest.raises(OperationalError):
        db.add_entry(store.scope, "log", "t", "b", "x")
    # and without the header the same write works as usual
    assert alice.post("/api/entries", json={"kind": "log", "title": "mine", "body": "b"}).status_code == 200
    assert [e["title"] for e in alice.get("/api/entries").json()] == ["mine"]
    assert "mine" not in {e["title"] for e in alice.get("/api/entries", headers=EX).json()}


def test_admin_mcp_and_tokens_ignore_the_header(alice):
    users = alice.get("/api/trackerai/admin/accounts", headers=EX).json()
    assert [u["username"] for u in users] == ["alice"]
    assert alice.patch("/api/trackerai/admin/registration", headers=EX, json={"registration": "invite"}).json()["registration"] == "invite"
    assert alice.post("/api/admin/invites", headers=EX, json={"days": 1}).status_code == 200
    made = alice.post("/api/agent-tokens", headers=EX, json={"name": "laptop"})
    assert made.status_code == 200 and made.json()["token"]

    bearer = {"Authorization": f"Bearer {TOKEN}", **EX}
    assert [a["name"] for a in alice.get("/api/activities", headers=bearer).json()] == ["Ochtendloop"]
    assert alice.post("/api/entries", headers=bearer, json={"kind": "log", "title": "agent", "body": "b"}).status_code == 200
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_activities", "arguments": {}}}
    res = alice.post("/api/mcp", headers=bearer, json=rpc).json()["result"]
    assert "Ochtendloop" in res["content"][0]["text"]
    res = alice.post(f"/api/mcp/{TOKEN}", headers=EX, json=rpc).json()["result"]
    assert "Ochtendloop" in res["content"][0]["text"]


def test_example_name_is_reserved(app, alice):
    alice.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    for name in ("example", "Example", " EXAMPLE "):
        r = TestClient(app).post("/api/register", json={"username": name, "email": "someone@example.org", "password": "a-long-password-1", "consent": True})
        assert r.status_code == 409 and r.json()["code"] == "username_reserved"
    assert TestClient(app).post("/api/register", json={"username": "examples", "email": "examples@example.org", "password": "a-long-password-1", "consent": True}).status_code == 200


def test_header_needs_value_one_and_a_login(alice, app):
    assert [a["name"] for a in alice.get("/api/activities", headers={"X-Example-Data": "0"}).json()] == ["Ochtendloop"]
    assert TestClient(app).get("/api/activities", headers=EX).status_code == 401


def rows(path):
    e = example.read_only_engine(path)
    try:
        uid = db.get_user_by_name(e, example.USERNAME)["id"]
        s = db.Scope(e, uid)
        plan = db.active_plan(s)
        return {
            "activities": db.load_activities(s),
            "streams": [db.load_streams(s, a["id"]) for a in db.load_activities(s)[:5]],
            "wellness": db.load_wellness(s),
            "routes": db.load_routes(s),
            "plan": [{k: v for k, v in x.items() if k != "id"} for x in plan["sessions"]],
            "entries": [(x["kind"], x["title"], x["body"], x["day"]) for x in db.list_entries(s)],
            "zones": db.get_setting(s, "zones"),
            "intraday": db.get_intraday(s, db.intraday_days(s)[-1]),
            "user": {k: v for k, v in db.get_user(e, uid, with_hash=True).items() if k not in ("created_at", "last_login_at")},
        }
    finally:
        e.dispose()


def test_seed_is_deterministic(tmp_path, example_dir):
    day = today()
    first = example_dir / f"example-{day.isoformat()}.db"
    if not first.exists():
        example.build(first, day)
    again = tmp_path / "again.db"
    example.build(again, day)
    a, b = rows(first), rows(again)
    assert a == b
    assert a["user"]["password_hash"] == "!" and not a["user"]["is_admin"]
    assert len(a["activities"]) > 40 and len(a["wellness"]) == example.DAYS + 1


def test_a_new_day_gives_a_new_example_database(tmp_path):
    days = iter([date(2026, 3, 1), date(2026, 3, 1), date(2026, 3, 2)])
    ex = example.ExampleData(tmp_path, lambda: next(days))
    s1 = ex.store()
    assert ex.store() is s1 and (tmp_path / "example-2026-03-01.db").exists()
    s2 = ex.store()
    assert s2 is not s1 and max(a["start_local"] for a in s2.activities) < "2026-03-02"
    assert not (tmp_path / "example-2026-03-01.db").exists() and (tmp_path / "example-2026-03-02.db").exists()
