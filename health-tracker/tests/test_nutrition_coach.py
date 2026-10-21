"""Nutrition for a coaching agent (api/mcp.py get_nutrition, log_meal, search_foods, get_context, get_day) and the
Trends tab and the evening before a night (api/nutrition.py trends, api/daily.py evening)."""

from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main
import api.mcp
from api.main import TZ, create_app
from api.nutrition_agent import parse
from tests.test_api import engine, login, make_settings  # noqa: F401  (engine is a fixture)
from tests.test_mcp import TOKEN, call, rpc
from tools import db
from tools.nutrition import foods, meals, nevo, report

SAMPLE = (Path(__file__).parent / "nevo_sample.csv").read_bytes()
TODAY = date(2026, 10, 19)


@pytest.fixture
def app(engine, monkeypatch):  # noqa: F811
    import hashlib

    monkeypatch.setattr(api.main, "today", lambda: TODAY)
    monkeypatch.setattr(api.main, "now", lambda: datetime(2026, 10, 19, 9, 30, tzinfo=TZ))
    foods.invalidate()
    nevo.import_foods(engine, nevo.csv_text(SAMPLE))
    s = db.Scope(engine, 1)
    db.set_setting(s, "profile_facts", {"weight_kg": 78})
    return create_app(engine=engine, settings=make_settings(agent_token_hash=hashlib.sha256(TOKEN.encode()).hexdigest()))


@pytest.fixture
def client(app):
    return TestClient(app)


def on(engine):  # noqa: F811
    db.set_user_beta(engine, 1, "nutrition", True)


def test_the_tools_come_with_the_beta(client, engine):  # noqa: F811
    names = lambda: {t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]}  # noqa: E731
    assert not {"get_nutrition", "log_meal", "search_foods"} & names()
    text, err = call(client, "get_nutrition")
    assert err and "Voeding staat niet aan" in text
    on(engine)
    assert {"get_nutrition", "log_meal", "search_foods"} <= names()
    init = rpc(
        client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}
    ).json()
    assert "Voeding: waarden zijn schattingen" in init["result"]["instructions"]


def test_search_and_log_a_meal(client, engine):  # noqa: F811
    on(engine)
    text, _ = call(client, "search_foods", q="haver")
    assert "| nevo:9001 | Havermout | nevo | 370 |" in text
    table = "| Voedingsmiddel | Gram | Moment | Tijd |\n|---|---|---|---|\n| havermout | 60 | ontbijt | 7:30 |\n| nevo:9002 | 120g | ontbijt | 07:30 |\n| xyzzy | 10 | ontbijt | 07:30 |"
    text, err = call(client, "log_meal", table=table, preview=True)
    assert not err and "Voorbeeld" in text and "Havermout (nevo:9001) 60 g" in text and "'xyzzy' niet gevonden" in text
    assert meals.between(db.Scope(engine, 1), "2026-10-19", "2026-10-19") == []
    text, err = call(client, "log_meal", table=table)
    logged = meals.between(db.Scope(engine, 1), "2026-10-19", "2026-10-19")
    assert not err and "1 maaltijd opgeslagen" in text and len(logged) == 1
    m = logged[0]
    assert (m["eaten_at"], m["moment"], m["input"], len(m["items"])) == ("07:30", "breakfast", "agent", 2)
    text, _ = call(client, "get_nutrition")
    assert (
        "# Voeding 2026-10-19 (rustdag)" in text
        and "Havermout: 60 g" in text
        and "| Koolhydraten | 59 g (0,8 g/kg) | 3,0-5,0 g/kg |" in text
    )
    assert "Waarschijnlijk niet alles gelogd (1 maaltijd)" in text


def test_a_range_and_the_context(client, engine):  # noqa: F811
    on(engine)
    s = db.Scope(engine, 1)
    for day, n in (("2026-10-17", 2), ("2026-10-18", 1)):
        for i in range(n):
            meals.create(
                s,
                day=day,
                eaten_at=f"{8 + 5 * i:02d}:00",
                moment="breakfast" if i == 0 else "lunch",
                input="search",
                items=[{"food_ref": "nevo:9001", "grams": 100}],
            )
    text, _ = call(client, "get_nutrition", **{"from": "2026-10-17", "to": "2026-10-19"})
    assert "| 2026-10-17 | rustdag | 740 |" in text and "| 2026-10-19 | rustdag | - |" in text
    assert "Dekking: 1 van 3 dagen met minstens 2 maaltijden (2 met iets gelogd)" in text
    assert call(client, "get_nutrition", **{"from": "2026-10-19", "to": "2026-10-01"})[1]  # backwards: an error
    text, _ = call(client, "get_context")
    assert "## Voeding, laatste 7 dagen: 2026-10-13 t/m 2026-10-19" in text


