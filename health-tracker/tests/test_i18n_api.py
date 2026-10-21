"""Language (nl/en) per user, and errors and warnings as codes the site translates (T25).

The API keeps a Dutch `detail` for agents and scripts, and adds `code` (+ `params`) so the site can show the error in
the user's own language."""

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.plans import parse_table_coded
from tests.test_api import PASSWORD, engine, login, make_settings  # noqa: F401  (engine is a fixture)

ANNA_PW = "anna-wachtwoord-1"


@pytest.fixture
def app(engine, tmp_path):  # noqa: F811
    return create_app(engine=engine, settings=make_settings())


def admin(app):
    c = TestClient(app)
    login(c)
    return c


def test_me_has_no_locale_until_chosen(app):
    assert admin(app).get("/api/me").json()["locale"] is None


def test_account_stores_locale(app):
    c = admin(app)
    r = c.patch("/api/account", json={"locale": "en"})
    assert r.status_code == 200 and r.json()["locale"] == "en"
    assert c.get("/api/me").json()["locale"] == "en"
    c.patch("/api/account", json={"display_name": "Alice"})  # other fields leave the language alone
    assert c.get("/api/me").json()["locale"] == "en"
    c.patch("/api/account", json={"locale": "nl"})
    assert c.get("/api/me").json()["locale"] == "nl"


def test_unknown_locale_is_rejected_with_a_code(app):
    r = admin(app).patch("/api/account", json={"locale": "de"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "invalid_locale" and body["params"] == {"options": ["nl", "en"]}
    assert body["detail"]  # Dutch text stays for agents


def test_locale_is_per_user(app):
    a = admin(app)
    a.patch("/api/trackerai/admin/registration", json={"registration": "open"})
    anna = TestClient(app)
    r = anna.post(
        "/api/register", json={"username": "anna", "email": "anna@example.org", "password": ANNA_PW, "locale": "en", "consent": True}
    )
    assert r.status_code == 200
    assert anna.get("/api/me").json()["locale"] == "en"
    assert a.get("/api/me").json()["locale"] is None


def test_register_with_unknown_locale_fails_before_creating_the_account(app):
    admin(app).patch("/api/trackerai/admin/registration", json={"registration": "open"})
    c = TestClient(app)
    r = c.post(
        "/api/register", json={"username": "anna", "email": "anna@example.org", "password": ANNA_PW, "locale": "xx", "consent": True}
    )
    assert r.status_code == 422 and r.json()["code"] == "invalid_locale"
    assert (
        c.post("/api/register", json={"username": "anna", "email": "anna@example.org", "password": ANNA_PW, "consent": True}).status_code
        == 200
    )


def test_agents_cannot_set_the_locale(app):
    c = admin(app)
    token = c.post("/api/agent-tokens", json={"name": "Claude"}).json()["token"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    r = agent.patch("/api/account", json={"locale": "en"})
    assert r.status_code == 403 and r.json()["code"] == "site_login_only"


@pytest.mark.parametrize(
    "call, status, code, params",
    [
        (lambda c: c.post("/api/login", json={"username": "alice", "password": "fout-wachtwoord"}), 401, "bad_credentials", {}),
        (lambda c: c.get("/api/dashboard"), 401, "not_logged_in", {}),
        (
            lambda c: c.post("/api/register", json={"username": "bob", "email": "bob@example.org", "password": "x" * 12}),
            403,
            "registration_closed",
            {},
        ),
    ],
)
def test_errors_without_login_have_codes(app, call, status, code, params):
    r = call(TestClient(app))
    assert r.status_code == status
    assert r.json()["code"] == code and r.json()["params"] == params and r.json()["detail"]


def test_errors_with_params(app):
    c = admin(app)
    r = c.post("/api/account/password", json={"current": PASSWORD, "new": "kort"})
    assert r.status_code == 422 and r.json()["code"] == "password_too_short" and r.json()["params"] == {"min": 10}
    assert "10" in r.json()["detail"]
    r = c.put("/api/settings/profile", json={"weight_kg": 10})
    assert r.json()["code"] == "profile_range" and r.json()["params"] == {"field": "weight_kg", "min": 25, "max": 250}
    r = c.put("/api/settings/zones", json={"percent": [70, 77, 85, 92.5], "sports": {"run": {"max_hr": 300}}})
    assert r.json()["code"] == "max_hr_range" and r.json()["params"] == {"min": 100, "max": 230}
    assert c.get("/api/plans/999").json()["code"] == "plan_not_found"
    assert c.get("/api/routes/nope").json()["code"] == "route_not_found"
    assert c.get("/api/activities/nope").json()["code"] == "activity_not_found"
    assert c.get("/api/docs/notes").json()["code"] == "document_not_found"
    assert c.post("/api/agent-tokens", json={"name": ""}).json() == {
        "detail": "naam van 1 tot 60 tekens",
        "code": "token_name_length",
        "params": {"min": 1, "max": 60},
    }
    assert c.post("/api/connections/sync").json()["code"] == "garmin_not_connected"


def test_plain_http_errors_keep_their_shape(app):
    # FastAPI's own errors (validation, unknown route) are untouched: no code
    r = admin(app).post("/api/entries", json={"kind": "log"})
    assert r.status_code == 422 and "code" not in r.json()


def test_plan_import_warnings_come_with_codes():
    items, warnings = parse_table_coded("| Datum | Sport |\n|---|---|\n| morgen | lopen |\n| 2026-10-06 | lopen |", 2026)
    assert len(items) == 1
    assert warnings == [{"code": "row_skipped_date", "params": {"row": 2, "value": "morgen"}}]
    assert parse_table_coded("", 2026) == ([], [{"code": "no_table", "params": {}}])
    assert parse_table_coded("a,b\n1,2", 2026)[1] == [{"code": "no_date_column", "params": {"columns": ["a", "b"]}}]


def test_plan_import_endpoint_returns_warning_codes(app):
    r = admin(app).post("/api/plans/import", json={"text": "| Datum | Sport |\n|---|---|\n| morgen | lopen |", "preview": True}).json()
    assert r["warnings"] == ["Rij 2 overgeslagen: datum 'morgen' niet herkend."]
    assert r["warning_codes"] == [{"code": "row_skipped_date", "params": {"row": 2, "value": "morgen"}}]


def test_garmin_login_errors_have_codes(app):
    from api.connections import GarminLoginError

    class Refuses:
        def start(self, email, password):
            raise GarminLoginError("garmin_rejected")

    app2 = create_app(engine=app.state.engine, settings=make_settings(), garmin_auth=Refuses())
    c = TestClient(app2)
    login(c)
    r = c.post("/api/connections/garmin", json={"email": "a@b.c", "password": "x"})
    assert r.status_code == 400 and r.json()["code"] == "garmin_rejected"
    assert r.json()["detail"] == "Garmin weigert de inlog: controleer e-mail en wachtwoord (of de MFA-code)."
