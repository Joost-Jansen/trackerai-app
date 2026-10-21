"""Real HTTP OAuth flow and failure paths, using disposable accounts only."""

import base64
import hashlib
import json
import secrets
from dataclasses import replace
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from trackerai_accounts import Accounts, Config, connect, crypto, install, make_router
from trackerai_accounts.oauth import OAuth, digest
from trackerai_accounts.service import now
from trackerai_accounts.store import account_apps, oauth_codes, oauth_grants, oauth_tokens
from trackerai_accounts.store import accounts as people

ORIGIN = "https://wealth.example"
RESOURCES = {"wealth": ORIGIN + "/api/mcp", "health": "https://health.example/api/mcp"}
CALLBACK = "https://assistant.example/oauth/callback"


@pytest.fixture
def setup(tmp_path):
    cfg = Config(
        database_url=f"sqlite:///{tmp_path}/accounts.db",
        session_secret=secrets.token_urlsafe(40),
        encryption_key=crypto.new_key(),
        cookie_secure=False,
        require_totp="off",
        oauth_issuer=ORIGIN,
        oauth_resources=json.dumps(RESOURCES),
    )
    accounts = Accounts(connect(cfg.database_url), cfg)
    app = FastAPI()
    install(app)
    router, _ = make_router(accounts, "wealth")
    app.include_router(router)
    owner, host = TestClient(app, base_url=ORIGIN), TestClient(app, base_url=ORIGIN)
    password = secrets.token_urlsafe(32)
    r = owner.post(
        "/api/auth/register",
        json={"username": "sample", "password": password, "email": "sample@example.org", "apps": ["health", "wealth"], "consent": True},
    )
    assert r.status_code == 200
    return accounts, owner, host, password


def client(host, callback=CALLBACK):
    r = host.post("/api/oauth/register", json={"client_name": "Sample assistant", "redirect_uris": [callback]})
    assert r.status_code == 201, r.text
    assert "client_secret" not in r.json()
    return r.json()["client_id"]


def request_flow(owner, host, app="wealth", scopes=None, cid=None, **extra):
    cid = cid or client(host)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    p = {
        "client_id": cid,
        "redirect_uri": CALLBACK,
        "response_type": "code",
        "resource": RESOURCES[app],
        "scope": scopes or f"{app}:read",
        "state": secrets.token_urlsafe(24),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **extra,
    }
    r = host.get("/api/oauth/authorize?" + urlencode(p), follow_redirects=False)
    assert r.status_code == 302, r.text
    nonce = parse_qs(urlsplit(r.headers["location"]).query)["request"][0]
    return p, verifier, nonce


def approve(owner, nonce, **kw):
    return owner.post("/api/oauth/consent", headers={"Origin": ORIGIN}, json={"request": nonce, "allow": True, **kw})


def exchange(host, p, verifier, code):
    return host.post(
        "/api/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": p["client_id"],
            "redirect_uri": p["redirect_uri"],
            "resource": p["resource"],
            "code_verifier": verifier,
            "code": code,
        },
    )


def access(setup, app="wealth", write=False):
    accounts, owner, host, _ = setup
    p, verifier, nonce = request_flow(owner, host, app, scopes=f"{app}:read {app}:write")
    consent = owner.get("/api/oauth/consent", params={"request": nonce})
    assert consent.status_code == 200, consent.text
    r = approve(owner, nonce, write=write, health_consent=app == "health")
    assert r.status_code == 200, r.text
    redirect = parse_qs(urlsplit(r.json()["redirect"]).query)
    assert redirect["state"] == [p["state"]]
    token = exchange(host, p, verifier, redirect["code"][0])
    assert token.status_code == 200, token.text
    return p, verifier, redirect["code"][0], token.json()


def test_discovery_and_default_read_only(setup):
    accounts, owner, host, _ = setup
    m = host.get("/.well-known/oauth-authorization-server").json()
    assert m["issuer"] == ORIGIN and m["code_challenge_methods_supported"] == ["S256"]
    resource = host.get("/.well-known/oauth-protected-resource/api/mcp").json()
    assert resource["resource"] == RESOURCES["wealth"] and resource["authorization_servers"] == [ORIGIN]
    assert "resource_metadata=" in OAuth(accounts).challenge("health")["WWW-Authenticate"]
    _, _, _, token = access(setup)
    assert token["scope"] == "wealth:read" and token["expires_in"] == 3600
    found = OAuth(accounts).resolve(token["access_token"], "wealth")
    assert found["account"]["username"] == "sample" and found["scope"] == "read"
    assert OAuth(accounts).resolve(token["access_token"], "health") is None
    listed = owner.get("/api/account/agent-connections").json()["connections"]
    assert len(listed) == 1 and listed[0]["last_used_at"] and listed[0]["scope"] == "read"
    with accounts.engine.connect() as c:
        stored = str(c.execute(select(oauth_tokens)).all()) + str(c.execute(select(oauth_codes)).all())
    assert token["access_token"] not in stored and token["refresh_token"] not in stored


