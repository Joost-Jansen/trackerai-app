"""
/api/dividend behind its beta flag.

Hiding a tab in the nav is not access control. These prove the endpoint refuses
an account without the flag, that the flag is a real registry entry (so the
admin panel can grant it instead of an admin editing YAML by hand), that an
empty account gets a well-formed payload rather than a 500, and that the plural
route the Details tab has always owned is untouched.
"""

from app.core import auth_store


def _login(client, who="alice"):
    return client.post("/api/auth/login", json={"username": who, "password": f"{who}pw"})


def _grant(who="alice"):
    cfg = auth_store.load_config()
    cfg["beta"] = {"dividends": [who]}
    auth_store.save_config(cfg)


def test_dividend_requires_auth(client):
    assert client.get("/api/dividend").status_code == 401


def test_dividend_is_refused_without_the_beta_flag(client):
    _login(client)
    assert client.get("/api/dividend").status_code == 403


def test_the_flag_bob_has_does_not_open_alices_tab(client):
    _grant("bob")
    _login(client, "alice")
    assert client.get("/api/dividend").status_code == 403


def test_dividend_is_a_registered_beta_feature():
    """The admin panel renders BETA_FEATURES and /api/admin validates against
    it, so a router naming a key that is not in there can never be granted."""
    assert "dividends" in auth_store.BETA_FEATURES


def test_an_empty_account_gets_the_empty_state_not_an_error(client):
    _grant()
    _login(client)
    resp = client.get("/api/dividend")
    assert resp.status_code == 200
    body = resp.json()
    assert body["totals"]["net"] == 0.0
    assert body["by_year"] == []
    assert body["by_stock"] == []
    assert body["payments"] == []
    # Twelve calendar months exist whether or not anything has ever been paid.
    assert len(body["seasonality"]) == 12


def test_the_singular_route_does_not_shadow_the_details_tabs_plural_one(client):
    """/api/dividends belongs to routers/details.py and is not beta-gated. If
    the new prefix ever swallowed it, the Details tab would 403 for everyone."""
    _login(client)
    resp = client.get("/api/dividends")
    assert resp.status_code == 200
    assert resp.json() == {"by_stock": [], "payments": []}


def test_me_reports_the_granted_flag_so_the_nav_can_show_the_tab(client):
    _grant()
    _login(client)
    assert "dividends" in client.get("/api/auth/me").json()["beta_features"]
