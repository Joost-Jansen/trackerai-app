"""Nutrition in the database (tools/db.py v8, tools/nutrition/): the NEVO import, food search, meals with their nutrient
snapshot, the usual portion, and that no user reaches another's meals.

tests/nevo_sample.csv is in NEVO-online's file format (`|`, quoted values, decimal comma, CRLF) with invented foods and
values: RIVM's table itself is not part of this repository.
"""

import io
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import inspect, update

from tools import db
from tools.nutrition import foods, meals, nevo
from tools.nutrition.nutrients import energy_split, scale, total
from trackerai_testing import new_database_url

SAMPLE = (Path(__file__).parent / "nevo_sample.csv").read_bytes()


@pytest.fixture
def engine(tmp_path):
    e = db.connect(new_database_url())
    db.create_schema(e)
    foods.invalidate()
    nevo.import_foods(e, nevo.csv_text(SAMPLE))
    return e


def test_schema_v8_adds_the_nutrition_tables_to_a_v7_database(tmp_path):
    e = db.connect(new_database_url())
    db.create_schema(e)
    with e.begin() as c:
        for t in ("meal_items", "meals", "foods", "user_foods", "meal_photos", "portion_memory", "meal_templates", "nutrition_ai_runs"):
            db.meta.tables[t].drop(c)
        c.execute(update(db.app_settings).where(db.app_settings.c.key == "schema_version").values(value=7))
    db.create_schema(e)
    assert {"foods", "meals", "meal_items", "portion_memory"} <= set(inspect(e).get_table_names())
    assert db.get_app_setting(e, "schema_version") == db.SCHEMA_VERSION == 8


def test_the_import_reads_nevos_format_and_is_idempotent(engine):
    rel, rows = nevo.parse(nevo.csv_text(SAMPLE))
    assert nevo.version_label(rel) == "2099/1.0" and len(rows) == 9
    banana = next(r for r in rows if r["source_code"] == "9002")
    assert banana["per_100"]["energy_kcal"] == 95 and banana["per_100"]["protein_g"] == 1.2  # decimal comma
    assert banana["per_100"]["omega3_g"] is None  # empty = not measured, not 0
    assert banana["per_100"]["salt_g"] == 0.003  # 1 mg sodium x 2.5
    assert next(r for r in rows if r["source_code"] == "9003")["unit"] == "ml"
    dried = next(r for r in rows if r["source_code"] == "9006")
    assert dried["per_100"]["sodium_mg"] is None and dried["per_100"]["salt_g"] is None
    assert nevo.import_foods(engine, nevo.csv_text(SAMPLE)) == {"release": "NEVO-online 2099/1.0", "foods": 9, "added": 0, "updated": 0}
    changed = SAMPLE.replace(b'"95"', b'"96"')
    assert nevo.import_foods(engine, nevo.csv_text(changed))["updated"] == 1
    assert nevo.current_version(engine) == "NEVO-online 2099/1.0"


def test_the_import_takes_rivms_zip_and_refuses_other_files():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("NEVO2099_v1.0.csv", SAMPLE)
        z.writestr("NEVO2099_v1.0_Details.csv", b"other")
    assert nevo.csv_text(buf.getvalue()).startswith('"NEVO-versie')
    with pytest.raises(nevo.NevoFormatError):
        nevo.parse("a|b\n1|2\n")
    with pytest.raises(nevo.NevoFormatError):
        nevo.csv_text(zipfile_with("readme.txt"))


def zipfile_with(name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, b"x")
    return buf.getvalue()


def test_attribution_is_rivms_reference():
    assert nevo.attribution("NEVO-online 2025/9.0") == "Gebaseerd op gegevens van NEVO-online versie 2025/9.0, RIVM, Bilthoven"
    assert nevo.attribution("NEVO-online 2025/9.0", "nl", others=True).endswith("Bilthoven en andere gegevens")
    assert nevo.attribution(None) is None