def test_health_explicit_consent_and_no_implicit_app_join(setup):
    accounts, owner, host, _ = setup
    p, verifier, nonce = request_flow(owner, host, "health")
    assert approve(owner, nonce).status_code == 403
    assert approve(owner, nonce, health_consent=True).status_code == 200
    account = accounts.by_username("sample")
    accounts.leave_app(account["id"], "health")
    _, _, nonce = request_flow(owner, host, "health")
    assert owner.get("/api/oauth/consent", params={"request": nonce}).status_code == 403
    assert approve(owner, nonce, health_consent=True).status_code == 403


def test_write_requires_request_and_opt_in(setup):
    accounts, owner, host, _ = setup
    _, _, _, token = access(setup, "health", write=True)
    assert OAuth(accounts).resolve(token["access_token"], "health")["scope"] == "write"
    _, _, nonce = request_flow(owner, host)
    assert approve(owner, nonce, write=True).json()["error"] == "invalid_scope"


@pytest.mark.parametrize(
    "mutation",
    [
        {"code_challenge_method": "plain"},
        {"code_challenge": ""},
        {"resource": "https://evil.example/api/mcp"},
        {"redirect_uri": "https://evil.example/callback"},
        {"scope": "health:read"},
        {"state": ""},
        {"response_type": "token"},
    ],
)
def test_invalid_authorization_never_redirects(setup, mutation):
    _, _, host, _ = setup
    cid = client(host)
    p = dict(
        client_id=cid,
        redirect_uri=CALLBACK,
        response_type="code",
        resource=RESOURCES["wealth"],
        scope="wealth:read",
        state="state",
        code_challenge=secrets.token_urlsafe(32),
        code_challenge_method="S256",
    )
    p.update(mutation)
    r = host.get("/api/oauth/authorize", params=p, follow_redirects=False)
    assert r.status_code == 400 and "location" not in r.headers


@pytest.mark.parametrize(
    "callback",
    [
        "http://evil.example/cb",
        "javascript:alert(1)",
        "https://x.example/cb#frag",
        "https://u:p@x.example/cb",
        "https://x.example\\@evil.example/cb",
    ],
)
def test_bad_client_callbacks(setup, callback):
    _, _, host, _ = setup
    r = host.post("/api/oauth/register", json={"redirect_uris": [callback]})
    assert r.status_code == 400


def test_loopback_public_client_supported(setup):
    _, _, host, _ = setup
    assert client(host, "http://127.0.0.1:3210/callback")


def test_pkce_resource_client_and_redirect_binding(setup):
    _, owner, host, _ = setup
    p, verifier, nonce = request_flow(owner, host)
    redirect = approve(owner, nonce).json()["redirect"]
    code = parse_qs(urlsplit(redirect).query)["code"][0]
    assert exchange(host, p, secrets.token_urlsafe(48), code).status_code == 400
    for key, value in [("resource", RESOURCES["health"]), ("redirect_uri", "https://evil.example/cb"), ("client_id", client(host))]:
        assert exchange(host, {**p, key: value}, verifier, code).status_code == 400
    assert exchange(host, p, verifier, code).status_code == 200
    assert exchange(host, p, verifier, code).status_code == 400


def test_consent_login_csrf_binding_cancel_and_replay(setup):
    accounts, owner, host, _ = setup
    p, _, nonce = request_flow(owner, host)
    assert host.get("/api/oauth/consent", params={"request": nonce}).status_code == 401
    assert owner.get("/api/oauth/consent", params={"request": nonce}).status_code == 200
    for origin in (None, "https://evil.example"):
        r = owner.post("/api/oauth/consent", json={"request": nonce, "allow": True}, headers={"Origin": origin} if origin else {})
        assert r.status_code == 403
    r = owner.post("/api/oauth/consent", json={"request": nonce, "allow": False}, headers={"Origin": ORIGIN})
    q = parse_qs(urlsplit(r.json()["redirect"]).query)
    assert q == {"error": ["access_denied"], "state": [p["state"]]}
    assert approve(owner, nonce).status_code == 400
    with accounts.engine.connect() as c:
        assert not c.execute(select(oauth_grants)).all()


def test_request_is_bound_to_account(setup):
    accounts, owner, host, _ = setup
    _, _, nonce = request_flow(owner, host)
    assert owner.get("/api/oauth/consent", params={"request": nonce}).status_code == 200
    accounts.set_registration_mode(accounts.by_username("sample"), "open")
    host.post("/api/auth/register", json={"username": "other", "password": secrets.token_urlsafe(32), "email": "other@example.org"})
    assert host.get("/api/oauth/consent", params={"request": nonce}).status_code == 400
    assert approve(host, nonce).status_code == 400


