"""The skin diary (api/skin.py, tools/skin.py): invisible without SKIN_DIARY_USERS, saving and merging a day, the photo
without metadata, the week view next to sleep and training, the CSV and the MCP tools. All data here is made up."""

import hashlib
import io
import json
import zipfile
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

import api.main
from api import betas
from api.main import TZ, create_app
from tests.test_api import engine, login, make_settings  # noqa: F401  (engine is a fixture)
from tests.test_multiuser_api import register
from tests.test_nutrition_match import jpeg
from tools import db, skin

TODAY = date(2026, 3, 18)
TOKEN = "skin-test-token"
NOT_FOUND = {"detail": "Not Found"}
ROUTES = (
    ("get", "/api/skin/day"),
    ("put", "/api/skin/day/2026-03-18"),
    ("delete", "/api/skin/day/2026-03-18"),
    ("post", "/api/skin/photo?day=2026-03-18"),
    ("delete", "/api/skin/photo?day=2026-03-18"),
    ("get", "/api/skin/photos/1"),
    ("get", "/api/skin/overview"),
    ("get", "/api/skin/export.csv"),
)


@pytest.fixture
def app(engine, monkeypatch):  # noqa: F811
    monkeypatch.delenv("SKIN_DIARY_USERS", raising=False)
    monkeypatch.setattr(api.main, "today", lambda: TODAY)
    monkeypatch.setattr(api.main, "now", lambda: datetime(2026, 3, 18, 21, 0, tzinfo=TZ))
    return create_app(engine=engine, settings=make_settings(agent_token_hash=hashlib.sha256(TOKEN.encode()).hexdigest()))


@pytest.fixture
def client(app):
    c = TestClient(app)
    assert login(c).status_code == 200  # alice, user 1
    return c


@pytest.fixture
def allowed(monkeypatch):
    monkeypatch.setenv("SKIN_DIARY_USERS", "someone-else, Alice")


def hit(c, method, path):
    kw = {"json": {}} if method == "put" else {"content": jpeg()} if method == "post" else {}
    return getattr(c, method)(path, **kw)


def rpc(c, method, params=None):
    r = c.post(
        "/api/mcp", headers={"Authorization": f"Bearer {TOKEN}"}, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    )
    return r.json()["result"]


def call(c, name, **args):
    res = rpc(c, "tools/call", {"name": name, "arguments": args})
    return res["content"][0]["text"], res["isError"]


def tools(c):
    return {t["name"] for t in rpc(c, "tools/list")["tools"]}


def test_without_the_list_the_diary_does_not_exist(app, client):
    nothing = client.get("/api/skin/no-such-page")
    assert nothing.status_code == 404 and nothing.json() == NOT_FOUND
    for method, path in ROUTES:
        r = hit(client, method, path)
        assert (r.status_code, r.json()) == (404, NOT_FOUND), (method, path)
        r = hit(TestClient(app), method, path)  # not logged in: no 401 that would tell the route is there
        assert (r.status_code, r.json()) == (404, NOT_FOUND), (method, path)
    assert "skin" not in client.get("/api/me").json()["betas"]
    assert not any(p.startswith("/api/skin") for p in app.openapi()["paths"])  # left out of the schema too
    assert not tools(client) & {"add_skin_entry", "get_skin_diary"}
    assert call(client, "add_skin_entry", itch=3) == ("Fout: Onbekende tool add_skin_entry", True)
    assert call(client, "made_up_tool") == ("Fout: Onbekende tool made_up_tool", True)


def test_only_the_listed_account_sees_it(app, client, allowed):
    assert client.get("/api/me").json()["betas"] == ["skin"]
    assert client.get("/api/skin/day").status_code == 200
    assert {"add_skin_entry", "get_skin_diary"} <= tools(client)
    login(client)
    client.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    anna, r = register(app)
    assert r.status_code in (200, 201), r.text
    assert "skin" not in anna.get("/api/me").json()["betas"]
    for method, path in ROUTES:
        r = hit(anna, method, path)
        assert (r.status_code, r.json()) == (404, NOT_FOUND), (method, path)
    # not in the admin hub, so nobody can switch it on for anyone there (the hub refuses features outside betas.ids())
    assert "skin" not in betas.ids() and all(f["id"] != "skin" for f in betas.BETA_FEATURES)


