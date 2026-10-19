"""The nutrition API (api/nutrition.py): the beta gate, logging a meal by search, a day's totals against its targets,
editing and deleting, the admin's NEVO import and the Voeding vandaag block on /api/dashboard."""

from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main
from api.main import TZ, create_app
from tests.test_api import engine, login, make_settings  # noqa: F401  (engine is a fixture)
from tests.test_multiuser_api import register
from tools import db
from tools.nutrition import foods

SAMPLE = (Path(__file__).parent / "nevo_sample.csv").read_bytes()
TODAY = date(2026, 10, 19)


@pytest.fixture
def app(engine, monkeypatch):  # noqa: F811
    monkeypatch.setattr(api.main, "today", lambda: TODAY)
    monkeypatch.setattr(api.main, "now", lambda: datetime(2026, 10, 19, 9, 30, tzinfo=TZ))
    foods.invalidate()
    return create_app(engine=engine, settings=make_settings())


@pytest.fixture
def client(app, engine):  # noqa: F811
    c = TestClient(app)
    assert login(c).status_code == 200
    db.set_setting(db.Scope(engine, 1), "profile_facts", {"weight_kg": 78})
    return c


def beta(engine, uid=1, on=True):  # noqa: F811
    db.set_user_beta(engine, uid, "nutrition", on)


def test_every_route_needs_the_beta(client, engine):  # noqa: F811
    for method, path in (("get", "/api/nutrition/day"), ("get", "/api/nutrition/foods/search?q=a"), ("delete", "/api/nutrition/meals/1")):
        r = getattr(client, method)(path)
        assert r.status_code == 403 and r.json()["code"] == "nutrition_off"
    assert client.get("/api/dashboard").json()["nutrition"] is None
    assert "nutrition" not in client.get("/api/me").json()["betas"]
    beta(engine)
    assert client.get("/api/me").json()["betas"] == ["nutrition"]
    assert client.get("/api/nutrition/day").status_code == 200


def test_only_admins_import_nevo(app, client, engine):  # noqa: F811
    assert client.get("/api/nutrition/admin/nevo").json() == {"version": None}
    r = client.post("/api/nutrition/admin/nevo", content=SAMPLE)
    assert r.status_code == 200 and r.json() == {"release": "NEVO-online 2099/1.0", "foods": 9, "added": 9, "updated": 0}
    r = client.post("/api/nutrition/admin/nevo", content=b"not|a|table\n")
    assert r.status_code == 422 and r.json()["code"] == "nevo_format"
    client.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    anna, _ = register(app)
    assert anna.post("/api/nutrition/admin/nevo", content=SAMPLE).status_code == 403


def test_log_a_meal_by_search_and_see_the_day(client, engine):  # noqa: F811
    beta(engine)
    client.post("/api/nutrition/admin/nevo", content=SAMPLE)
    r = client.post("/api/plans", json={"title": "Najaar", "sessions": [{"date": "2026-10-20", "sport": "run", "kind": "Duurloop", "distance_km": 20}]})
    assert r.status_code in (200, 201), r.text
    hits = client.get("/api/nutrition/foods/search", params={"q": "haver"}).json()
    assert hits[0]["ref"] == "nevo:9001" and hits[0]["portion_g"] is None
    r = client.post("/api/nutrition/meals", json={"day": "2026-10-19", "eaten_at": "07:30", "moment": "breakfast", "input": "search",
                                                 "items": [{"food_ref": "nevo:9001", "grams": 80}, {"food_ref": "nevo:9003", "grams": 250}]})
    assert r.status_code == 201, r.text
    meal = r.json()
    assert [i["unit"] for i in meal["items"]] == ["g", "ml"] and meal["totals"]["energy_kcal"] == 411
    day = client.get("/api/nutrition/day").json()
    assert day["day"] == "2026-10-19" and len(day["meals"]) == 1 and day["last_meal"] == "07:30"
    assert day["totals"]["carbs_g"] == 59 and day["per_kg"] == {"carbs": 0.8, "protein": 0.2}  # 19.15 g protein / 78 kg
    assert day["targets"]["weight_kg"] == 78 and day["targets"]["carbs_g"] == [390, 546]  # a long run tomorrow: 5-7 g/kg today
    assert day["context"]["line"] == "tomorrow" and day["context"]["kind"] == "Duurloop" and day["context"]["distance_km"] == 20
    assert day["source"]["nl"] == "Gebaseerd op gegevens van NEVO-online versie 2099/1.0, RIVM, Bilthoven" and day["foods_ready"]
    assert round(sum(day["energy_split"].values()), 2) == 1.0
    # the usual portion comes back in search, and recent foods offer it again
    assert client.get("/api/nutrition/foods/search", params={"q": "haver"}).json()[0]["portion_g"] == 80
    assert [f["ref"] for f in client.get("/api/nutrition/foods/recent").json()] == ["nevo:9001", "nevo:9003"]
    # edit: less milk, later; then delete
    oats, milk = meal["items"]
    r = client.patch(f"/api/nutrition/meals/{meal['id']}", json={"eaten_at": "08:00", "items": [{"id": oats["id"]}, {"id": milk["id"], "grams": 100}]})
    assert r.status_code == 200 and r.json()["eaten_at"] == "08:00" and r.json()["items"][1]["grams"] == 100
    assert client.get("/api/nutrition/meals", params={"from": "2026-10-01", "to": "2026-10-31"}).json()[0]["id"] == meal["id"]
    assert client.delete(f"/api/nutrition/meals/{meal['id']}").json() == {"ok": True}
    assert client.delete(f"/api/nutrition/meals/{meal['id']}").status_code == 404
    assert client.get("/api/nutrition/day").json()["meals"] == []


