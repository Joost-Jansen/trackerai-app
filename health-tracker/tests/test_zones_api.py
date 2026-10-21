from datetime import date

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from api.zones_api import make_router, period_bounds, period_label, zone_history, zones_for_period
from tests.helpers import FakeStore, fake_user_dep
from trackerai_testing import new_database_url

ZONES = {"run": {"bounds": [132, 147, 162, 176], "max_hr": 189}, "ride": {"bounds": [127, 141, 156, 169], "max_hr": 182}}


def act(start_local, sport="run", **zones):
    secs = {z: 0 for z in ("Z1", "Z2", "Z3", "Z4", "Z5")}
    secs.update(zones)
    return {"id": start_local, "start_local": start_local, "sport": sport, "hr_zones_s": secs}


ACTS = [
    act("2026-09-27T23:30:00", Z1=100),  # Sunday, week 39
    act("2026-09-28T00:10:00", Z2=600),  # Monday, week 40
    act("2026-10-01T18:00:00", "ride", Z2=300, Z3=100),
    act("2026-10-03T08:00:00", Z4=200),
    {"id": "nohr", "start_local": "2026-10-02T08:00:00", "sport": "strength_training"},
    act("2025-12-30T08:00:00", Z1=50),
]


# ── period boundaries ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "today,offset,start,end",
    [
        (date(2026, 10, 3), 0, date(2026, 9, 28), date(2026, 10, 4)),  # Saturday
        (date(2026, 10, 4), 0, date(2026, 9, 28), date(2026, 10, 4)),  # Sunday still the same week
        (date(2026, 10, 5), 0, date(2026, 10, 5), date(2026, 10, 11)),  # Monday starts a new week
        (date(2026, 10, 5), 1, date(2026, 9, 28), date(2026, 10, 4)),
        (date(2026, 1, 1), 0, date(2025, 12, 29), date(2026, 1, 4)),  # ISO week 1 starts in December
        (date(2026, 1, 5), 1, date(2025, 12, 29), date(2026, 1, 4)),
    ],
)
def test_week_bounds(today, offset, start, end):
    assert period_bounds("week", today, offset) == (start, end)


@pytest.mark.parametrize(
    "today,offset,start,end",
    [
        (date(2026, 10, 3), 0, date(2026, 10, 1), date(2026, 10, 31)),
        (date(2026, 10, 1), 1, date(2026, 9, 1), date(2026, 9, 30)),
        (date(2026, 3, 31), 1, date(2026, 2, 1), date(2026, 2, 28)),
        (date(2026, 1, 15), 1, date(2025, 12, 1), date(2025, 12, 31)),
        (date(2026, 10, 3), 21, date(2025, 1, 1), date(2025, 1, 31)),
        (date(2024, 3, 1), 1, date(2024, 2, 1), date(2024, 2, 29)),
    ],
)
def test_month_bounds(today, offset, start, end):
    assert period_bounds("month", today, offset) == (start, end)


def test_labels_are_dutch():
    assert period_label("week", date(2026, 9, 28), date(2026, 10, 4)) == "week 40 · 28 sep – 4 okt 2026"
    assert period_label("week", date(2026, 10, 5), date(2026, 10, 11)) == "week 41 · 5 – 11 okt 2026"
    assert period_label("week", date(2025, 12, 29), date(2026, 1, 4)) == "week 1 · 29 dec 2025 – 4 jan 2026"
    assert period_label("month", date(2026, 9, 1), date(2026, 9, 30)) == "september 2026"
    assert period_label("month", date(2026, 3, 1), date(2026, 3, 31)) == "maart 2026"


# ── one period ───────────────────────────────────────────────────────────────


def test_current_week_so_far_with_all_and_per_sport():
    out = zones_for_period(ACTS, ZONES, "week", 0, date(2026, 10, 3))
    assert out["start"] == "2026-09-28" and out["end"] == "2026-10-04" and out["is_current"] is True
    assert out["label"] == "week 40 · 28 sep – 4 okt 2026" and out["offset"] == 0 and out["period"] == "week"
    z = out["zones"]
    assert set(z) == {"all", "run", "ride"}  # sport without HR has no zone entry
    assert z["run"]["seconds"] == {"Z1": 0, "Z2": 600, "Z3": 0, "Z4": 200, "Z5": 0}
    assert z["all"]["seconds"] == {"Z1": 0, "Z2": 900, "Z3": 100, "Z4": 200, "Z5": 0}
    assert z["all"]["total_s"] == 1200 and z["all"]["pct"]["Z2"] == 75.0
    assert out["bounds"] == {"run": [132, 147, 162, 176], "ride": [127, 141, 156, 169]}


def test_previous_week_gets_sunday_late_activity_only():
    out = zones_for_period(ACTS, ZONES, "week", 1, date(2026, 10, 3))
    assert out["start"] == "2026-09-21" and out["is_current"] is False
    assert out["zones"]["all"]["seconds"]["Z1"] == 100 and out["zones"]["all"]["total_s"] == 100


