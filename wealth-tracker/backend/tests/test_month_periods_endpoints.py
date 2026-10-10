"""
/api/month-periods and /api/accounts/{id}/schedule.

The arithmetic is in backend/tests/domain/test_month_periods.py and
backend/tests/domain/test_debt_schedule.py; here: the routes, the error codes
and that everyone has their own setting.
"""


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def test_without_a_session_nothing(client):
    assert client.get("/api/month-periods").status_code == 401


def test_calendar_month_by_default(client):
    _login(client)
    r = client.get("/api/month-periods").json()
    assert r["mode"] == "calendar" and r["active"] == "calendar" and r["category"] == "Salaris"


def test_salary_without_a_salary_says_it_stays_the_calendar(client):
    _login(client)
    r = client.put("/api/month-periods", json={"mode": "salary"}).json()
    assert r["mode"] == "salary" and r["active"] == "calendar" and r["recognised"] is None


def test_an_own_day_makes_the_salary_month_active(client):
    _login(client)
    r = client.put("/api/month-periods", json={"mode": "salary", "day": 25}).json()
    assert r["active"] == "salary" and r["day"] == 25 and r["day_configured"] == 25
    assert all(g[8:] <= "25" for g in r["boundaries"])
    r = client.put("/api/month-periods", json={"day": None}).json()
    assert r["day_configured"] is None


def test_nonsense_is_400(client):
    _login(client)
    assert client.put("/api/month-periods", json={"mode": "week"}).status_code == 400
    assert client.put("/api/month-periods", json={"day": 40}).status_code == 400
    assert client.put("/api/month-periods", json={"iets": 1}).status_code == 400


def test_everyone_their_own_month_periods(client):
    _login(client)
    client.put("/api/month-periods", json={"mode": "salary"})
    client.post("/api/auth/logout")
    _login(client, "bob", "bobpw")
    assert client.get("/api/month-periods").json()["mode"] == "calendar"


def _debt(client) -> int:
    r = client.post("/api/accounts", json={"kind": "debt", "provider": "manual", "name": "DUO"})
    rid = r.json()["account"]["id"]
    client.put(f"/api/accounts/{rid}/balance", json={"date": "2020-01-01", "balance": 20000})
    return rid


def test_interest_and_repayment_on_a_debt(client):
    _login(client)
    rid = _debt(client)
    r = client.put(f"/api/accounts/{rid}/schedule", json={"interest": 2.4, "repayment": 100, "from_date": "2020-01-01"})
    assert r.status_code == 200, r.text
    account = r.json()["account"]
    assert account["schedule"] == {"interest": 2.4, "repayment": 100.0, "from_date": "2020-01-01"}
    assert account["balance_source"] == "schedule" and account["balance"] > -20000

    balances = client.get(f"/api/accounts/{rid}/balances").json()
    assert len(balances["balances"]) == 1, "de berekende maanden zijn geen metingen"
    assert balances["calculated"] and all(p["source"] == "schedule" for p in balances["calculated"])


def test_interest_and_repayment_only_on_a_debt(client):
    _login(client)
    r = client.post("/api/accounts", json={"kind": "bank", "provider": "manual", "name": "Bank"})
    rid = r.json()["account"]["id"]
    assert client.put(f"/api/accounts/{rid}/schedule", json={"interest": 2, "repayment": 50}).status_code == 400


def test_remove_the_schedule(client):
    _login(client)
    rid = _debt(client)
    client.put(f"/api/accounts/{rid}/schedule", json={"interest": 2.4, "repayment": 100})
    r = client.put(f"/api/accounts/{rid}/schedule", json={"interest": None, "repayment": None})
    assert r.json()["account"]["schedule"] is None