def test_errors_are_codes(client, engine):  # noqa: F811
    beta(engine)
    client.post("/api/nutrition/admin/nevo", content=SAMPLE)
    base = {"day": "2026-10-19", "eaten_at": "07:30", "moment": "breakfast"}
    for body, status, code in (
        ({**base, "items": []}, 422, "meal_empty"),
        ({**base, "items": [{"food_ref": "nevo:1", "grams": 10}]}, 404, "food_not_found"),
        ({**base, "items": [{"food_ref": "nevo:9001", "grams": 9000}]}, 422, "invalid_grams"),
        ({**base, "moment": "x", "items": [{"food_ref": "nevo:9001", "grams": 10}]}, 422, "invalid_choice"),
    ):
        r = client.post("/api/nutrition/meals", json=body)
        assert (r.status_code, r.json()["code"]) == (status, code)
    assert client.get("/api/nutrition/day", params={"day": "19-10"}).json()["code"] == "invalid_date"
    assert client.patch("/api/nutrition/meals/99", json={"note": "x"}).json()["code"] == "meal_not_found"


def test_another_user_sees_none_of_it(app, client, engine):  # noqa: F811
    beta(engine)
    client.post("/api/nutrition/admin/nevo", content=SAMPLE)
    meal = client.post("/api/nutrition/meals", json={"day": "2026-10-19", "eaten_at": "07:30", "moment": "breakfast",
                                                     "items": [{"food_ref": "nevo:9002", "grams": 120}]}).json()
    client.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    anna, _ = register(app)
    beta(engine, anna.get("/api/me").json()["id"])
    assert anna.get("/api/nutrition/day").json()["meals"] == []
    assert anna.patch(f"/api/nutrition/meals/{meal['id']}", json={"note": "x"}).status_code == 404
    assert anna.delete(f"/api/nutrition/meals/{meal['id']}").status_code == 404
    assert client.get("/api/nutrition/day").json()["meals"][0]["id"] == meal["id"]


def test_dashboard_block(client, engine):  # noqa: F811
    beta(engine)
    client.post("/api/nutrition/admin/nevo", content=SAMPLE)
    assert client.get("/api/dashboard").json()["nutrition"] is None  # never used: the card stays away
    client.post("/api/nutrition/meals", json={"day": "2026-10-18", "eaten_at": "19:00", "moment": "dinner",
                                              "items": [{"food_ref": "nevo:9002", "grams": 100}]})
    block = client.get("/api/dashboard").json()["nutrition"]
    assert block["empty"] is True and block["targets"]["day_type"] == "rest"  # used before, nothing today: no bars
    client.post("/api/nutrition/meals", json={"day": "2026-10-19", "eaten_at": "07:30", "moment": "breakfast",
                                              "items": [{"food_ref": "nevo:9001", "grams": 80}]})
    block = client.get("/api/dashboard").json()["nutrition"]
    assert block["empty"] is False and block["totals"]["energy_kcal"] == 296 and len(block["meals"]) == 1
    assert block["per_kg"]["carbs"] == 0.6