def test_empty_period_has_no_zones():
    out = zones_for_period(ACTS, ZONES, "month", 5, date(2026, 10, 3))
    assert out["label"] == "mei 2026" and out["zones"] == {}


def test_month_across_year():
    out = zones_for_period(ACTS, ZONES, "month", 10, date(2026, 10, 3))
    assert out["label"] == "december 2025" and out["zones"]["all"]["total_s"] == 50


def test_bounds_ignore_non_sport_entries():
    out = zones_for_period([], {**ZONES, "_note": "tekst"}, "week", 0, date(2026, 10, 3))
    assert set(out["bounds"]) == {"run", "ride"}


# ── history ──────────────────────────────────────────────────────────────────


def test_week_history_oldest_first_with_empty_weeks():
    h = zone_history(ACTS, "week", 4, "all", date(2026, 10, 3))
    assert [i["start"] for i in h["items"]] == ["2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28"]
    assert h["items"][0]["total_s"] == 0 and h["items"][0]["pct"] == {"Z1": 0, "Z2": 0, "Z3": 0, "Z4": 0, "Z5": 0}
    assert h["items"][2]["total_s"] == 100
    last = h["items"][-1]
    assert last["end"] == "2026-10-04" and last["label"] == "week 40 · 28 sep – 4 okt 2026"
    assert last["seconds"] == {"Z1": 0, "Z2": 900, "Z3": 100, "Z4": 200, "Z5": 0} and last["total_s"] == 1200
    assert h["period"] == "week" and h["sport"] == "all"
    assert h["sports"] == ["run", "ride"]


def test_history_sport_filter():
    h = zone_history(ACTS, "week", 2, "ride", date(2026, 10, 3))
    assert h["sport"] == "ride"
    assert h["items"][0]["total_s"] == 0
    assert h["items"][1]["seconds"] == {"Z1": 0, "Z2": 300, "Z3": 100, "Z4": 0, "Z5": 0}
    assert h["items"][1]["pct"]["Z2"] == 75.0


def test_month_history_across_year():
    h = zone_history(ACTS, "month", 11, "all", date(2026, 10, 3))
    assert h["items"][0]["start"] == "2025-12-01" and h["items"][0]["label"] == "december 2025"
    assert h["items"][0]["total_s"] == 50
    assert h["items"][-1]["start"] == "2026-10-01" and h["items"][-1]["end"] == "2026-10-31"
    assert h["items"][-2]["total_s"] == 700  # September: Sunday run + Monday run (28 Sep)


# ── endpoints ────────────────────────────────────────────────────────────────


def author(request: Request) -> str:
    if request.headers.get("x-user") != "alice":
        raise HTTPException(status_code=401, detail="niet ingelogd")
    return fake_user_dep(FakeStore(activities=ACTS, zones=ZONES))()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(make_router(lambda: date(2026, 10, 3), author))
    return TestClient(app, headers={"x-user": "alice"})


def test_auth_required(client):
    for path in ("/api/zones", "/api/zones/history"):
        assert client.get(path, headers={"x-user": ""}).status_code == 401


def test_zones_endpoint(client):
    out = client.get("/api/zones?period=week&offset=1").json()
    assert out["start"] == "2026-09-21" and out["zones"]["all"]["total_s"] == 100
    assert client.get("/api/zones").json()["period"] == "week"
    assert client.get("/api/zones?period=month").json()["label"] == "oktober 2026"


def test_history_endpoint(client):
    out = client.get("/api/zones/history?period=month&count=3&sport=run").json()
    assert [i["label"] for i in out["items"]] == ["augustus 2026", "september 2026", "oktober 2026"]
    assert out["items"][1]["total_s"] == 700
    assert len(client.get("/api/zones/history").json()["items"]) == 12
    assert len(client.get("/api/zones/history?period=week&count=104").json()["items"]) == 104


@pytest.mark.parametrize(
    "path",
    [
        "/api/zones?period=year",
        "/api/zones?offset=-1",
        "/api/zones/history?period=day",
        "/api/zones/history?count=0",
        "/api/zones/history?period=week&count=105",
        "/api/zones/history?period=month&count=37",
    ],
)
def test_bad_input_is_422(client, path):
    assert client.get(path).status_code == 422


def test_wired_into_app(tmp_path):
    from api.main import create_app
    from tests.test_api import PASSWORD, make_settings
    from tools import db

    e = db.connect(new_database_url())
    c = TestClient(create_app(engine=e, settings=make_settings()))
    assert c.get("/api/zones").status_code == 401
    assert c.get("/api/zones/history").status_code == 401
    c.post("/api/login", json={"username": "alice", "password": PASSWORD})
    assert c.get("/api/zones").json()["zones"] == {}
    assert len(c.get("/api/zones/history?period=month&count=6").json()["items"]) == 6
