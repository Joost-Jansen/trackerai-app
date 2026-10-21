"""S6: cookie-authenticated writes must come from this site."""

from fastapi.testclient import TestClient


def _logged_in(client):
    assert client.post("/api/auth/login", json={"username": "alice", "password": "alicepw"}).status_code == 200
    return client


def test_cross_site_write_with_the_cookie_is_refused(client):
    _logged_in(client)
    r = client.put("/api/auth/me/locale", json={"locale": "en"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["code"] == "csrf_origin"
    # The security headers are on the refusal too.
    assert r.headers["x-frame-options"] == "DENY"


def test_multipart_upload_from_another_site_is_refused(client):
    _logged_in(client)
    r = client.post("/api/uploads/bank", files={"files": ("x.csv", b"a,b\n", "text/csv")}, headers={"Origin": "https://health.example.org"})
    assert r.status_code == 403


def test_same_origin_and_referer_pass(client):
    _logged_in(client)
    assert client.put("/api/auth/me/locale", json={"locale": "en"}).status_code == 200
    r = client.put("/api/auth/me/locale", json={"locale": "nl"}, headers={"Origin": "", "Referer": "http://testserver/account"})
    assert r.status_code == 200


def test_no_origin_and_no_referer_is_refused(client):
    from app.main import app

    _logged_in(client)
    bare = TestClient(app)
    bare.cookies.update(client.cookies)
    assert bare.put("/api/auth/me/locale", json={"locale": "en"}).status_code == 403
    # Reading stays possible.
    assert bare.get("/api/auth/me").status_code == 200


def test_public_origins_are_allowed(client, monkeypatch):
    from app.main import app
    from trackerai_websec.csrf import OriginCheckMiddleware

    _logged_in(client)
    # The middleware read PUBLIC_ORIGINS at startup; check the class with it directly.
    mw = OriginCheckMiddleware(app, ["https://stocks.example.org"], "stocktracker_session")
    hdrs = {"cookie": "stocktracker_session=x", "host": "api:8000"}
    assert mw.allowed_request("POST", "/api/x", {**hdrs, "origin": "https://stocks.example.org"})
    assert not mw.allowed_request("POST", "/api/x", {**hdrs, "origin": "https://evil.example"})


def test_the_front_door_at_the_cookie_domain_may_post():
    """trackerai.nl logs in with the shared account: its logout must pass, a look-alike must not."""
    from trackerai_accounts.config import front_door_origins
    from trackerai_websec.csrf import OriginCheckMiddleware

    assert front_door_origins("") == []
    origins = front_door_origins(".TrackerAI.nl")
    assert origins == ["https://trackerai.nl", "https://www.trackerai.nl"]
    mw = OriginCheckMiddleware(None, origins, "trackerai_session")
    hdrs = {"cookie": "trackerai_session=x", "host": "api:8000"}
    assert mw.allowed_request("POST", "/api/auth/logout", {**hdrs, "origin": "https://www.trackerai.nl"})
    assert mw.allowed_request("POST", "/api/auth/logout", {**hdrs, "origin": "https://trackerai.nl"})
    assert not mw.allowed_request("POST", "/api/auth/logout", {**hdrs, "origin": "https://trackerai.nl.evil.example"})
    assert not mw.allowed_request("POST", "/api/auth/logout", {**hdrs, "origin": "http://trackerai.nl"})


def test_bearer_agents_are_exempt(client):
    from app.core import auth_store
    from app.main import app

    token = auth_store.create_agent_token("alice", "t", "write")["token"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token}", "Origin": "https://elsewhere.example"})
    r = agent.put("/api/month-periods", json={"mode": "calendar"})
    assert r.status_code != 403, r.text
