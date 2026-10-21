"""
Feedback: users report, the admin reads and replies (in the app and through
MCP). Nobody sees someone else's reports; the push only says *that* there is
something.
"""

import base64

from fastapi.testclient import TestClient

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 100).decode()


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _admin(name="alice"):
    from app.core import auth_store

    with auth_store._locked_update() as cfg:
        cfg["admins"] = [name]


def _send(client, **kw):
    body = {
        "kind": "bug",
        "message": "De budgetgrafiek blijft leeg",
        "page": "/budget",
        "app": "money",
        "context": {"browser": "Firefox 130", "screen": "1440x900", "errors": [{"message": "500 internal", "where": "GET /api/budget"}]},
    }
    return client.post("/api/feedback", json={**body, **kw})


def test_user_sends_and_sees_own_feedback(client, monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abcdef1234567")
    _login(client, "bob", "bobpw")
    r = _send(client, screenshot=PNG)
    assert r.status_code == 201, r.text
    f = r.json()
    assert f["status"] == "new" and f["app"] == "wealth" and f["has_screenshot"]
    assert f["context"]["version"] == "abcdef1" and f["context"]["errors"][0]["where"] == "GET /api/budget"
    assert [x["id"] for x in client.get("/api/feedback").json()["feedback"]] == [f["id"]]
    shot = client.get(f"/api/feedback/{f['id']}/screenshot")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/png"


def test_admin_answers_and_user_sees_it(client):
    _admin()
    _login(client, "bob", "bobpw")
    fid = _send(client).json()["id"]
    _login(client)
    inbox = client.get("/api/admin/feedback").json()["feedback"]
    assert inbox[0]["id"] == fid and inbox[0]["username"] == "bob"
    r = client.patch(f"/api/admin/feedback/{fid}", json={"status": "fixed", "reply": "Opgelost, dank!"})
    assert r.status_code == 200 and r.json()["status"] == "fixed"
    assert client.get("/api/admin/feedback", params={"status": "new"}).json()["feedback"] == []
    assert client.patch(f"/api/admin/feedback/{fid}", json={"status": "broken"}).status_code == 422
    assert client.patch("/api/admin/feedback/999", json={"status": "fixed"}).status_code == 404
    _login(client, "bob", "bobpw")
    mine = client.get("/api/feedback").json()["feedback"][0]
    assert mine["status"] == "fixed" and mine["reply"] == "Opgelost, dank!"


def test_others_see_nothing_of_it(client):
    _login(client, "bob", "bobpw")
    fid = _send(client, screenshot=PNG).json()["id"]
    _login(client)  # alice, no admin
    assert client.get("/api/feedback").json()["feedback"] == []
    assert client.get(f"/api/feedback/{fid}/screenshot").status_code == 404
    assert client.get("/api/admin/feedback").status_code == 403
    assert client.patch(f"/api/admin/feedback/{fid}", json={"status": "fixed"}).status_code == 403
    from app.main import app

    assert TestClient(app).post("/api/feedback", json={"kind": "bug", "message": "x"}).status_code == 401


def test_bad_input_and_a_flood_are_refused(client, monkeypatch):
    from app.routers import feedback as fb

    _login(client)
    assert _send(client, kind="klacht").status_code == 422
    assert _send(client, message="   ").status_code == 422
    assert _send(client, screenshot="data:text/html;base64,PGgxPg==").status_code == 422
    big = "data:image/png;base64," + base64.b64encode(b"0" * (fb.MAX_SCREENSHOT + 1)).decode()
    assert _send(client, screenshot=big).status_code == 413
    monkeypatch.setattr(fb, "PER_DAY", 1)
    assert _send(client).status_code == 201
    assert _send(client).status_code == 429


def test_push_says_only_that_something_came_in(client, monkeypatch):
    from app.core import notify

    sent = []
    monkeypatch.setattr(notify, "push", lambda title, message, **kw: sent.append((title, message)) or True)
    _login(client)
    fid = _send(client).json()["id"]
    assert sent == [("wealth-tracker: iets kapot", f"Feedback #{fid}")]


def test_an_agent_token_cannot_send_feedback(client):
    _login(client)
    token = client.post("/api/agent-tokens", json={"name": "Claude", "scope": "write"}).json()["token"]
    from app.main import app

    agent = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    assert _send(agent).status_code == 403
    assert agent.get("/api/admin/feedback").status_code == 403


def test_deleting_an_account_deletes_its_feedback(client):
    from app.core import feedback_store

    _admin()
    _login(client, "bob", "bobpw")
    _send(client)
    _login(client)
    from app.core.accounts import accounts, purge

    bob = accounts.by_username("bob")["id"]
    assert client.delete(f"/api/trackerai/admin/accounts/{bob}", params={"confirm": "bob"}).status_code == 200
    purge()
    assert feedback_store.list_() == []


def test_mcp_feedback_tools_only_for_an_admins_token(client):
    from app.main import app

    _admin()
    _login(client, "bob", "bobpw")
    fid = _send(client).json()["id"]
    bob_token = client.post("/api/agent-tokens", json={"name": "Claude", "scope": "write"}).json()["token"]
    _login(client)
    read = client.post("/api/agent-tokens", json={"name": "Claude", "scope": "read"}).json()["token"]
    write = client.post("/api/agent-tokens", json={"name": "Claude", "scope": "write"}).json()["token"]

    def rpc(token, method, params=None):
        r = TestClient(app).post(f"/api/mcp/{token}", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
        return r.json()["result"]

    names = lambda tok: {t["name"] for t in rpc(tok, "tools/list")["tools"]}  # noqa: E731
    assert {"list_feedback", "update_feedback"} <= names(read)
    assert not {"list_feedback", "update_feedback"} & names(bob_token)

    listed = rpc(read, "tools/call", {"name": "list_feedback", "arguments": {}})
    assert not listed["isError"] and "De budgetgrafiek blijft leeg" in listed["content"][0]["text"]
    assert rpc(read, "tools/call", {"name": "update_feedback", "arguments": {"id": fid, "status": "fixed"}})["isError"]
    assert rpc(bob_token, "tools/call", {"name": "list_feedback", "arguments": {}})["isError"]

    done = rpc(
        write, "tools/call", {"name": "update_feedback", "arguments": {"id": fid, "status": "planned", "reply": "Staat op de lijst"}}
    )
    assert not done["isError"], done
    _login(client, "bob", "bobpw")
    assert client.get("/api/feedback").json()["feedback"][0]["reply"] == "Staat op de lijst"
