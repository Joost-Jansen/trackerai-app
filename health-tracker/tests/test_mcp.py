import hashlib

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from tests.test_api import engine, make_settings  # noqa: F401  (engine is a fixture)

TOKEN = "mcp-test-token"


@pytest.fixture
def client(engine, tmp_path):  # noqa: F811
    settings = make_settings(agent_token_hash=hashlib.sha256(TOKEN.encode()).hexdigest())
    return TestClient(create_app(engine=engine, settings=settings))


def rpc(client, method, params=None, mid=1, path="/api/mcp", auth=True):
    headers = {"Authorization": f"Bearer {TOKEN}"} if auth else {}
    return client.post(path, headers=headers, json={"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})


def call(client, name, **args):
    res = rpc(client, "tools/call", {"name": name, "arguments": args}).json()["result"]
    return res["content"][0]["text"], res["isError"]


def test_requires_token(client):
    assert rpc(client, "tools/list", auth=False).status_code == 401
    assert rpc(client, "tools/list", auth=False, path="/api/mcp/fout").status_code == 401
    assert rpc(client, "tools/list", auth=False, path=f"/api/mcp/{TOKEN}").status_code == 200


def test_initialize_and_list(client):
    init = rpc(
        client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}
    ).json()["result"]
    assert init["protocolVersion"] == "2025-03-26" and "tools" in init["capabilities"]
    note = client.post(
        "/api/mcp", headers={"Authorization": f"Bearer {TOKEN}"}, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert note.status_code == 202
    names = {t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert {"get_context", "get_plan", "create_plan", "replace_plan_sessions", "add_log", "update_doc"} <= names
    assert rpc(client, "nope").json()["error"]["code"] == -32601


def test_any_client_can_connect(client):
    """Clients differ in protocol version, header or URL token, and whether they look for an SSE stream."""
    for asked, got in [("2025-11-25", "2025-11-25"), ("2024-11-05", "2024-11-05"), ("1999-01-01", "2025-11-25")]:
        assert rpc(client, "initialize", {"protocolVersion": asked}).json()["result"]["protocolVersion"] == got
    assert rpc(client, "tools/list", auth=False, path=f"/api/mcp/{TOKEN}").json()["result"]["tools"]
    assert client.get("/api/mcp", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 405


def test_tools_read_and_write(client):
    text, err = call(client, "list_activities", sport="run")
    assert not err and "Ochtendloop" in text
    aid = text.splitlines()[2].split("|")[1].strip()
    assert "Ochtendloop" in call(client, "get_activity", id=aid)[0]
    assert call(client, "get_activity", id="bestaat-niet")[1] is True

    table = "| Datum | Sport | Km | Zone |\n|---|---|---|---|\n| 2026-09-29 | lopen | 10 | Z2 |\n| 2026-10-02 | lopen | 14 | Z2 |"
    text, err = call(client, "create_plan", title="Blok 1", table=table, goal="marathon 3:45")
    assert not err and "gedaan" in text and "door agent" in text
    text, _ = call(client, "replace_plan_sessions", table=table.replace("14", "16"))
    assert "| 16.0 |" in text
    assert "afgerond" in call(client, "set_plan_status", status="afgerond")[0]
    assert call(client, "get_plan")[0] == "Geen actief schema."

    call(client, "add_log", title="Sessie", body="Advies: rustig aan", day="2026-09-30")
    assert "Advies: rustig aan" in call(client, "list_log")[0]
    call(client, "update_doc", key="goals", body="# Doelen\nMarathon 3:45")
    assert call(client, "get_doc", key="goals")[0].endswith("3:45")

    ctx, err = call(client, "get_context")
    assert not err and ctx.startswith("# Trainingscontext") and "Marathon 3:45" in ctx and "Sessie" in ctx
    assert '"predictions"' in call(client, "get_trends")[0]


def test_batch(client):
    res = client.post(
        "/api/mcp",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/initialized"}],
    )
    assert res.json() == [{"jsonrpc": "2.0", "id": 1, "result": {}}]


def test_token_in_path_is_redacted_in_access_log():
    import logging

    from trackerai_websec.log_redact import RedactFilter

    rec = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', ("1.2.3.4", "POST", "/api/mcp/geheim123", "1.1", 200), None
    )
    RedactFilter().filter(rec)
    assert "geheim123" not in rec.getMessage() and "/api/mcp/***" in rec.getMessage()


def test_tokens_made_on_the_site_work_for_api_and_mcp(client):
    assert client.post("/api/agent-tokens", json={"name": "x"}).status_code == 401
    bearer = {"Authorization": f"Bearer {TOKEN}"}
    assert client.post("/api/agent-tokens", headers=bearer, json={"name": "x"}).status_code == 403  # agents cannot mint
    client.post("/api/login", json={"username": "alice", "password": "test-wachtwoord-123"})
    made = client.post("/api/agent-tokens", json={"name": "Claude app", "scope": "write"}).json()
    assert made["token"].startswith("tr_") and made["name"] == "Claude app"
    assert "hash" not in client.get("/api/agent-tokens").json()["tokens"][0]

    fresh = TestClient(client.app)  # no cookie
    me = fresh.get("/api/me", headers={"Authorization": f"Bearer {made['token']}"}).json()
    assert me["username"] == "alice" and me["via"] == "agent"
    assert rpc(fresh, "tools/list", auth=False, path=f"/api/mcp/{made['token']}").status_code == 200

    assert client.delete(f"/api/agent-tokens/{made['id']}").json() == {"ok": True}
    assert fresh.get("/api/me", headers={"Authorization": f"Bearer {made['token']}"}).status_code == 401
    assert client.delete(f"/api/agent-tokens/{made['id']}").status_code == 404


def test_plans_listed_opened_by_id_drafted_and_achievements(client):
    table = "| Datum | Sport | Km |\n|---|---|---|\n| 2026-09-29 | lopen | 10 |"
    call(client, "create_plan", title="Marathon", table=table)
    text, err = call(
        client, "create_plan", title="Advent", table="| Datum | Sport | Km |\n|---|---|---|\n| 2026-12-01 | lopen | 5 |", draft=True
    )
    assert not err and "concept" in text
    assert "Marathon" in call(client, "get_plan")[0]  # the draft did not replace the active plan
    listing = call(client, "list_plans")[0]
    assert "| Advent | concept |" in listing and "| Marathon | actief | 2026-09-29 | 2026-09-29 | 1/1 |" in listing
    draft_id = int(next(line for line in listing.splitlines() if "Advent" in line).split("|")[1])
    assert "2026-12-01" in call(client, "get_plan", plan_id=draft_id)[0]
    assert call(client, "get_plan", plan_id=999)[1] is True

    call(client, "set_plan_status", status="active", plan_id=draft_id)
    assert "| Marathon | afgerond |" in call(client, "list_plans")[0]
    text, err = call(client, "add_achievement", title="Adventskalender voltooid", day="2026-12-24", kind="challenge", body="24/24 runs")
    assert not err and "2026-12-24" in text
    assert call(client, "add_achievement", title="x", kind="fout")[1] is True
    out = call(client, "list_achievements")[0]
    assert out.index("Adventskalender voltooid (challenge)") < out.index("Marathon (schema afgerond")
    assert "1/1 sessies gedaan, 0 gemist, 10.0 van 10.0 km" in out and "24/24 runs" in out


def tool(client, name, args):
    """As call(), for tools with an argument called `name`."""
    res = rpc(client, "tools/call", {"name": name, "arguments": args}).json()["result"]
    return res["content"][0]["text"], res["isError"]


def test_gear_added_set_per_run_cleared_retired_and_removed(client):
    text, err = tool(client, "add_gear", {"name": "Pegasus", "kind": "shoes", "max_km": 600, "default_for": ["run"]})
    assert not err and "| Pegasus | shoes | 10.0 |" in text  # the default reaches the 10 km run in the fixture
    pegasus = int(text.splitlines()[-1].split("|")[1])
    racer = int(tool(client, "add_gear", {"name": "Racer", "kind": "shoes"})[0].splitlines()[-1].split("|")[1])
    aid = call(client, "list_activities", sport="run")[0].splitlines()[2].split("|")[1].strip()
    assert "| Pegasus |" in call(client, "list_activities", sport="run")[0]  # the gear column

    text, err = call(client, "set_activity_gear", activity_ids=[aid], gear_ids=[racer])
    assert not err and f"{aid}: Racer" in text
    assert "Materiaal: Racer" in call(client, "get_activity", id=aid)[0]
    assert f"{aid}: geen materiaal" in call(client, "set_activity_gear", activity_ids=[aid], gear_ids=[])[0]
    assert f"{aid}: Pegasus (automatisch)" in call(client, "set_activity_gear", activity_ids=[aid], automatic=True)[0]
    # nothing changes on a wrong id
    assert call(client, "set_activity_gear", activity_ids=[aid, "bestaat-niet"], gear_ids=[racer])[1] is True
    assert call(client, "set_activity_gear", activity_ids=[aid], gear_ids=[999])[1] is True
    assert call(client, "set_activity_gear", activity_ids=[aid])[1] is True
    assert "Materiaal: Pegasus" in call(client, "get_activity", id=aid)[0]

    text, err = tool(client, "update_gear", {"id": pegasus, "retired_on": "2026-09-01", "name": "Pegasus oud"})
    assert not err and "| Pegasus oud |" in text and "buiten gebruik" in text
    assert "Materiaal:" not in call(client, "get_activity", id=aid)[0]  # retired before the run: no default any more
    assert "| ok |" in call(client, "update_gear", id=pegasus, retired_on="")[0]
    assert call(client, "update_gear", id=pegasus, kind="boot")[1] is True
    assert "verwijderd" in call(client, "delete_gear", id=racer)[0]
    assert call(client, "delete_gear", id=racer)[1] is True
    assert "Racer" not in call(client, "list_gear")[0]


def test_read_tokens_read_and_tokens_end(client, engine):  # noqa: F811
    """A token is read-only unless write is chosen (as in wealth): no write tools, no writes over the API either.
    One with an end date stops working after it."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from tools import db

    client.post("/api/login", json={"username": "alice", "password": "test-wachtwoord-123"})
    made = client.post("/api/agent-tokens", json={"name": "Reader", "expires_days": 30}).json()
    assert made["scope"] == "read" and made["expires_at"]
    listed = client.get("/api/agent-tokens").json()
    assert listed["scopes"] == ["read", "write"] and {t["name"]: t["scope"] for t in listed["tokens"]}["Reader"] == "read"
    agent = TestClient(client.app, headers={"Authorization": f"Bearer {made['token']}"})
    tools = agent.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
    assert tools and all(t["annotations"]["readOnlyHint"] for t in tools)
    assert agent.post("/api/entries", json={}).status_code == 403
    assert agent.get("/api/me").status_code == 200
    assert client.post("/api/agent-tokens", json={"name": "x", "scope": "admin"}).status_code == 422
    assert client.post("/api/agent-tokens", json={"name": "x", "expires_days": 0}).status_code == 422
    with engine.begin() as c:
        c.execute(update(db.agent_tokens).values(expires_at=datetime.now(UTC) - timedelta(days=1)))
    assert agent.get("/api/me").status_code == 401


def test_write_tools_say_what_they_do(client):
    client.post("/api/login", json={"username": "alice", "password": "test-wachtwoord-123"})
    token = client.post("/api/agent-tokens", json={"name": "Writer", "scope": "write"}).json()["token"]
    agent = TestClient(client.app, headers={"Authorization": f"Bearer {token}"})
    tools = {
        t["name"]: t["annotations"]
        for t in agent.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
    }
    assert tools["list_activities"]["readOnlyHint"] and not tools["list_activities"]["destructiveHint"]
    assert not tools["add_log"]["readOnlyHint"] and not tools["add_log"]["destructiveHint"]
    assert tools["delete_gear"]["destructiveHint"] and tools["sync_now"]["openWorldHint"]