def test_search_matches_word_prefixes_synonyms_and_ranks_what_you_eat(engine):
    s = db.Scope(engine, 1)
    assert [f["name"] for f in foods.search(s, "banaan")] == ["Banaan", "Banaan gedroogd met suiker"]
    assert [f["name"] for f in foods.search(s, "volkorenbr")] == ["Brood volkoren"]  # the synonym
    assert [f["name"] for f in foods.search(s, "brood volk")] == ["Brood volkoren"]
    assert foods.search(s, "melk")[0]["unit"] == "ml"
    assert foods.search(s, "olijfolie")[0]["name"] == "Olie olijf-"  # NEVO's way of writing a compound
    assert foods.search(s, "brood")[0]["name"] == "Brood volkoren"
    assert [f["name"] for f in foods.search(s, "volkorenbr")] == ["Brood volkoren"]
    assert foods.search(s, "ei")[0]["name"] == "Ei kippen- gekookt"  # not the quiche whose name ends in "kaas/ei"
    assert foods.search(s, "  ") == [] and foods.search(s, "xyz") == []
    assert foods.search(s, "ban")[0]["ref"] == "nevo:9002"  # the shorter name first
    ranked = foods.search(s, "ban", history={"nevo:9006": 5})  # what you eat comes first at an equal match
    assert ranked[0]["ref"] == "nevo:9006" and ranked[0]["uses"] == 5
    assert foods.search(s, "banaan", history={"nevo:9006": 5})[0]["ref"] == "nevo:9002"  # an exact name still wins


def _breakfast(s, grams=60, source="user"):
    return meals.create(s, day="2026-10-19", eaten_at="07:30", moment="breakfast", input="search",
                        items=[{"food_ref": "nevo:9001", "grams": grams, "grams_source": source}, {"food_ref": "nevo:9002", "grams": 120}])


def test_a_meal_keeps_a_snapshot_of_its_nutrients(engine):
    s = db.Scope(engine, 1)
    m = _breakfast(s)
    oats, banana = m["items"]
    assert oats["nutrients"]["energy_kcal"] == 222 and banana["nutrients"]["carbs_g"] == 24
    assert m["totals"]["energy_kcal"] == 336 and m["totals"]["missing"] == {"omega3_g": 1, "trans_fat_g": 1}
    nevo.import_foods(engine, nevo.csv_text(SAMPLE.replace(b'"370"', b'"999"')))  # a new release
    assert meals.get(s, m["id"])["items"][0]["nutrients"]["energy_kcal"] == 222
    changed = meals.change(s, m["id"], items=[{"id": oats["id"], "grams": 30}, {"id": banana["id"]}])
    assert changed["items"][0]["nutrients"]["energy_kcal"] == 299.7  # scaled from the food as it is now
    assert changed["items"][1]["grams"] == 120


def test_the_usual_portion_learns_from_what_you_set_not_from_estimates(engine):
    s = db.Scope(engine, 1)
    _breakfast(s, 60)
    _breakfast(s, 100)
    assert meals.portions(s)["nevo:9001"] == {"grams": 72.0, "uses": 2, "last_used": "2026-10-19"}  # 0.7 x 60 + 0.3 x 100
    _breakfast(s, 500, source="ai")
    assert meals.portions(s)["nevo:9001"]["grams"] == 72.0
    assert meals.history(s)["nevo:9001"] == 3
    # an edit teaches only what it changed: saving untouched items again, or moving the time, leaves the portion be
    m = _breakfast(s, 100)
    before = meals.portions(s)["nevo:9001"]
    # each save gives the items new ids, so every edit goes on from the meal the last one returned, as the site does
    m = meals.change(s, m["id"], eaten_at="09:00", items=[{"id": i["id"]} for i in m["items"]])
    m = meals.change(s, m["id"], items=[{"id": i["id"], "grams": i["grams"]} for i in m["items"]])
    assert meals.portions(s)["nevo:9001"] == before
    meals.change(s, m["id"], items=[{"id": m["items"][0]["id"], "grams": 40}, {"id": m["items"][1]["id"]}])
    assert meals.portions(s)["nevo:9001"]["uses"] == before["uses"] + 1