def test_a_day_is_saved_merged_and_checked(client, allowed):
    r = client.put("/api/skin/day/2026-03-17", json={"itch": 6, "redness": 4, "locations": ["nose", "cheeks"], "food": ["Pindakaas"]})
    assert r.status_code == 200, r.text
    e = r.json()["entry"]
    assert (e["itch"], e["redness"], e["locations"], e["food"], e["bumps"]) == (6, 4, ["cheeks", "nose"], ["Pindakaas"], None)
    e = client.put("/api/skin/day/2026-03-17", json={"bumps": 3, "flaking": True}).json()["entry"]
    assert (e["itch"], e["bumps"], e["flaking"], e["food"]) == (6, 3, True, ["Pindakaas"])  # left out: kept
    e = client.put("/api/skin/day/2026-03-17", json={"food": [], "itch": None}).json()["entry"]
    assert (e["itch"], e["food"]) == (None, [])  # null and an empty list clear a field
    for bad, code in (
        ({"itch": 11}, "invalid_scale"),
        ({"redness": "veel"}, "invalid_scale"),
        ({"locations": ["elbow"]}, "invalid_choice"),
        ({"flaking": "yes"}, "invalid_flag"),
        ({"mood": 5}, "unknown_field"),
    ):
        r = client.put("/api/skin/day/2026-03-17", json=bad)
        assert r.status_code == 422 and r.json()["code"] == code, bad
    assert client.put("/api/skin/day/17-03", json={}).json()["code"] == "invalid_day"
    assert client.get("/api/skin/day", params={"day": "2026-03-17"}).json()["entry"]["bumps"] == 3
    assert client.delete("/api/skin/day/2026-03-17").status_code == 204
    assert client.get("/api/skin/day", params={"day": "2026-03-17"}).json()["entry"] is None
    assert client.delete("/api/skin/day/2026-03-17").status_code == 404


def test_the_photo_loses_its_metadata_and_goes_with_the_day(client, allowed, engine):  # noqa: F811
    e = client.post("/api/skin/photo", params={"day": "2026-03-18"}, content=jpeg()).json()["entry"]
    stored = client.get(f"/api/skin/photos/{e['photo_id']}")
    assert stored.status_code == 200 and stored.headers["content-type"] == "image/jpeg"
    assert b"Exif" not in stored.content and b"GPS" not in stored.content
    assert client.post("/api/skin/photo", params={"day": "2026-03-18"}, content=b"GIF89a").json()["code"] == "photo_invalid"
    again = client.post("/api/skin/photo", params={"day": "2026-03-18"}, content=jpeg()).json()["entry"]
    assert client.get(f"/api/skin/photos/{e['photo_id']}").status_code == 404  # replaced, not kept beside it
    assert client.put("/api/skin/day/2026-03-18", json={"photo_id": 999}).json()["entry"]["photo_id"] == again["photo_id"]
    assert client.delete("/api/skin/day/2026-03-18").status_code == 204
    with engine.connect() as conn:
        assert conn.execute(db.skin_photos.select()).first() is None


def test_week_view_next_to_sleep_and_training():
    entries = [
        {"day": f"2026-03-{d:02d}", "itch": i, "redness": r, "bumps": b, "flaking": f, "burning": False, "food": food}
        for d, i, r, b, f, food in (
            (9, 2, 2, 1, False, []),
            (10, 3, 6, 4, True, ["Witte chocolade"]),
            (11, 2, 3, 1, False, []),
            (12, 5, 7, 5, True, ["witte chocolade", "Alcohol"]),
            (16, 1, 1, 0, False, []),
        )
    ]
    wellness = {
        "2026-03-09": {"sleep_h": 7.5},
        "2026-03-10": {"sleep_h": 5.2},
        "2026-03-11": {"sleep_h": 7.8},
        "2026-03-12": {"sleep_h": 5.5},
    }
    acts = [{"id": "a1", "start_local": "2026-03-10T18:00:00", "sport": "run", "moving_time_s": 3600, "avg_hr": 150}]
    weeks = skin.weeks(entries, acts, wellness, 50, {"run": 190})
    assert [(w["week"], w["days"], w["redness"], w["flaking_days"], w["sessions"], w["training_min"]) for w in weeks] == [
        ("2026-W11", 4, 4.5, 2, 1, 60),
        ("2026-W12", 1, 1.0, 0, 0, 0),
    ]
    assert weeks[0]["sleep_h"] == 6.5 and weeks[0]["load"] > 0
    comp = {(c["kind"], c["label"]): c for c in skin.comparisons(entries, acts, wellness)}
    assert comp[("short_sleep", "< 6 h")]["with"] == {"days": 2, "redness": 6.5}
    assert comp[("short_sleep", "< 6 h")]["without"] == {"days": 2, "redness": 2.5}
    assert comp[("food", "Witte chocolade")]["with"]["days"] == 2  # one tag, whatever its capitals
    assert ("training", "") not in comp  # one training day: too few to compare
    assert ("food", "Alcohol") not in comp


