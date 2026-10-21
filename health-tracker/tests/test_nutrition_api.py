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
    r = client.post(
        "/api/plans", json={"title": "Najaar", "sessions": [{"date": "2026-10-20", "sport": "run", "kind": "Duurloop", "distance_km": 20}]}
    )
    assert r.status_code in (200, 201), r.text
    hits = client.get("/api/nutrition/foods/search", params={"q": "haver"}).json()
    assert hits[0]["ref"] == "nevo:9001" and hits[0]["portion_g"] is None
    r = client.post(
        "/api/nutrition/meals",
        json={
            "day": "2026-10-19",
            "eaten_at": "07:30",
            "moment": "breakfast",
            "input": "search",
            "items": [{"food_ref": "nevo:9001", "grams": 80}, {"food_ref": "nevo:9003", "grams": 250}],
        },
    )
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
    r = client.patch(
        f"/api/nutrition/meals/{meal['id']}", json={"eaten_at": "08:00", "items": [{"id": oats["id"]}, {"id": milk["id"], "grams": 100}]}
    )
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
    meal = client.post(
        "/api/nutrition/meals",
        json={"day": "2026-10-19", "eaten_at": "07:30", "moment": "breakfast", "items": [{"food_ref": "nevo:9002", "grams": 120}]},
    ).json()
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
    client.post(
        "/api/nutrition/meals",
        json={"day": "2026-10-18", "eaten_at": "19:00", "moment": "dinner", "items": [{"food_ref": "nevo:9002", "grams": 100}]},
    )
    block = client.get("/api/dashboard").json()["nutrition"]
    assert block["empty"] is True and block["targets"]["day_type"] == "rest"  # used before, nothing today: no bars
    client.post(
        "/api/nutrition/meals",
        json={"day": "2026-10-19", "eaten_at": "07:30", "moment": "breakfast", "items": [{"food_ref": "nevo:9001", "grams": 80}]},
    )
    block = client.get("/api/dashboard").json()["nutrition"]
    assert block["empty"] is False and block["totals"]["energy_kcal"] == 296 and len(block["meals"]) == 1
    assert block["per_kg"]["carbs"] == 0.6


# --- phase 2: photos, barcode, favourites, settings -------------------------------------------------------------

from tests.test_nutrition_match import RECORDED, Stub, jpeg  # noqa: E402
from tools.nutrition import off, recognize  # noqa: E402


