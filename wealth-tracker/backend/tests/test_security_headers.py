"""S5: every API response carries the security headers, errors included."""


def test_api_responses_carry_security_headers(client):
    for r in (client.get("/api/health"), client.get("/api/auth/me"), client.get("/api/nope")):
        h = r.headers
        assert "default-src 'none'" in h["content-security-policy"]
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["x-frame-options"] == "DENY"
        assert h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "strict-origin-when-cross-origin"
        assert h["cross-origin-opener-policy"] == "same-origin"
        assert "geolocation=()" in h["permissions-policy"]


def test_hsts_follows_cookie_secure():
    # The test run sets COOKIE_SECURE=false (plain http), so no HSTS here; in
    # production COOKIE_SECURE defaults to true and HSTS is sent.
    from app.core import config
    from app.main import app

    hsts = [m.kwargs.get("hsts") for m in app.user_middleware if "hsts" in m.kwargs]
    assert hsts == [config.COOKIE_SECURE]


def test_privacy_contact_is_public_and_configurable(client, monkeypatch):
    from app.core import config

    assert client.get("/api/privacy").json()["controller"] is None
    monkeypatch.setattr(config, "PRIVACY_CONTROLLER", "J. Jansen")
    monkeypatch.setattr(config, "PRIVACY_CONTACT", "privacy@example.org")
    r = client.get("/api/privacy").json()
    assert r["controller"] == "J. Jansen" and r["contact"] == "privacy@example.org"


def test_claude_labelling_is_off_until_the_user_turns_it_on(client):
    from domain import database, preferences
    from domain.money import ai_labelling

    assert client.post("/api/auth/login", json={"username": "alice", "password": "alicepw"}).status_code == 200
    conn = database.connect("alice")
    database.init_db(conn)
    assert ai_labelling.on(conn) is False
    preferences.put(conn, "ai_labelling", {"on": True})
    assert ai_labelling.on(conn) is True
    conn.close()
