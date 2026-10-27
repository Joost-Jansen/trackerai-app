"""Feedback: users report, admins read and answer (on the site and through MCP). Nobody sees another user's reports."""

import base64

import pytest
from fastapi.testclient import TestClient

from api import feedback as fb
from tests.test_api import engine  # noqa: F401  (fixture)
from tests.test_multiuser_api import app, as_admin, register  # noqa: F401  (app is a fixture)
from tools import db

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 100).decode()


def send(c, **kw):
    body = {
        "kind": "bug",
        "message": "De grafiek op Trends blijft leeg",
        "page": "/trends/",
        "context": {
            "browser": "Firefox 130",
            "screen": "1440x900",
            "errors": [{"message": "TypeError: x is undefined", "where": "/trends/"}],
        },
    }
    return c.post("/api/feedback", json={**body, **kw})


@pytest.fixture
def anna(app):  # noqa: F811
    as_admin(app).patch("/api/trackerai/admin/registration", json={"registration": "open"})
    c, r = register(app)
    assert r.status_code == 200
    return c


def test_user_sends_and_sees_own_feedback_with_context(anna, monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abcdef1234567")
    r = send(anna, screenshot=PNG)
    assert r.status_code == 201, r.text
    f = r.json()
    assert f["status"] == "new" and f["kind"] == "bug" and f["has_screenshot"]
    assert f["context"]["version"] == "abcdef1" and f["context"]["errors"][0]["message"].startswith("TypeError")
    mine = anna.get("/api/feedback").json()
    assert [x["id"] for x in mine] == [f["id"]]
    shot = anna.get(f"/api/feedback/{f['id']}/screenshot")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/png"


def test_admin_reads_answers_and_user_sees_the_reply(app, anna):  # noqa: F811
    fid = send(anna).json()["id"]
    admin = as_admin(app)
    inbox = admin.get("/api/admin/feedback").json()
    assert inbox[0]["id"] == fid and inbox[0]["username"] == "anna"
    r = admin.patch(f"/api/admin/feedback/{fid}", json={"status": "fixed", "reply": "Opgelost, dank!"})
    assert r.json()["status"] == "fixed"
    mine = anna.get("/api/feedback").json()[0]
    assert mine["status"] == "fixed" and mine["reply"] == "Opgelost, dank!"
    assert admin.get("/api/admin/feedback", params={"status": "new"}).json() == []
    assert admin.patch(f"/api/admin/feedback/{fid}", json={"status": "kapot"}).status_code == 422
    assert admin.patch("/api/admin/feedback/999", json={"status": "fixed"}).status_code == 404


def test_others_see_nothing_of_it(app, anna):  # noqa: F811
    fid = send(anna, screenshot=PNG).json()["id"]
    bob, _ = register(app, username="bob")
    assert bob.get("/api/feedback").json() == []
    assert bob.get(f"/api/feedback/{fid}/screenshot").status_code == 404
    assert bob.get("/api/admin/feedback").status_code == 403
    assert bob.patch(f"/api/admin/feedback/{fid}", json={"status": "fixed"}).status_code == 403
    assert TestClient(app).post("/api/feedback", json={"kind": "bug", "message": "x"}).status_code == 401


def test_bad_input_is_refused(anna):
    assert send(anna, kind="klacht").status_code == 422
    assert send(anna, message="   ").status_code == 422
    assert send(anna, screenshot="data:text/html;base64,PGgxPg==").status_code == 422
    big = "data:image/png;base64," + base64.b64encode(b"0" * (fb.MAX_SCREENSHOT + 1)).decode()
    assert send(anna, screenshot=big).status_code == 413


def test_a_flood_is_stopped(anna, monkeypatch):
    monkeypatch.setattr(fb, "PER_DAY", 2)
    assert send(anna).status_code == 201 and send(anna).status_code == 201
    assert send(anna).status_code == 429


def test_ping_sends_only_kind_and_link(anna, monkeypatch):
    sent = []

    class Thread:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(fb.threading, "Thread", Thread)
    monkeypatch.setattr(
        fb.urllib.request, "urlopen", lambda req, timeout: sent.append(req) or type("R", (), {"close": lambda self: None})()
    )
    monkeypatch.setenv("FEEDBACK_NTFY_URL", "https://ntfy.sh/test-topic")
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "example.up.railway.app")
    fid = send(anna).json()["id"]
    (req,) = sent
    assert req.full_url == "https://ntfy.sh/test-topic"
    assert req.data == f"Feedback #{fid}".encode()  # never the message itself
    assert req.headers["Click"] == "https://example.up.railway.app/settings/feedback/"


def test_deleting_a_user_deletes_their_feedback(app, anna, engine):  # noqa: F811
    send(anna)
    uid = anna.get("/api/me").json()["id"]
    db.delete_user(engine, uid)
    assert db.list_feedback(engine) == []


def test_mcp_feedback_tools_only_for_admins(app, anna):  # noqa: F811
    fid = send(anna).json()["id"]
    admin = as_admin(app)
    token = admin.post("/api/agent-tokens", json={"name": "Claude", "scope": "write"}).json()["token"]
    anna_token = anna.post("/api/agent-tokens", json={"name": "Claude", "scope": "write"}).json()["token"]

    def rpc(tok, method, params=None):
        return (
            TestClient(app)
            .post(
                "/api/mcp",
                headers={"Authorization": f"Bearer {tok}"},
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
            )
            .json()["result"]
        )

    names = {t["name"] for t in rpc(token, "tools/list")["tools"]}
    assert {"list_feedback", "update_feedback"} <= names
    assert not {"list_feedback", "update_feedback"} & {t["name"] for t in rpc(anna_token, "tools/list")["tools"]}

    listed = rpc(token, "tools/call", {"name": "list_feedback", "arguments": {}})
    assert (
        not listed["isError"]
        and "De grafiek op Trends blijft leeg" in listed["content"][0]["text"]
        and "TypeError" in listed["content"][0]["text"]
    )
    done = rpc(
        token, "tools/call", {"name": "update_feedback", "arguments": {"id": fid, "status": "planned", "reply": "Staat op de lijst"}}
    )
    assert not done["isError"]
    assert anna.get("/api/feedback").json()[0]["reply"] == "Staat op de lijst"
    assert rpc(anna_token, "tools/call", {"name": "list_feedback", "arguments": {}})["isError"]