@pytest.fixture
def ai(monkeypatch):
    """A server with a key and Claude answering RECORDED."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    real = recognize.trackerai_ai.ask
    monkeypatch.setattr(recognize.trackerai_ai, "ask", lambda body, **kw: real(body, **{**kw, "client": Stub(RECORDED)}))


def test_photo_analysis_is_opt_in(client, engine, monkeypatch):  # noqa: F811
    beta(engine)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert client.get("/api/nutrition/settings").json()["ai_available"] is False
    assert client.put("/api/nutrition/settings", json={"ai": True}).json()["code"] == "nutrition_ai_unavailable"
    assert client.post("/api/nutrition/photo", content=jpeg()).json()["code"] == "nutrition_ai_unavailable"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    r = client.post("/api/nutrition/photo", content=jpeg())
    assert r.status_code == 403 and r.json()["code"] == "nutrition_ai_off"  # the server can, the user did not switch it on
    out = client.put("/api/nutrition/settings", json={"ai": True, "photos": "keep", "kcal_target": 2600}).json()
    assert (out["ai"], out["photos"], out["kcal_target"], out["ai_available"]) == (True, "keep", 2600, True)
    assert out["day_types"]["race"]["carbs_per_kg"] == [8.0, 12.0]
    assert client.put("/api/nutrition/settings", json={"clear_kcal_target": True}).json()["kcal_target"] is None
    assert client.put("/api/nutrition/settings", json={"photos": "always"}).status_code == 422


def test_from_photo_to_saved_meal(app, client, engine, ai):  # noqa: F811
    beta(engine)
    client.post("/api/nutrition/admin/nevo", content=SAMPLE)
    client.put("/api/nutrition/settings", json={"ai": True})
    assert client.post("/api/nutrition/photo", content=b"GIF89a").json()["code"] == "photo_invalid"
    d = client.post("/api/nutrition/photo", content=jpeg()).json()
    assert d["failed"] is None and d["photo_id"] and d["ai_run_id"] and d["moment_guess"] == "breakfast"
    assert [i["food"]["ref"] for i in d["items"]] == ["nevo:9001", "nevo:9002", "nevo:9003"]
    stored = client.get(f"/api/nutrition/photos/{d['photo_id']}")
    assert stored.headers["content-type"] == "image/jpeg" and b"Exif" not in stored.content and b"GPS" not in stored.content
    items = [
        {
            "food_ref": i["food"]["ref"],
            "grams": i["grams"],
            "grams_source": i["grams_source"],
            "grams_ai": i["grams_ai"],
            "grams_low": i["grams_low"],
            "grams_high": i["grams_high"],
            "confidence": i["confidence"],
        }
        for i in d["items"]
    ]
    items[0].update(grams=50, grams_source="user")  # corrected the oats
    meal = client.post(
        "/api/nutrition/meals",
        json={
            "day": "2026-10-19",
            "eaten_at": "07:45",
            "moment": "breakfast",
            "input": "photo",
            "photo_id": d["photo_id"],
            "ai_run_id": d["ai_run_id"],
            "items": items,
        },
    ).json()
    assert meal["photo_id"] == d["photo_id"] and [i["grams_source"] for i in meal["items"]] == ["user", "ai", "ai"]
    assert meal["items"][0]["grams_ai"] == 65
    # someone else sees nothing of it, and cannot attach the photo to their own meal
    client.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    anna, _ = register(app)
    beta(engine, anna.get("/api/me").json()["id"])
    assert anna.get(f"/api/nutrition/photos/{d['photo_id']}").status_code == 404
    r = anna.post(
        "/api/nutrition/meals",
        json={
            "day": "2026-10-19",
            "eaten_at": "08:00",
            "moment": "breakfast",
            "photo_id": d["photo_id"],
            "items": [{"food_ref": "nevo:9001", "grams": 50}],
        },
    )
    assert r.status_code == 404 and r.json()["code"] == "photo_not_found"
    # a run is only yours to refer to
    r = anna.post(
        "/api/nutrition/meals",
        json={
            "day": "2026-10-19",
            "eaten_at": "08:00",
            "moment": "breakfast",
            "ai_run_id": d["ai_run_id"],
            "items": [{"food_ref": "nevo:9001", "grams": 50}],
        },
    )
    assert r.status_code == 201 and r.json()["ai_run_id"] is None
    # deleting the meal deletes the photo
    client.delete(f"/api/nutrition/meals/{meal['id']}")
    assert client.get(f"/api/nutrition/photos/{d['photo_id']}").status_code == 404


def test_photo_analysis_has_a_daily_limit(client, engine, ai, monkeypatch):  # noqa: F811
    beta(engine)
    client.post("/api/nutrition/admin/nevo", content=SAMPLE)
    client.put("/api/nutrition/settings", json={"ai": True})
    monkeypatch.setenv("NUTRITION_DAILY_PHOTOS", "2")
    assert [client.post("/api/nutrition/photo", content=jpeg()).status_code for _ in range(3)] == [200, 200, 429]
    assert client.post("/api/nutrition/photo", content=jpeg()).json()["code"] == "nutrition_ai_limit"


def test_a_failed_analysis_keeps_the_photo(client, engine, monkeypatch):  # noqa: F811
    beta(engine)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client.put("/api/nutrition/settings", json={"ai": True})

    def down(body, **kw):
        raise recognize.trackerai_ai.AiError("unreachable", "timeout")

    monkeypatch.setattr(recognize.trackerai_ai, "ask", down)
    d = client.post("/api/nutrition/photo", content=jpeg()).json()
    assert d["failed"] == "unreachable" and d["items"] == [] and client.get(f"/api/nutrition/photos/{d['photo_id']}").status_code == 200


def test_barcode(client, engine, monkeypatch):  # noqa: F811
    beta(engine)
    monkeypatch.setattr(
        off,
        "fetch",
        lambda ean: (
            {"product_name": "Skyr", "nutriments": {"energy-kcal_100g": 63, "proteins_100g": 11}} if ean == "4006381333931" else None
        ),
    )
    assert client.get("/api/nutrition/foods/barcode/123").json()["code"] == "invalid_barcode"
    assert client.get("/api/nutrition/foods/barcode/4006381333931").json()["per_100"]["protein_g"] == 11
    assert client.get("/api/nutrition/foods/barcode/5000112637922").status_code == 404
    monkeypatch.setattr(off, "fetch", lambda ean: {"product_name": "Water", "nutriments": {}})
    assert client.get("/api/nutrition/foods/barcode/5000112637922").json()["code"] == "barcode_no_nutrients"

    def broken(ean):
        raise off.LookupFailed("timeout")

    monkeypatch.setattr(off, "fetch", broken)
    assert client.get("/api/nutrition/foods/barcode/5000112637922").json()["code"] == "barcode_lookup_failed"


def test_favourites_api(client, engine):  # noqa: F811
    beta(engine)
    client.post("/api/nutrition/admin/nevo", content=SAMPLE)
    t = client.post(
        "/api/nutrition/templates", json={"name": "Pap", "moment": "breakfast", "items": [{"food_ref": "nevo:9001", "grams": 60}]}
    )
    assert t.status_code == 201
    tid = t.json()["id"]
    assert client.patch(f"/api/nutrition/templates/{tid}", json={"name": "Havermoutpap"}).json()["name"] == "Havermoutpap"
    assert client.get("/api/nutrition/again", params={"moment": "breakfast"}).json()["favourites"][0]["id"] == tid
    assert client.delete(f"/api/nutrition/templates/{tid}").json() == {"ok": True}
    assert client.patch(f"/api/nutrition/templates/{tid}", json={"name": "x"}).json()["code"] == "template_not_found"
