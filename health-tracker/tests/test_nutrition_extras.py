"""Phase 4 of Voeding: the Dutch norms for vitamins and minerals (tools/nutrition/references.py), My foods (your usual
portions, your own products), the USDA fallback (usda.py, never called for real) and the accuracy figures for the
admin hub (accuracy.py)."""

from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main
from api.main import TZ, create_app
from tests.test_api import engine, login, make_settings  # noqa: F401  (engine is a fixture)
from tools import db
from tools.nutrition import accuracy, foods, meals, nevo, references, usda

SAMPLE = (Path(__file__).parent / "nevo_sample.csv").read_bytes()
TODAY = date(2026, 10, 19)


@pytest.fixture
def client(engine, monkeypatch):  # noqa: F811
    monkeypatch.setattr(api.main, "today", lambda: TODAY)
    monkeypatch.setattr(api.main, "now", lambda: datetime(2026, 10, 19, 9, 30, tzinfo=TZ))
    foods.invalidate()
    nevo.import_foods(engine, nevo.csv_text(SAMPLE))
    db.set_setting(db.Scope(engine, 1), "profile_facts", {"weight_kg": 70, "birth_year": 1975})
    c = TestClient(create_app(engine=engine, settings=make_settings()))
    assert login(c).status_code == 200  # user 1 exists from here
    db.set_user_beta(engine, 1, "nutrition", True)
    return c


def test_norms_by_sex_and_age():
    assert references.norm("iron_mg", "men", 30) == ("ADH", 11)
    assert references.norm("iron_mg", "women", 30) == ("ADH", 16) and references.norm("iron_mg", "women", 55) == ("ADH", 11)
    assert references.norm("calcium_mg", "women", 55) == ("ADH", 1100) and references.norm("calcium_mg", "men", 20) == ("ADH", 1000)
    assert references.norm("vit_d_ug", "men", 72) == ("ADH", 20) and references.norm("magnesium_mg", "women", 40) == ("AI", 300)
    assert references.norm("iron_mg", None, 30) is None and references.norm("sodium_mg", "men", 30) is None
    assert references.norm("calcium_mg", "men", None) == ("ADH", 1000)  # without an age: the band from 18


def test_the_day_shows_vitamins_and_minerals_against_the_chosen_norms(client):
    client.post("/api/nutrition/meals", json={"day": "2026-10-19", "eaten_at": "08:00", "moment": "breakfast",
                                              "items": [{"food_ref": "nevo:9004", "grams": 200}]})  # 2 mg iron per 100 g
    micros = client.get("/api/nutrition/day").json()["micros"]
    iron = micros["rows"][0]
    assert micros["group"] is None and (iron["key"], iron["amount"], iron["pct"]) == ("iron_mg", 4.0, None)
    assert client.put("/api/nutrition/settings", json={"norms": "women"}).json()["norms"] == "women"
    iron = client.get("/api/nutrition/day").json()["micros"]["rows"][0]
    assert (iron["reference"], iron["pct"]) == (11, 36)  # 51 in 2026: past the menopause band
    assert client.put("/api/nutrition/settings", json={"norms": "none"}).json()["norms"] is None
    assert client.put("/api/nutrition/settings", json={"norms": "x"}).status_code == 422
    client.put("/api/nutrition/settings", json={"norms": "men"})
    assert client.get("/api/nutrition/trends", params={"days": 14}).json()["iron_reference"] == 11


def test_my_portions(client, engine):  # noqa: F811
    client.post("/api/nutrition/meals", json={"day": "2026-10-19", "eaten_at": "08:00", "moment": "breakfast",
                                              "items": [{"food_ref": "nevo:9001", "grams": 60}]})
    assert client.get("/api/nutrition/portions").json() == [
        {"ref": "nevo:9001", "name": "Havermout", "name_en": "Oat flakes", "source": "nevo", "unit": "g", "grams": 60.0, "uses": 1, "last_used": "2026-10-19"}]
    assert client.put("/api/nutrition/portions/nevo:9001", json={"grams": 45}).json() == {"ok": True}
    assert meals.portions(db.Scope(engine, 1))["nevo:9001"]["grams"] == 45
    assert client.put("/api/nutrition/portions/nevo:404", json={"grams": 45}).status_code == 404
    client.delete("/api/nutrition/portions/nevo:9001")
    assert client.get("/api/nutrition/portions").json() == []


def test_my_own_products(client):
    r = client.post("/api/nutrition/user-foods", json={"name": "Muesli van de markt", "brand": "Boer Jan",
                                                       "per_100": {"energy_kcal": 410, "carbs_g": 60, "protein_g": 11, "fat_g": 12, "salt_g": 0.1}})
    assert r.status_code == 201
    food = r.json()
    assert food["ref"].startswith("user:") and food["per_100"]["salt_g"] == 0.1 and food["per_100"]["iron_mg"] is None
    assert client.get("/api/nutrition/foods/search", params={"q": "muesli"}).json()[0]["ref"] == food["ref"]
    fid = food["ref"].split(":")[1]
    assert client.patch(f"/api/nutrition/user-foods/{fid}", json={"per_100": {"energy_kcal": 400}}).json()["per_100"]["energy_kcal"] == 400
    for body, code in (({"name": " ", "per_100": {"energy_kcal": 1}}, "food_name_required"), ({"name": "x", "per_100": {}}, "food_energy_required"),
                       ({"name": "x", "per_100": {"energy_kcal": 1000}}, "food_value_range"), ({"name": "x", "unit": "kg", "per_100": {"energy_kcal": 1}}, "invalid_choice")):
        assert client.post("/api/nutrition/user-foods", json=body).json()["code"] == code
    meal = client.post("/api/nutrition/meals", json={"day": "2026-10-19", "eaten_at": "08:00", "moment": "breakfast",
                                                     "items": [{"food_ref": food["ref"], "grams": 50}]}).json()
    assert client.get("/api/nutrition/user-foods").json()["own"][0]["name"] == "Muesli van de markt"
    client.post("/api/nutrition/templates", json={"name": "Muesli", "items": [{"food_ref": food["ref"], "grams": 50}]})
    client.post("/api/nutrition/templates", json={"name": "Mix", "items": [{"food_ref": food["ref"], "grams": 50}, {"food_ref": "nevo:9002", "grams": 100}]})
    assert client.delete(f"/api/nutrition/user-foods/{fid}").json() == {"ok": True}
    favourites = client.get("/api/nutrition/templates").json()  # the product left them; the one only it was in went too
    assert [(t["name"], [i["food_ref"] for i in t["items"]]) for t in favourites] == [("Mix", ["nevo:9002"])]
    assert client.get("/api/nutrition/portions").json() == []
    day = client.get("/api/nutrition/day").json()
    assert day["meals"][0]["id"] == meal["id"] and day["totals"]["energy_kcal"] == 200  # the snapshot stays
    assert "en andere gegevens" in day["source"]["nl"]


