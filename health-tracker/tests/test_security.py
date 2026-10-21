"""App-level security: headers, the CSRF origin check, body limits, log redaction (api/main.py; the building blocks
are tested in packages/websec/tests, the pages' policy is web/proxy.ts)."""

from fastapi.testclient import TestClient

from api.main import create_app
from tests.test_api import PASSWORD, client, engine, login, make_settings  # noqa: F401  (fixtures)


def test_api_responses_carry_security_headers(client):  # noqa: F811
    r = client.get("/api/health")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"].startswith("default-src 'none'")
    assert "strict-transport-security" not in r.headers  # make_settings: cookie_secure=False, plain http
    assert client.get("/api/me").headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_hsts_when_served_over_https(engine, tmp_path):  # noqa: F811
    settings = make_settings()
    settings.cookie_secure = True
    c = TestClient(create_app(engine=engine, settings=settings))
    assert "max-age" in c.get("/api/health").headers["strict-transport-security"]


def test_cross_site_writes_are_refused(client):  # noqa: F811
    login(client)
    evil = {"Origin": "https://evil.example"}
    r = client.post("/api/entries", json={"kind": "log", "title": "t", "body": "b"}, headers=evil)
    assert r.status_code == 403 and r.json()["code"] == "csrf_origin"
    assert client.post("/api/login", json={"username": "alice", "password": PASSWORD}, headers=evil).status_code == 403
    own = {"Origin": "http://testserver"}
    assert client.post("/api/entries", json={"kind": "log", "title": "t", "body": "b"}, headers=own).status_code == 200
    assert client.get("/api/entries", headers=evil).status_code == 200  # reads are not state-changing


def test_public_origins_are_allowed(engine, tmp_path):  # noqa: F811
    c = TestClient(create_app(engine=engine, settings=make_settings(public_origins=("https://health.example.org",))))
    login(c)
    assert (
        c.post(
            "/api/entries", json={"kind": "log", "title": "t", "body": "b"}, headers={"Origin": "https://health.example.org"}
        ).status_code
        == 200
    )


def test_oversized_json_body_is_refused_before_it_is_read(client):  # noqa: F811
    login(client)
    r = client.post("/api/entries", content=b"{" + b" " * (7 * 1024 * 1024) + b"}", headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["code"] == "upload_too_large"
    assert r.headers["x-frame-options"] == "DENY"


def test_fit_zip_bomb_is_refused(client):  # noqa: F811
    import io
    import zipfile

    login(client)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bomb.fit", b"\0" * (150 * 1024 * 1024))
    r = client.post("/api/activities/upload", content=buf.getvalue(), headers={"content-type": "application/octet-stream"})
    assert r.status_code == 422 and r.json()["code"] == "fit_unreadable"


def test_overlong_fields_are_a_422_not_a_database_error(client):  # noqa: F811
    login(client)
    assert client.post("/api/entries", json={"kind": "log", "title": "t" * 201, "body": "b"}).status_code == 422
    assert client.post("/api/plans", json={"title": "t" * 201, "sessions": []}).status_code == 422
    assert (
        client.post("/api/plans", json={"title": "ok", "sessions": [{"date": "2026-10-04", "sport": "run", "kind": "k" * 61}]}).status_code
        == 422
    )


def test_garmin_logins_through_the_server_are_limited(engine, tmp_path):  # noqa: F811
    from api.connections import GarminLoginError

    class Refuses:
        def start(self, email, password):
            raise GarminLoginError("garmin_rejected")

    c = TestClient(create_app(engine=engine, settings=make_settings(), garmin_auth=Refuses()))
    login(c)
    codes = [c.post("/api/connections/garmin", json={"email": "x@example.org", "password": f"guess{i}"}).status_code for i in range(11)]
    assert codes[:10] == [400] * 10 and codes[10] == 429
