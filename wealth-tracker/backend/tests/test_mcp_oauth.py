"""OAuth uses the existing wealth data isolation and bookkeeping permissions."""

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import update

from tests.test_mcp_agents import _call, _login, _mcp, _seed_bank
from trackerai_accounts.service import now
from trackerai_accounts.store import oauth_grants

sys.path.append(str(Path(__file__).resolve().parents[3] / "packages/accounts/tests"))
from oauth_fixtures import seed_token


def agent(client, shared, scope="read"):
    from app.main import app

    _login(client)
    token, gid = seed_token(shared, shared.by_username("alice"), "wealth", scope)
    return TestClient(app, headers={"Authorization": "Bearer " + token}), token, gid


def test_read_only_wealth_and_data_isolation(client, _accounts):
    oauth, token, gid = agent(client, _accounts)
    _seed_bank(client)
    assert oauth.get("/api/bank-transactions").json()["count"] == 3
    _login(client, "bob", "bobpw")
    assert client.get("/api/bank-transactions").json()["count"] == 0
    tools = _mcp(oauth, "tools/list")["result"]["tools"]
    assert "list_transactions" in {t["name"] for t in tools} and "label_transactions" not in {t["name"] for t in tools}
    assert all(t["securitySchemes"] == [{"type": "oauth2", "scopes": ["wealth:read"]}] for t in tools)
    assert not _call(oauth, "list_transactions")["isError"]
    assert _call(oauth, "label_transactions", {"ids": [1], "category": "Food"})["isError"]
    assert oauth.post("/api/agent-tokens", json={"name": "No"}).status_code == 403
    assert oauth.get("/api/connections").status_code == 403
    assert oauth.post("/api/mcp/" + token, json={}).status_code == 401
    with _accounts.engine.begin() as c:
        c.execute(update(oauth_grants).where(oauth_grants.c.id == gid).values(revoked_at=now()))
    response = oauth.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response.status_code == 401 and "resource_metadata=" in response.headers["www-authenticate"]


def test_write_connection_has_no_feedback_admin(client, _accounts):
    from app.core import auth_store

    oauth, _, _ = agent(client, _accounts, "write")
    cfg = auth_store.load_config()
    cfg["admins"] = ["alice"]
    auth_store.save_config(cfg)
    tools = _mcp(oauth, "tools/list")["result"]["tools"]
    assert "label_transactions" in {t["name"] for t in tools}
    assert "list_feedback" not in {t["name"] for t in tools}
    assert _call(oauth, "list_feedback")["isError"]


def test_browser_cookie_cannot_expand_oauth_permissions(client, _accounts):
    _, token, _ = agent(client, _accounts)
    # This browser has an ordinary editing session. Its explicit OAuth header
    # must still behave as the approved read-only connection.
    client.headers["Authorization"] = "Bearer " + token
    assert client.put("/api/budget/Food", json={"amount": 100}).status_code == 403
    assert client.get("/api/admin/tracker").status_code == 403
    client.headers["Authorization"] = "Bearer ta_o_invalid"
    assert client.get("/api/auth/me").status_code == 401