def test_refresh_rotation_and_replay_revokes_family(setup):
    accounts, _, host, _ = setup
    p, _, _, token = access(setup)
    data = {"grant_type": "refresh_token", "client_id": p["client_id"], "resource": p["resource"], "refresh_token": token["refresh_token"]}
    wrong = host.post("/api/oauth/token", data={**data, "resource": RESOURCES["health"]})
    assert wrong.status_code == 400
    raised = host.post("/api/oauth/token", data={**data, "scope": "wealth:read wealth:write"})
    assert raised.status_code == 400
    r = host.post("/api/oauth/token", data=data)
    assert r.status_code == 200, r.text
    rotated = r.json()
    assert rotated["refresh_token"] != token["refresh_token"]
    assert OAuth(accounts).resolve(token["access_token"], "wealth") is None
    assert OAuth(accounts).resolve(rotated["access_token"], "wealth")
    assert host.post("/api/oauth/token", data=data).status_code == 400
    assert OAuth(accounts).resolve(rotated["access_token"], "wealth") is None


@pytest.mark.parametrize("change", ["password", "suspend", "leave", "unconfirmed_health"])
def test_account_changes_end_access(setup, change):
    accounts, _, host, password = setup
    p, _, _, token = access(setup, "health")
    account = accounts.by_username("sample")
    if change == "password":
        accounts.change_password(account["id"], password, secrets.token_urlsafe(32))
    elif change == "suspend":
        with accounts.engine.begin() as c:
            c.execute(update(people).where(people.c.id == account["id"]).values(suspended=True))
    elif change == "leave":
        accounts.leave_app(account["id"], "health")
    else:
        with accounts.engine.begin() as c:
            c.execute(
                update(account_apps)
                .where(account_apps.c.account_id == account["id"], account_apps.c.app == "health")
                .values(consent_at=None)
            )
    assert OAuth(accounts).resolve(token["access_token"], "health") is None
    assert (
        host.post(
            "/api/oauth/token",
            data={
                "grant_type": "refresh_token",
                "client_id": p["client_id"],
                "resource": p["resource"],
                "refresh_token": token["refresh_token"],
            },
        ).status_code
        == 400
    )


def test_two_step_required_before_consent_and_after_policy_change(setup):
    accounts, owner, host, _ = setup
    _, _, _, token = access(setup)
    accounts.config = replace(accounts.config, require_totp="all")
    _, _, nonce = request_flow(owner, host)
    assert owner.get("/api/oauth/consent", params={"request": nonce}).json()["code"] == "totp_setup_required"
    assert approve(owner, nonce).status_code == 403
    assert OAuth(accounts).resolve(token["access_token"], "wealth") is None


def test_disconnect_from_either_app_and_only_owned_connection(setup):
    accounts, owner, _, _ = setup
    _, _, _, token = access(setup, "health")
    grant = OAuth(accounts).resolve(token["access_token"], "health")["id"]
    assert owner.delete("/api/account/agent-connections/" + grant).status_code == 403
    assert owner.delete("/api/account/agent-connections/" + grant, headers={"Origin": ORIGIN}).status_code == 200
    assert OAuth(accounts).resolve(token["access_token"], "health") is None


def test_expiry_duplicate_parameters_and_disabled(setup):
    accounts, owner, host, _ = setup
    p, _, nonce = request_flow(owner, host)
    duplicate = host.get("/api/oauth/authorize?" + urlencode(p) + "&resource=" + RESOURCES["wealth"], follow_redirects=False)
    assert duplicate.status_code == 400
    r = approve(owner, nonce)
    code = parse_qs(urlsplit(r.json()["redirect"]).query)["code"][0]
    with accounts.engine.begin() as c:
        c.execute(update(oauth_codes).where(oauth_codes.c.digest == digest(code)).values(expires_at=now() - timedelta(seconds=1)))
    assert exchange(host, p, secrets.token_urlsafe(48), code).status_code == 400
    accounts.config = replace(accounts.config, oauth_issuer="")
    assert host.get("/.well-known/oauth-authorization-server").status_code == 404
    assert owner.get("/api/account/agent-connections").json()["enabled"] is False


def test_debug_logs_cannot_expose_protocol_credentials(setup, caplog):
    import logging

    caplog.set_level(logging.DEBUG, logger="oauthlib")
    _, _, _, token = access(setup)
    assert token["access_token"] not in caplog.text and token["refresh_token"] not in caplog.text
    assert not any(r.name.startswith("oauthlib") and r.levelno < logging.WARNING for r in caplog.records)


def test_private_consent_and_connections_are_not_cached(setup):
    _, owner, host, _ = setup
    _, _, nonce = request_flow(owner, host)
    for path in ["/api/oauth/consent?request=" + nonce, "/api/account/agent-connections"]:
        assert owner.get(path).headers["cache-control"] == "no-store"
