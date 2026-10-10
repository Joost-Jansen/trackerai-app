"""
wealth-tracker for the trackerai.nl admin page (routers/admin.py, /api/admin/tracker), and feedback in the shape
both trackers share. The page reaches these through /api/hub/wealth/..., which forwards to the same paths.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

BOB_PW = "bob" + "pw"
ALICE_PW = "alice" + "pw"


def _login(client, user="alice", pw=ALICE_PW):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _admin(name="alice"):
    from app.core import auth_store

    with auth_store._locked_update() as cfg:
        cfg["admins"] = [name]


def _account_id(folder):
    from app.core.accounts import APP, accounts

    return accounts.account_id_for_local_key(APP, folder)


def _bank(folder, *days):
    """One bank transaction per booking date in `days` in the folder's own database."""
    from domain import database

    with database.user_db(folder) as conn:
        database.init_db(conn)
        conn.execute("INSERT INTO accounts (kind, provider, name, created_at) VALUES ('bank', 'ing', 'Betaal', '2026-01-01')")
        for i, d in enumerate(days):
            conn.execute("INSERT INTO bank_transactions (account_id, date, amount, name, dedup_hash) VALUES (1, ?, 10, 'Shop', ?)",
                         (d.isoformat(), f"{folder}-{i}"))
        conn.commit()


def _db_size(folder):
    from domain import database

    return database.db_size_bytes(folder)


@pytest.fixture()
def admin(client):
    """alice admin and signed in; bob has an account too (made on his first login)."""
    _admin()
    _login(client, "bob", BOB_PW)
    _login(client)
    return client


# --- access --------------------------------------------------------------------


def test_the_tracker_routes_are_for_admins_only(client):
    from app.main import app

    anonymous = TestClient(app, headers={"Origin": "http://testserver"})
    assert anonymous.get("/api/admin/tracker").status_code == 401
    assert anonymous.patch("/api/admin/tracker/betas/1", json={"feature": "returns", "enabled": True}).status_code == 401
    _login(client)  # alice, not an admin
    assert client.get("/api/admin/tracker").status_code == 403
    assert client.patch(f"/api/admin/tracker/betas/{_account_id('alice')}", json={"feature": "returns", "enabled": True}).status_code == 403