def test_meal_checks(engine):
    s = db.Scope(engine, 1)
    for kwargs, code in (
        ({"items": []}, "meal_empty"),
        ({"items": [{"food_ref": "nevo:9001", "grams": 0}]}, "invalid_grams"),
        ({"items": [{"food_ref": "nevo:404", "grams": 10}]}, "food_not_found"),
        ({"items": [{"food_ref": "nevo:9001", "grams": 10}], "moment": "brunch"}, "invalid_choice"),
        ({"items": [{"food_ref": "nevo:9001", "grams": 10}], "eaten_at": "25:00"}, "invalid_time"),
    ):
        args = {"day": "2026-10-19", "eaten_at": "08:00", "moment": "breakfast", "input": "search", **kwargs}
        with pytest.raises(meals.MealError) as e:
            meals.create(s, **args)
        assert e.value.code == code


def test_no_user_reaches_anothers_meals(engine):
    alice, bob = db.Scope(engine, 1), db.Scope(engine, 2)
    m = _breakfast(alice)
    assert meals.get(bob, m["id"]) is None and meals.between(bob, "2026-01-01", "2026-12-31") == []
    assert meals.change(bob, m["id"], note="mine") is None
    assert meals.remove(bob, m["id"]) is False and meals.get(alice, m["id"])
    assert meals.portions(bob) == {} and meals.history(bob) == {}
    with engine.begin() as c:
        uid = c.execute(db.user_foods.insert().values(user_id=1, name_nl="Eigen muesli", unit="g", per_100={"energy_kcal": 400},
                                                       created_at=meals._now())).inserted_primary_key[0]
    assert foods.get(alice, f"user:{uid}")["name"] == "Eigen muesli" and foods.get(bob, f"user:{uid}") is None
    assert [f["name"] for f in foods.search(alice, "muesli")] == ["Eigen muesli"] and foods.search(bob, "muesli") == []


def test_deleting_a_meal_or_the_user_removes_everything(engine):
    s = db.Scope(engine, 1)
    db.create_user(engine, "alice", "!", is_admin=True, user_id=1)
    m = _breakfast(s)
    assert meals.remove(s, m["id"]) and meals.get(s, m["id"]) is None
    _breakfast(s)
    db.delete_user(engine, 1)
    with engine.connect() as c:
        for t in (db.meals, db.meal_items, db.portion_memory):
            assert c.execute(t.select()).first() is None
        assert c.execute(db.foods.select()).first() is not None  # global


def test_export_holds_the_meals(engine):
    s = db.Scope(engine, 1)
    db.create_user(engine, "alice", "!", is_admin=True, user_id=1)
    _breakfast(s)
    tables = {name: list(rows) for name, rows in db.export_tables(s)}
    assert len(tables["meals"]) == 1 and len(tables["meal_items"]) == 2 and tables["portion_memory"][0]["food_ref"] == "nevo:9001"


def test_nutrient_maths():
    assert scale({"energy_kcal": 200, "omega3_g": None}, 50)["energy_kcal"] == 100
    t = total([{"carbs_g": 10, "protein_g": None}, {"carbs_g": 5.55, "protein_g": 2}])
    assert t["carbs_g"] == 15.6 and t["protein_g"] == 2 and t["missing"]["protein_g"] == 1
    split = energy_split({"carbs_g": 100, "protein_g": 50, "fat_g": 20, "alcohol_g": 0, "fiber_g": 0})
    assert split == {"carbs_g": 0.513, "protein_g": 0.256, "fat_g": 0.231, "alcohol_g": 0.0, "fiber_g": 0.0}