def test_overview_and_csv_for_the_dermatologist(client, allowed):
    client.put("/api/skin/day/2026-03-16", json={"itch": 4, "redness": 5, "locations": ["chin", "mouth"], "products": ["Crème A"]})
    client.put(
        "/api/skin/day/2026-03-18", json={"heating": True, "sport": [{"name": "Hardlopen", "red": True}], "note": "Na het sporten; rood"}
    )
    o = client.get("/api/skin/overview", params={"from": "2026-03-01", "to": "2026-03-31"}).json()
    assert [e["day"] for e in o["entries"]] == ["2026-03-16", "2026-03-18"] and o["weeks"][0]["week"] == "2026-W12"
    assert client.get("/api/skin/overview", params={"from": "2026-03-31", "to": "2026-03-01"}).json()["code"] == "invalid_range"
    r = client.get("/api/skin/export.csv", params={"from": "2026-03-01", "to": "2026-03-31"})
    assert r.headers["content-type"].startswith("text/csv") and "huiddagboek-2026-03-01-2026-03-31.csv" in r.headers["content-disposition"]
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0].startswith("datum;jeuk (0-10);roodheid (0-10)")
    assert lines[1].startswith("2026-03-16;4;5;;;kin, rond de mond;;Crème A;")
    assert "Hardlopen (rood)" in lines[2] and ";ja;" in lines[2] and '"Na het sporten; rood"' in lines[2]


def test_tell_it_to_claude(client, allowed):
    text, err = call(client, "add_skin_entry", itch=5, food=["Witte chocolade"], products=["Crème A"])
    assert not err and "2026-03-18" in text and "Witte chocolade" in text
    text, err = call(client, "add_skin_entry", day="2026-03-18", food=["alcohol"], note="Jeukt vooral 's avonds", locations=["nose"])
    e = skin.get(db.Scope(client.app.state.engine, 1), "2026-03-18")
    assert (e["itch"], e["food"], e["products"], e["locations"]) == (5, ["Witte chocolade", "alcohol"], ["Crème A"], ["nose"])
    call(client, "add_skin_entry", note="Morgen nieuwe zeep")
    assert skin.get(db.Scope(client.app.state.engine, 1), "2026-03-18")["note"] == "Jeukt vooral 's avonds\nMorgen nieuwe zeep"
    assert call(client, "add_skin_entry", itch=12)[1] is True
    assert call(client, "add_skin_entry", day="2026-03-19", itch=1)[1] is True  # not ahead of today
    text, err = call(client, "get_skin_diary", **{"from": "2026-03-01"})
    assert not err and "# Huiddagboek 2026-03-01 t/m 2026-03-18" in text and "## Per week" in text


def test_export_and_deletion_of_the_account_include_the_diary(app, client, allowed, engine, monkeypatch):  # noqa: F811
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "Q0FGRUJBQkVDQUZFQkFCRUNBRkVCQUJFQ0FGRUJBQkU=")
    client.put("/api/skin/day/2026-03-18", json={"itch": 2})
    client.post("/api/skin/photo", params={"day": "2026-03-18"}, content=jpeg())
    z = zipfile.ZipFile(io.BytesIO(client.get("/api/account/export").content))
    assert [e["itch"] for e in json.loads(z.read("skin_entries.json"))] == [2]
    assert any(n.startswith("skin/") for n in z.namelist())
    db.delete_user(engine, 1)
    with engine.connect() as conn:
        assert conn.execute(db.skin_entries.select()).first() is None and conn.execute(db.skin_photos.select()).first() is None
