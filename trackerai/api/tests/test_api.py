"""trackerai-api: the account on the front door, its security, and the hub to each tracker's admin API."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app import hub
from app.config import Settings
from app.main import create_app
from trackerai_accounts import Accounts, Config, connect, crypto

PASSWORD = "correct horse battery staple 42"
DOOR = "https://www.trackerai.example"


@pytest.fixture
def accounts(pg_url):
    cfg = Config(
        database_url=pg_url,
        session_secret="s" * 40,
        encryption_key=crypto.new_key(),
        cookie_domain="trackerai.example",
        cookie_secure=False,
        require_totp="off",
    )
    return Accounts(connect(cfg.database_url), cfg, mailer=False)


class Trackers:
    """Stands in for health-tracker's and wealth-tracker's APIs: records what reached them, answers what it is told."""

    def __init__(self):
        self.seen: list[httpx.Request] = []
        self.answer = httpx.Response(200, json={"ok": True}, headers={"cache-control": "no-store", "x-secret": "no"})
        self.down = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("down", request=request)
        self.seen.append(request)
        return self.answer


@pytest.fixture
def trackers():
    return Trackers()


@pytest.fixture
def client(accounts, trackers):
    settings = Settings(
        public_origins=[DOOR],
        trackers={"health": "http://health.internal:8000", "wealth": "http://wealth.internal:8000"},
        cookie_secure=False,
    )
    app = create_app(accounts, settings, hub_transport=httpx.MockTransport(trackers))
    return TestClient(app, base_url=DOOR, headers={"origin": DOOR})


def sign_up(client, name="anna", **kw):
    body = {"username": name, "password": PASSWORD, "email": f"{name}@example.org", "apps": ["wealth"], **kw}
    return client.post("/api/auth/register", json=body)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert r.headers["content-security-policy"].startswith("default-src 'none'")


def test_sign_up_names_the_trackers(client):
    r = sign_up(client, apps=[])
    assert r.status_code == 422 and r.json()["code"] == "unknown_app"
    assert sign_up(client).status_code == 200
    assert client.get("/api/auth/account").json()["username"] == "anna"


def test_login_sets_the_shared_cookie(client):
    sign_up(client)
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"username": "anna", "password": PASSWORD})
    assert r.status_code == 200
    assert "domain=trackerai.example" in r.headers["set-cookie"].lower()


def test_cookie_write_from_another_site_is_refused(client):
    sign_up(client)
    r = client.patch("/api/auth/account", json={"display_name": "Mallory"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_no_oauth_issuer_on_the_front_door(client):
    assert client.get("/.well-known/oauth-authorization-server").status_code == 404


def test_hub_forwards_allowed_paths_with_only_the_listed_headers(client, trackers):
    sign_up(client)
    r = client.post(
        "/api/hub/health/admin/feedback/7?x=1", json={"status": "done"}, headers={"x-locale": "nl", "x-forwarded-for": "1.2.3.4"}
    )
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert r.headers["cache-control"] == "no-store" and "x-secret" not in r.headers
    sent = trackers.seen[-1]
    assert str(sent.url) == "http://health.internal:8000/api/admin/feedback/7?x=1"
    assert sent.method == "POST" and sent.content == b'{"status":"done"}'
    assert sent.headers["origin"] == DOOR and sent.headers["x-locale"] == "nl" and "cookie" in sent.headers
    assert "x-forwarded-for" not in sent.headers


@pytest.mark.parametrize("path", ["admin/accounts", "admin/tracker/%2E%2E/feedback", "feedback/1", "admin/feedback/x"])
def test_hub_refuses_other_paths(client, trackers, path):
    assert client.get(f"/api/hub/wealth/{path}").status_code == 404
    assert trackers.seen == []


def test_hub_unknown_tracker(client):
    assert client.get("/api/hub/stock/admin/tracker").status_code == 404


def test_hub_tracker_without_address(accounts, trackers):
    app = create_app(
        accounts,
        Settings(trackers={"wealth": "http://wealth.internal:8000"}, cookie_secure=False),
        hub_transport=httpx.MockTransport(trackers),
    )
    r = TestClient(app, base_url=DOOR).get("/api/hub/health/admin/tracker")
    assert r.status_code == 503 and r.json()["detail"] == "not_configured"


def test_hub_tracker_down(client, trackers):
    trackers.down = True
    r = client.get("/api/hub/wealth/admin/tracker")
    assert r.status_code == 502 and r.json()["detail"] == "unreachable"


def test_hub_path_rules():
    assert hub.path_allowed("admin/tracker/betas/12")
    assert not hub.path_allowed("admin/tracker/betas/12/")
    assert not hub.path_allowed("admin\\tracker")
    assert not hub.path_allowed("admin/tracker/../feedback")


def test_settings_from_env():
    s = Settings.from_env(
        {
            "PUBLIC_ORIGINS": "https://www.t.nl/, https://t.nl",
            "HEALTH_API_URL": "http://h:8000/",
            "LANDING_WEALTH_URL": "https://wealth.t.nl",
            "COOKIE_SECURE": "false",
        }
    )
    assert s.public_origins == ["https://www.t.nl", "https://t.nl"]
    assert s.trackers == {"health": "http://h:8000", "wealth": "https://wealth.t.nl"}
    assert s.cookie_secure is False


def test_refuses_to_start_without_accounts(monkeypatch):
    for name in ("ACCOUNTS_DATABASE_URL", "ACCOUNTS_SESSION_SECRET", "ACCOUNTS_ENCRYPTION_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="accounts are not set up"):
        create_app(settings=Settings())