def test_an_admins_agent_token_does_not_reach_them(admin):
    from app.main import app

    token = admin.post("/api/agent-tokens", json={"name": "Claude", "scope": "write"}).json()["token"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    assert agent.get("/api/admin/tracker").status_code == 403
    assert agent.patch("/api/admin/tracker/betas/1", json={"feature": "returns", "enabled": True}).status_code == 403


# --- GET /api/admin/tracker ---------------------------------------------------------


def test_the_overview_has_betas_measure_and_accounts(admin):
    _bank("bob", date.today(), date.today() - timedelta(days=400))
    r = admin.get("/api/admin/tracker")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["app"] == "wealth"
    assert [b["id"] for b in body["betas"]] == ["rebalancing", "returns", "dividends", "calendar", "money"]
    assert body["betas"][0]["name"] == {"en": "Rebalancing tab", "nl": "Herbalanceren-tab"}
    assert body["measure"] == {"en": "bank transactions", "nl": "banktransacties"}
    by_id = {a["account_id"]: a for a in body["accounts"]}
    assert set(by_id) == {_account_id("alice"), _account_id("bob")}
    bob = by_id[_account_id("bob")]
    assert bob == {"account_id": _account_id("bob"), "betas": ["money"], "count": 2, "last_at": date.today().isoformat(),
                   "disk_bytes": _db_size("bob")}
    assert bob["disk_bytes"] > 0 and body["disk_bytes_total"] == bob["disk_bytes"]
    # alice has no bank transactions (no database even): zero, and no date or bytes
    alice = by_id[_account_id("alice")]
    assert alice["count"] == 0 and alice["last_at"] is None and alice["disk_bytes"] == 0


def test_weekly_is_twelve_iso_weeks_zero_filled(admin):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    _bank("bob", today, monday, monday - timedelta(weeks=7) + timedelta(days=3), monday - timedelta(weeks=20))
    _bank("alice", monday - timedelta(weeks=11))
    weekly = admin.get("/api/admin/tracker").json()["weekly"]
    assert [w["week"] for w in weekly] == [(monday - timedelta(weeks=n)).isoformat() for n in range(11, -1, -1)]
    values = [w["value"] for w in weekly]
    assert values[-1] == (1 if today == monday else 2)  # today and this Monday, one row if they are the same day
    assert values[-8] == 1 and values[0] == 1
    assert sum(values) == values[-1] + 2  # the one from 20 weeks ago is outside


def test_a_user_without_an_account_counts_in_weekly_but_is_not_listed(admin):
    from app.core import auth_store

    auth_store.ensure_user("carol", "Carol")
    _bank("carol", date.today())
    body = admin.get("/api/admin/tracker").json()
    assert body["weekly"][-1]["value"] == 1
    assert len(body["accounts"]) == 2
    assert body["disk_bytes_total"] == _db_size("carol") > 0  # on disk all the same


def test_disk_bytes_are_the_database_size(admin):
    from domain import database

    _bank("bob", date.today())
    body = admin.get("/api/admin/tracker").json()
    bob = database.user_stats("bob")["db_size_bytes"]
    assert next(a for a in body["accounts"] if a["account_id"] == _account_id("bob"))["disk_bytes"] == bob > 0


def test_a_database_without_bank_transactions_is_skipped(admin):
    from domain import database

    database.connect("bob").close()  # an empty database (or schema), no tables
    r = admin.get("/api/admin/tracker")
    assert r.status_code == 200
    assert next(a for a in r.json()["accounts"] if a["account_id"] == _account_id("bob"))["count"] == 0


# --- PATCH /api/admin/tracker/betas/{account_id} -----------------------------------


def test_toggling_a_beta_persists_and_is_audited(admin):
    bob = _account_id("bob")
    r = admin.patch(f"/api/admin/tracker/betas/{bob}", json={"feature": "returns", "enabled": True})
    assert r.status_code == 200, r.text
    assert r.json() == {"account_id": bob, "betas": ["returns", "money"], "count": 0, "last_at": None, "disk_bytes": 0}
    listed = next(a for a in admin.get("/api/admin/tracker").json()["accounts"] if a["account_id"] == bob)
    assert listed["betas"] == ["returns", "money"]
    # the grants the app itself reads
    from app.core import audit, auth_store

    assert set(auth_store.user_beta_features("bob")) == {"returns", "money"}
    entry = audit.tail(1)[0]
    assert (entry["actor"], entry["action"], entry["target"], entry["detail"]) == ("alice", "beta_feature", "bob", "returns on")

    assert admin.patch(f"/api/admin/tracker/betas/{bob}", json={"feature": "money", "enabled": False}).json()["betas"] == ["returns"]
    _login(admin, "bob", BOB_PW)
    assert admin.get("/api/auth/me").json()["beta_features"] == ["returns"]


def test_toggle_errors(admin):
    bob = _account_id("bob")
    assert admin.patch("/api/admin/tracker/betas/99999", json={"feature": "returns", "enabled": True}).status_code == 404
    r = admin.patch(f"/api/admin/tracker/betas/{bob}", json={"feature": "teleport", "enabled": True})
    assert r.status_code == 422 and "teleport" in r.json()["detail"]
    assert admin.patch(f"/api/admin/tracker/betas/{bob}", json={"feature": "returns"}).status_code == 422


def test_an_account_that_left_wealth_tracker_is_404(admin, _accounts):
    from app.core.accounts import APP

    bob = _account_id("bob")
    _accounts.leave_app(bob, APP)
    assert admin.patch(f"/api/admin/tracker/betas/{bob}", json={"feature": "returns", "enabled": True}).status_code == 404
    assert bob not in {a["account_id"] for a in admin.get("/api/admin/tracker").json()["accounts"]}


# --- feedback in the shared shape ----------------------------------------------------

FIELDS = {"id", "app", "kind", "message", "page", "context", "status", "reply", "created_at", "updated_at",
          "account_id", "username", "has_screenshot"}


def test_feedback_items_have_the_shared_shape(admin):
    from datetime import datetime

    _login(admin, "bob", BOB_PW)
    sent = admin.post("/api/feedback", json={"kind": "idea", "message": "Meer grafieken", "app": "money"})
    assert sent.status_code == 201
    item = sent.json()
    assert set(item) == FIELDS
    assert item["app"] == "wealth" and item["account_id"] == _account_id("bob") and item["username"] == "bob"
    assert datetime.fromisoformat(item["created_at"]).tzinfo is not None and item["updated_at"] is None
    assert item["has_screenshot"] is False
    assert admin.get("/api/feedback").json()["feedback"] == [item]

    _login(admin)
    inbox = admin.get("/api/admin/feedback").json()["feedback"]
    assert inbox == [item]
    answered = admin.patch(f"/api/admin/feedback/{item['id']}", json={"status": "planned", "reply": "Komt eraan"}).json()
    assert set(answered) == FIELDS and answered["app"] == "wealth"
    assert datetime.fromisoformat(answered["updated_at"]).tzinfo is not None


def test_old_stock_and_money_rows_are_reported_as_wealth(admin):
    from app.core import feedback_store

    old = feedback_store.add("bob", "stock", "bug", "Oud", "/", {})
    feedback_store.add("bob", "money", "bug", "Ook oud", "/budget", {})
    feedback_store.add("gone", None, "idea", "Van iemand die weg is", None, None)
    # a row from before timestamps carried their timezone
    with feedback_store._connect() as conn:
        conn.execute("UPDATE feedback SET created_at = '2025-03-01T10:00:00' WHERE id = ?", (old,))
    items = admin.get("/api/admin/feedback").json()["feedback"]
    assert {f["app"] for f in items} == {"wealth"}
    gone = items[0]
    assert (gone["account_id"], gone["username"]) == (None, "gone")
    assert items[-1]["created_at"] == "2025-03-01T10:00:00+00:00"
    # stored as it was
    with feedback_store._connect() as conn:
        assert [r[0] for r in conn.execute("SELECT app FROM feedback ORDER BY id")] == ["stock", "money", None]