USDA_ITEM = {"fdcId": 168872, "description": "Oat bran, raw", "foodCategory": "Cereal Grains and Pasta", "foodNutrients": [
    {"nutrientId": 1008, "value": 246}, {"nutrientId": 1005, "value": 66.2}, {"nutrientId": 1079, "value": 15.4},
    {"nutrientId": 1003, "value": 17.3}, {"nutrientId": 1004, "value": 7.03}, {"nutrientId": 1093, "value": 4.0}, {"nutrientId": 1089, "value": 5.41}]}


def test_usda_fills_in_what_nevo_lacks(engine, monkeypatch):  # noqa: F811
    s = db.Scope(engine, 1)
    foods.invalidate()
    nevo.import_foods(engine, nevo.csv_text(SAMPLE))
    calls = []
    fetch = lambda q: calls.append(q) or [USDA_ITEM]  # noqa: E731
    monkeypatch.delenv("FDC_API_KEY", raising=False)
    assert usda.fill(s, "oat bran", fetch) == 0 and calls == []  # without a key nothing is asked
    monkeypatch.setenv("FDC_API_KEY", "test")
    assert usda.fill(s, "ob", fetch) == 0  # too short
    assert usda.fill(s, "oat bran", fetch) == 1 and usda.fill(s, "oat bran", fetch) == 0 and calls == ["oat bran"]  # once an hour
    hit = foods.search(s, "oat bran")[0]
    p = hit["per_100"]
    assert (hit["ref"], hit["source"]) == ("usda:168872", "usda")
    assert p["carbs_g"] == 50.8 and p["fiber_g"] == 15.4 and p["salt_g"] == 0.01 and p["iron_mg"] == 5.41  # carbs without the fibre
    assert usda.to_food({"fdcId": 1, "description": "x", "foodNutrients": []}) is None


def test_accuracy_for_the_hub(engine):  # noqa: F811
    s = db.Scope(engine, 1)
    foods.invalidate()
    nevo.import_foods(engine, nevo.csv_text(SAMPLE))
    for grams, ai, source in ((60, 50, "user"), (100, 100, "user"), (120, 100, "user"), (80, 80, "ai"), (90, 100, "memory"), (70, 50, "user"), (100, 80, "user")):
        meals.create(s, day="2026-10-19", eaten_at="08:00", moment="breakfast", input="photo",
                     items=[{"food_ref": "nevo:9001", "grams": grams, "grams_ai": ai, "grams_source": source}])
    with engine.begin() as c:
        c.execute(db.nutrition_ai_runs.insert().values(user_id=1, model="m", prompt_version="1", tokens_in=1000, tokens_out=200,
                                                       created_at=datetime(2026, 10, 5, tzinfo=TZ)))
    st = accuracy.stats(engine, TODAY)
    assert (st["runs_month"], st["tokens_in_month"], st["corrected"], st["kept"], st["memory"]) == (1, 1000, 5, 1, 1)
    assert st["by_group"] == [{"group": "Cereal products", "items": 5, "median_error": 0.167}]  # |60-50|/60, 0, 20/120, 20/70, 20/100
    facts = accuracy.facts(engine, TODAY)
    assert facts[0]["note"]["nl"] == "1.000 tokens in, 200 uit"
    assert facts[0]["value"] == "1" and facts[-1]["label"]["en"] == "Gram error: Cereal products" and facts[-1]["value"] == "17%"


def test_the_hub_shows_the_facts(client):
    out = client.get("/api/admin/tracker").json()
    assert out["facts"][0]["label"] == {"en": "Photo analyses this month", "nl": "Foto-analyses deze maand"}


def test_scanned_products_are_listed_also_when_not_logged(client, monkeypatch):
    from tools.nutrition import off

    monkeypatch.setattr(off, "fetch", lambda ean: {"product_name": "Skyr", "nutriments": {"energy-kcal_100g": 63}})
    client.get("/api/nutrition/foods/barcode/4006381333931")
    assert [f["ref"] for f in client.get("/api/nutrition/user-foods").json()["scanned"]] == ["off:4006381333931"]


def test_usda_never_holds_up_a_search(engine, monkeypatch):  # noqa: F811
    started = []
    monkeypatch.setenv("FDC_API_KEY", "test")
    monkeypatch.setattr(usda.threading, "Thread", lambda target, args, **kw: type("T", (), {"start": lambda self: started.append(args[1])})())
    s = db.Scope(engine, 1)
    assert usda.fill_later(s, "zzqx onbekend") and started == ["zzqx onbekend"]
    assert not usda.fill_later(s, "zzq")  # shorter than a word
