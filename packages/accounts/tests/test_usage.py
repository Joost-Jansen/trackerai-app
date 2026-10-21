"""Usage for the admin page: page visits per day, app and account, a count and never which page."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import insert, select
from test_accounts import PASSWORD, accounts, config, health, make_app, register, wealth  # noqa: F401  (fixtures)

from trackerai_accounts import Accounts, connect
from trackerai_accounts.service import now
from trackerai_accounts.store import daily_use


def _anna(client, accounts):  # noqa: F811
    """anna, an ordinary account: the first one made becomes the admin (who must set up two-step login first), and
    sign-up closes after it."""
    register(client, name="rita")
    client.cookies.clear()
    accounts.set_registration_mode(accounts.by_username("rita"), "open")
    assert register(client).status_code == 200
    return accounts.by_username("anna")["id"]


def test_a_visit_counts_once_per_call_in_its_own_app_only(health, wealth, accounts):  # noqa: F811
    anna = _anna(health, accounts)  # anna uses health-tracker, not wealth-tracker
    for _ in range(3):
        assert health.post("/api/account/visit").status_code == 204
    assert wealth.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}).status_code == 200
    assert wealth.post("/api/account/visit").status_code == 204  # logged in, but not using wealth-tracker: not counted
    with accounts.engine.connect() as c:
        rows = c.execute(select(daily_use)).mappings().all()
    assert [(r["app"], r["account_id"], r["visits"]) for r in rows] == [("health", anna, 3)]


def test_a_visit_needs_a_login(health):  # noqa: F811
    assert health.post("/api/account/visit").status_code == 401


def test_the_count_stops_at_the_daily_cap(health, accounts, monkeypatch):  # noqa: F811
    _anna(health, accounts)
    monkeypatch.setattr(type(accounts), "VISITS_PER_DAY", 2)
    for _ in range(5):
        health.post("/api/account/visit")
    with accounts.engine.connect() as c:
        assert c.execute(select(daily_use.c.visits)).scalar_one() == 2


def test_usage_per_week_and_active_accounts(health, accounts):  # noqa: F811
    anna = _anna(health, accounts)
    health.cookies.clear()
    register(health, name="bob")
    bob = accounts.by_username("bob")["id"]
    today = now().date()
    with accounts.engine.begin() as c:
        c.execute(
            insert(daily_use),
            [
                {"day": today, "app": "health", "account_id": anna, "visits": 4},
                {"day": today, "app": "wealth", "account_id": anna, "visits": 1},
                {"day": today - timedelta(days=20), "app": "health", "account_id": bob, "visits": 2},
                {"day": today - timedelta(days=200), "app": "health", "account_id": bob, "visits": 9},  # outside the weeks
            ],
        )
    u = accounts.usage(weeks=12)
    assert len(u["weeks"]) == 12 and u["weeks"][-1] == (today - timedelta(days=today.weekday())).isoformat()
    assert u["apps"]["health"]["visits"][-1] == 4 and u["apps"]["health"]["users"][-1] == 1
    assert u["apps"]["wealth"]["visits"][-1] == 1
    assert sum(u["apps"]["health"]["visits"]) == 6 and sum(u["apps"]["health"]["users"]) == 2
    assert (u["active_7"], u["active_30"]) == (1, 2)
    assert u["last_seen"] == {str(anna): today.isoformat(), str(bob): (today - timedelta(days=20)).isoformat()}


def test_usage_is_for_admins_and_goes_with_a_deleted_account(tmp_path):
    cfg = config(tmp_path, require_totp="off")
    accounts = Accounts(connect(cfg.database_url), cfg)  # noqa: F811
    admin = TestClient(make_app(accounts, "health"), base_url="https://health.example")
    register(admin, name="rita")  # the first account: an admin
    admin.post("/api/account/visit")
    assert admin.get("/api/trackerai/admin/usage").json()["active_7"] == 1
    accounts.set_registration_mode(accounts.by_username("rita"), "open")
    other = TestClient(make_app(accounts, "health"), base_url="https://health.example")
    register(other, name="bob")
    assert other.get("/api/admin/usage").status_code == 403

    rita, bob = accounts.by_username("rita")["id"], accounts.by_username("bob")["id"]
    accounts.record_visit(bob, "health")
    accounts.delete_account(bob)
    with accounts.engine.connect() as c:
        assert {r.account_id for r in c.execute(select(daily_use.c.account_id))} == {rita}