def test_the_evening_before_a_night(client, app, engine):  # noqa: F811
    on(engine)
    s = db.Scope(engine, 1)
    meals.create(s, day="2026-10-18", eaten_at="18:30", moment="dinner", input="search", items=[{"food_ref": "nevo:9004", "grams": 100}])
    meals.create(
        s,
        day="2026-10-18",
        eaten_at="21:30",
        moment="drinks",
        input="search",
        items=[{"food_ref": "nevo:9005", "grams": 1000}, {"food_ref": "nevo:9001", "grams": 200}],
    )
    e = report.evening(s, "2026-10-18")
    assert e == {"day": "2026-10-18", "last_meal": "21:30", "alcohol_units": 3.9, "kcal": 1160, "late_large": True, "minute": 1290}
    assert report.evening(s, "2026-10-17") is None
    assert (
        report.evening_line(e)
        == "Avond ervoor (voeding): laatste maaltijd 21:30, 1160 kcal na 19:00, alcohol 3,9 eenheden, late grote maaltijd (na 20:30, 600+ kcal)."
    )
    text, _ = call(client, "get_day", day="2026-10-19")
    assert "Avond ervoor (voeding): laatste maaltijd 21:30" in text
    site = TestClient(app)
    assert login(site).status_code == 200
    view = site.get("/api/wellness/day", params={"day": "2026-10-19"}).json()
    assert view["evening"]["last_meal"] == "21:30" and view["from"] <= -150  # the timeline reaches back to before 21:30
    db.set_user_beta(engine, 1, "nutrition", False)
    assert "evening" not in site.get("/api/wellness/day", params={"day": "2026-10-19"}).json()


def test_trends(app, engine):  # noqa: F811
    on(engine)
    site = TestClient(app)
    assert login(site).status_code == 200
    s = db.Scope(engine, 1)
    meals.create(s, day="2026-10-19", eaten_at="08:00", moment="breakfast", input="search", items=[{"food_ref": "nevo:9001", "grams": 100}])
    meals.create(s, day="2026-10-19", eaten_at="12:00", moment="lunch", input="search", items=[{"food_ref": "nevo:9005", "grams": 500}])
    out = site.get("/api/nutrition/trends", params={"days": 14}).json()
    assert len(out["days"]) == 14 and out["days"][-1]["day"] == "2026-10-19" and out["covered"] == 1
    last = out["days"][-1]
    assert last["kcal"] == 580 and last["carbs_per_kg"] == 0.9 and last["carbs_target"] == [3.0, 5.0] and last["alcohol_g"] == 19.5
    assert last["sat_fat_share"] == round(1.2 * 9 / 580, 3) and out["days"][0]["kcal"] is None
    assert site.get("/api/nutrition/trends", params={"days": 7}).json()["code"] == "invalid_choice"


def test_the_table_parser():
    rows, warnings = parse("food,grams,time\nbanaan,120,13:05\nmelk,abc,13:05\n", TODAY, "09:00")
    assert rows[0]["moment"] == "lunch" and rows[0]["eaten_at"] == "13:05"  # the moment from the row's own time
    assert warnings == ["regel 3: geen hoeveelheid in gram"]
    assert parse("x\ny", TODAY, "09:00")[1] == ["kolommen Voedingsmiddel en Gram zijn verplicht"]
    assert parse("| Voedingsmiddel | Gram | Moment |\n|---|---|---|\n| banaan | 1 | brunch |", TODAY, "09:00")[1] == [
        "regel 2: onbekend moment 'brunch'"
    ]  # counted as the table reads, header first


def test_log_meal_is_all_or_nothing_and_teaches_no_portion(client, engine):  # noqa: F811
    on(engine)
    s = db.Scope(engine, 1)
    table = "| Voedingsmiddel | Gram | Tijd | Dag |\n|---|---|---|---|\n| havermout | 60 | 07:30 | 2026-10-19 |\n| banaan | 9000 | 12:30 | 2026-10-19 |"
    text, err = call(client, "log_meal", table=table)
    assert err and "Niets opgeslagen" in text and "invalid_grams" in text
    assert meals.between(s, "2026-10-19", "2026-10-19") == []
    call(client, "log_meal", table=table.replace("9000", "120"))
    assert [i["grams_source"] for m in meals.between(s, "2026-10-19", "2026-10-19") for i in m["items"]] == ["agent", "agent"]
    assert meals.portions(s) == {}  # an assistant's amounts are not your usual portion
