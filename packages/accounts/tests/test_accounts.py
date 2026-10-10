import json
import time
from dataclasses import replace

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from trackerai_accounts import Accounts, Config, Session, connect, crypto, install, make_router, session, totp
from trackerai_accounts.service import hash_password
from trackerai_accounts.store import accounts as accounts_table

PASSWORD = "a long enough passphrase"


def config(tmp_path, **kw) -> Config:
    base = dict(database_url=f"sqlite:///{tmp_path}/accounts.db", session_secret="s" * 40, encryption_key=crypto.new_key(),
                cookie_domain=None, cookie_secure=False)
    return Config(**{**base, **kw})


def make_app(accounts: Accounts, app: str | None) -> FastAPI:
    api = FastAPI()
    install(api)
    router, sessions = make_router(accounts, app)
    api.include_router(router)

    @api.get("/api/data")
    def data(s: Session = Depends(sessions.ready)):
        return {"account": s.username, "apps": sorted(s.apps)}

    return api


@pytest.fixture
def accounts(tmp_path):
    cfg = config(tmp_path)
    return Accounts(connect(cfg.database_url), cfg)


@pytest.fixture
def health(accounts):
    return TestClient(make_app(accounts, "health"), base_url="https://health.example")


@pytest.fixture
def wealth(accounts):
    return TestClient(make_app(accounts, "wealth"), base_url="https://wealth.example")


def register(client, name="anna", **kw):
    body = {"username": name, "password": PASSWORD, "consent": True, "email": f"{name}@example.org", **kw}
    return client.post("/api/auth/register", json=body)


def code_for(accounts, name, offset=0):
    row = accounts.by_username(name)
    secret = crypto.decrypt(row["totp_secret"], accounts.config.encryption_key)
    return totp.code_at(secret, time.time() + offset)


def enable_totp(client, accounts, name="anna"):
    secret = client.post("/api/account/totp/setup").json()["secret"]
    codes = client.post("/api/account/totp/enable", json={"code": totp.code_at(secret)}).json()["backup_codes"]
    return secret, codes


def test_first_account_is_admin_and_registration_then_closes(health, accounts):
    r = register(health)
    assert r.status_code == 200 and r.json()["is_admin"] is True
    assert accounts.registration_mode() == "closed"
    assert register(TestClient(health.app), "bob").json()["code"] == "registration_closed"


def test_health_needs_consent(health):
    r = register(health, consent=False)
    assert r.status_code == 422 and r.json()["code"] == "consent_required"


def test_one_login_for_both_apps(accounts, health, wealth):
    register(health)
    accounts.set_registration_mode(accounts.by_username("anna"), "open")
    bob = TestClient(wealth.app, base_url="https://wealth.example")
    assert register(bob, "bob", consent=False).status_code == 200  # wealth asks no health consent
    # the cookie from one app is a session in the other (same secret, same database)
    token = bob.cookies.get(session.COOKIE)
    other = TestClient(health.app, base_url="https://health.example", cookies={session.COOKIE: token})
    me = other.get("/api/auth/account").json()
    assert me["username"] == "bob" and me["apps"] == ["wealth"]


def test_cookie_on_the_shared_domain(tmp_path):
    cfg = config(tmp_path, cookie_domain="trackerai.nl", cookie_secure=True)
    accounts = Accounts(connect(cfg.database_url), cfg)
    client = TestClient(make_app(accounts, "wealth"), base_url="https://wealth.trackerai.nl")
    r = register(client)
    header = r.headers["set-cookie"].lower()
    assert "domain=trackerai.nl" in header and "httponly" in header and "secure" in header and "samesite=lax" in header


def test_login_and_wrong_password(health, accounts):
    register(health)
    c = TestClient(health.app)
    assert c.post("/api/auth/login", json={"username": "Anna", "password": "wrong one"}).json()["code"] == "bad_credentials"
    r = c.post("/api/auth/login", json={"username": "Anna", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["username"] == "anna"
    assert c.get("/api/auth/account").json()["username"] == "anna"


def test_failed_logins_are_counted_in_the_database(accounts, health):
    register(health)
    for _ in range(10):
        accounts._failed(accounts.by_username("anna"))
    # another app (another process) sees the same count
    c = TestClient(make_app(accounts, "wealth"))
    r = c.post("/api/auth/login", json={"username": "anna", "password": PASSWORD})
    assert r.status_code == 429 and r.json()["code"] == "too_many_attempts"


def test_two_step_login(health, accounts):
    register(health)
    secret, backup = enable_totp(health, accounts)
    c = TestClient(health.app)
    assert c.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}).json()["code"] == "totp_required"
    assert c.post("/api/auth/login", json={"username": "anna", "password": PASSWORD, "totp": "000000"}).json()["code"] == "totp_invalid"
    code = totp.code_at(secret, time.time() + 30)
    assert c.post("/api/auth/login", json={"username": "anna", "password": PASSWORD, "totp": code}).status_code == 200
    # a code is good once
    again = TestClient(health.app)
    assert again.post("/api/auth/login", json={"username": "anna", "password": PASSWORD, "totp": code}).json()["code"] == "totp_invalid"
    # a backup code once too
    assert again.post("/api/auth/login", json={"username": "anna", "password": PASSWORD, "totp": backup[0]}).status_code == 200
    third = TestClient(health.app)
    assert third.post("/api/auth/login", json={"username": "anna", "password": PASSWORD, "totp": backup[0]}).json()["code"] == "totp_invalid"


def test_enabling_two_step_login_ends_other_sessions(health, accounts):
    register(health)
    other = TestClient(health.app)
    other.post("/api/auth/login", json={"username": "anna", "password": PASSWORD})
    enable_totp(health, accounts)
    assert other.get("/api/auth/account").status_code == 401
    assert health.get("/api/auth/account").status_code == 200  # this browser got a new cookie


def test_password_change_ends_other_sessions_in_every_app(health, wealth, accounts):
    register(health)
    elsewhere = TestClient(wealth.app, cookies={session.COOKIE: health.cookies.get(session.COOKIE)})
    assert elsewhere.get("/api/auth/account").status_code == 200
    assert health.post("/api/account/password", json={"current": PASSWORD, "new": "another long passphrase"}).status_code == 200
    assert elsewhere.get("/api/auth/account").status_code == 401
    assert health.get("/api/auth/account").status_code == 200


def test_password_policy(health):
    assert register(health, password="short").json()["code"] == "password_too_short"
    assert register(health, "annabelle1", password="annabelle1").json()["code"] == "password_is_username"
    assert register(health, password="aaaaaaaaaaaa").json()["code"] == "password_too_common"


def test_two_step_login_required_once_both_apps_are_used(health, accounts):
    register(health)  # the first account is admin: required at once under "shared"
    r = health.get("/api/data")
    assert r.status_code == 403 and r.json()["code"] == "totp_setup_required"
    assert health.get("/api/auth/account").json()["totp_setup_required"] is True
    enable_totp(health, accounts)
    assert health.get("/api/data").status_code == 200


def test_shared_policy_for_a_normal_account(accounts, health):
    register(health)
    accounts.set_registration_mode(accounts.by_username("anna"), "open")
    bob = TestClient(health.app)
    register(bob, "bob")
    assert bob.get("/api/data").json() == {"account": "bob", "apps": ["health"]}  # one app: not required
    assert bob.post("/api/account/apps/wealth", json={}).status_code == 200
    r = bob.get("/api/data")
    assert r.status_code == 403 and r.json()["code"] == "totp_setup_required"
    enable_totp(bob, accounts, "bob")
    assert bob.get("/api/data").json()["apps"] == ["health", "wealth"]
    # switched off while required (a new phone): nothing opens until it is set up again
    code = code_for(accounts, "bob", 30)
    assert bob.post("/api/account/totp/disable", json={"password": PASSWORD, "code": code}).status_code == 200
    assert bob.get("/api/data").json()["code"] == "totp_setup_required"


def test_policy_off_and_all(tmp_path):
    for policy, expected in (("off", 200), ("all", 403)):
        cfg = config(tmp_path / policy, require_totp=policy)
        (tmp_path / policy).mkdir()
        accounts = Accounts(connect(cfg.database_url), cfg)
        c = TestClient(make_app(accounts, "wealth"))
        register(c)
        assert c.get("/api/data").status_code == expected


def test_joining_needs_an_open_installation_or_the_admin(accounts, health):
    register(health)
    accounts.set_registration_mode(accounts.by_username("anna"), "open")
    bob = TestClient(health.app)
    register(bob, "bob")
    accounts.set_registration_mode(accounts.by_username("anna"), "invite")
    r = bob.post("/api/account/apps/wealth", json={})
    assert r.status_code == 403 and r.json()["code"] == "app_not_available"
    accounts.set_app(accounts.by_username("anna"), accounts.by_username("bob")["id"], "wealth", enabled=True)
    assert accounts.apps(accounts.by_username("bob")["id"]).keys() == {"health", "wealth"}


def test_invite_opens_its_apps(accounts, health):
    register(health)
    anna = accounts.by_username("anna")
    accounts.set_registration_mode(anna, "invite")
    invite = accounts.create_invite(anna, 7, ["wealth"])
    c = TestClient(make_app(accounts, "health"))
    assert register(c, "carl", invite="nope").json()["code"] == "invalid_invite"
    assert register(c, "carl", invite=invite["code"]).status_code == 200
    assert sorted(accounts.apps(accounts.by_username("carl")["id"])) == ["health", "wealth"]
    assert register(TestClient(health.app), "dora", invite=invite["code"]).json()["code"] == "invalid_invite"


def test_leaving_an_app_and_the_purge(accounts, health):
    register(health)
    anna = accounts.by_username("anna")
    accounts.set_registration_mode(anna, "open")
    bob = TestClient(health.app)
    register(bob, "bob")
    bid = accounts.by_username("bob")["id"]
    accounts.set_local_key(bid, "health", "42")
    assert accounts.account_for_local_key("health", "42")["username"] == "bob"
    assert bob.request("DELETE", "/api/account/apps/health", json={"password": "wrong passphrase"}).json()["code"] == "wrong_current_password"
    assert bob.request("DELETE", "/api/account/apps/health", json={"password": PASSWORD}).status_code == 200
    assert accounts.pending_purges("health") == [{"account_id": bid, "local_key": "42"}]
    assert accounts.account_for_local_key("health", "42") is None
    accounts.purged(bid, "health")
    assert accounts.pending_purges("health") == [] and accounts.get(bid)  # the account itself stays


def test_deleting_the_account_in_every_app(accounts, health):
    register(health)
    accounts.set_registration_mode(accounts.by_username("anna"), "open")
    bob = TestClient(health.app)
    register(bob, "bob")
    bid = accounts.by_username("bob")["id"]
    accounts.set_app(accounts.by_username("anna"), bid, "wealth", enabled=True)
    enable_totp(bob, accounts, "bob")
    code = code_for(accounts, "bob", 30)
    assert bob.request("DELETE", "/api/account", json={"password": PASSWORD, "totp": code}).status_code == 200
    assert bob.get("/api/auth/account").status_code == 401
    assert TestClient(health.app).post("/api/auth/login", json={"username": "bob", "password": PASSWORD}).json()["code"] == "bad_credentials"
    assert {p["account_id"] for p in accounts.pending_purges("health")} == {bid}
    accounts.purged(bid, "health")
    assert accounts.get(bid) is not None  # wealth still has to delete its part
    accounts.purged(bid, "wealth")
    assert accounts.get(bid) is None


def test_last_admin_cannot_delete_themselves(accounts, health):
    register(health)
    enable_totp(health, accounts)
    accounts.set_registration_mode(accounts.by_username("anna"), "open")
    register(TestClient(health.app), "bob")
    code = code_for(accounts, "anna", 30)
    r = health.request("DELETE", "/api/account", json={"password": PASSWORD, "totp": code})
    assert r.json()["code"] == "last_admin"


def test_admin_tools(accounts, health):
    register(health)
    enable_totp(health, accounts)
    accounts.set_registration_mode(accounts.by_username("anna"), "open")
    bob = TestClient(health.app)
    register(bob, "bob")
    bid = accounts.by_username("bob")["id"]
    assert bob.get("/api/admin/accounts").json()["code"] == "admins_only"
    listed = health.get("/api/admin/accounts").json()
    assert [a["username"] for a in listed] == ["anna", "bob"]
    assert health.patch(f"/api/admin/accounts/{bid}", json={"suspended": True}).status_code == 200
    assert bob.get("/api/auth/account").status_code == 401
    health.patch(f"/api/admin/accounts/{bid}", json={"suspended": False})
    temporary = health.post(f"/api/admin/accounts/{bid}/reset-password").json()["password"]
    assert TestClient(health.app).post("/api/auth/login", json={"username": "bob", "password": temporary}).status_code == 200
    assert health.request("DELETE", f"/api/admin/accounts/{bid}?confirm=nope").json()["code"] == "confirm_username"
    assert health.request("DELETE", f"/api/admin/accounts/{bid}?confirm=bob").status_code == 200
    assert accounts.by_username("bob")["deleted_at"] is not None


def test_legacy_password_opens_the_account_until_changed(accounts, health):
    register(health)
    with accounts.engine.begin() as c:
        c.execute(accounts_table.update().values(legacy_password_hashes=[hash_password("the old wealth password")]))
    c = TestClient(health.app)
    assert c.post("/api/auth/login", json={"username": "anna", "password": "the old wealth password"}).status_code == 200
    c.post("/api/account/password", json={"current": "the old wealth password", "new": "a brand new passphrase"})
    again = TestClient(health.app)
    assert again.post("/api/auth/login", json={"username": "anna", "password": "the old wealth password"}).json()["code"] == "bad_credentials"
    assert again.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}).json()["code"] == "bad_credentials"


def test_session_from_another_secret_is_refused(accounts, health, tmp_path):
    register(health)
    token = health.cookies.get(session.COOKIE)
    other_cfg = config(tmp_path / "x", session_secret="t" * 40)
    assert session.claims(token, other_cfg) is None


def test_config_problems():
    cfg = Config(database_url="", session_secret="short", encryption_key="not a key")
    assert len(cfg.problems()) == 3


def test_aliases_answer_the_old_paths(accounts):
    api = FastAPI()
    install(api)
    router, _ = make_router(accounts, "health", aliases={"/api/login": "/api/auth/login", "/api/register": "/api/auth/register"})
    api.include_router(router)
    c = TestClient(api)
    assert c.post("/api/register", json={"username": "anna", "password": PASSWORD, "consent": True,
                                         "email": "anna@example.org"}).status_code == 200
    assert TestClient(api).post("/api/login", json={"username": "anna", "password": PASSWORD}).status_code == 200


def test_bootstrap_from_an_app_login(accounts):
    a = accounts.bootstrap("Alice", hash_password(PASSWORD), "health", "1")
    assert a["is_admin"] and accounts.local_key(a["id"], "health") == "1"
    assert accounts.bootstrap("bob", hash_password(PASSWORD), "health", "2") is None  # once there is an account
    assert accounts.login("alice", PASSWORD)["username"] == "alice"


def test_consent_on_the_first_visit_after_an_admin_gave_the_app(accounts, wealth):
    register(wealth, consent=False)
    anna = accounts.by_username("anna")
    accounts.set_app(anna, anna["id"], "health", enabled=True)
    assert accounts.apps(anna["id"])["health"]["consent_at"] is None
    assert wealth.post("/api/account/apps/health", json={}).json()["code"] == "consent_required"
    with accounts.engine.begin() as c:
        c.execute(accounts_table.update().values(is_admin=False))
    assert wealth.post("/api/account/apps/health", json={}).json()["code"] == "consent_required"
    assert wealth.post("/api/account/apps/health", json={"consent": True}).status_code == 200
    assert accounts.apps(anna["id"])["health"]["consent_at"] is not None


def test_an_app_admin_manages_only_accounts_of_their_app(accounts, health):
    register(health)
    anna = accounts.by_username("anna")
    accounts.set_registration_mode(anna, "open")
    for name, app in (("bob", "wealth"), ("carl", "wealth")):
        c = TestClient(make_app(accounts, app))
        register(c, name, consent=False)
    bob, carl = accounts.by_username("bob"), accounts.by_username("carl")
    accounts.set_app(anna, carl["id"], "health", enabled=True)
    assert accounts.can_manage(bob, "wealth", carl["id"]) is False  # carl uses health too
    assert accounts.can_manage(carl, "wealth", bob["id"]) is True
    assert accounts.can_manage(bob, None, carl["id"]) is False
    assert accounts.can_manage(anna, None, carl["id"]) is True
    assert accounts.can_manage(bob, "wealth", anna["id"]) is False  # never an account admin


def test_reset_to_a_chosen_password(accounts, health):
    register(health)
    anna = accounts.by_username("anna")
    assert accounts.reset_password(anna, anna["id"], "a chosen new passphrase") is None
    assert accounts.login("anna", "a chosen new passphrase")


def test_before_login_can_bring_in_an_old_login(accounts):
    api = FastAPI()
    install(api)
    old = {"olga": hash_password(PASSWORD)}

    def bring_in(name, password):
        if name in old and not accounts.by_username(name):
            accounts.create_linked(name, old[name], "wealth", name, totp_secret=None)

    router, _ = make_router(accounts, "wealth", before_login=bring_in)
    api.include_router(router)
    assert TestClient(api).post("/api/auth/login", json={"username": "olga", "password": PASSWORD}).status_code == 200
    assert accounts.local_key(accounts.by_username("olga")["id"], "wealth") == "olga"


def test_create_linked_brings_two_step_login(accounts):
    a = accounts.create_linked("tess", hash_password(PASSWORD), "wealth", "Tess", display_name="Tess", locale="nl",
                               totp_secret="JBSWY3DPEHPK3PXP", totp_backup=[])
    assert a["locale"] == "nl" and a["display_name"] == "Tess" and a["totp_enabled_at"]
    with pytest.raises(Exception):
        accounts.login("tess", PASSWORD)  # the code is asked for
    assert accounts.login("tess", PASSWORD, totp.code_at("JBSWY3DPEHPK3PXP"))


def test_stay_logged_in_or_a_browser_session(health, accounts):
    register(health)
    long = TestClient(health.app).post("/api/auth/login", json={"username": "anna", "password": PASSWORD})
    assert "max-age=2592000" in long.headers["set-cookie"].lower()  # 30 days
    short = TestClient(health.app).post("/api/auth/login", json={"username": "anna", "password": PASSWORD, "remember": False})
    header = short.headers["set-cookie"].lower()
    assert "max-age" not in header and "expires" not in header  # gone when the browser closes
    c = session.claims(short.cookies.get(session.COOKIE), accounts.config)
    assert c["exp"] - c["iat"] == 24 * 3600 and c["rm"] == 0
    assert health.get("/api/auth/registration-status").json()["session_days"] == 30


def test_registration_status_tells_the_front_door(tmp_path, health):
    assert health.get("/api/auth/registration-status").json()["front_door_url"] is None
    for kw, url in (({"cookie_domain": "trackerai.nl"}, "https://www.trackerai.nl"),
                    ({"cookie_domain": "trackerai.nl", "front_door": "https://trackerai.example/"}, "https://trackerai.example")):
        cfg = config(tmp_path, **kw)
        c = TestClient(make_app(Accounts(connect(cfg.database_url), cfg), "wealth"))
        assert c.get("/api/auth/registration-status").json()["front_door_url"] == url
    assert c.get("/api/auth/registration-status").json()["tracker_urls"] == {"health": "https://health.trackerai.nl",
                                                                              "wealth": "https://wealth.trackerai.nl"}


def test_a_remembered_device_is_not_asked_for_the_code_again(health, accounts):
    register(health)
    secret, _ = enable_totp(health, accounts)
    phone = TestClient(health.app)
    code = totp.code_at(secret, time.time() + 30)
    r = phone.post("/api/auth/login", json={"username": "anna", "password": PASSWORD, "totp": code})
    assert r.status_code == 200 and phone.cookies.get(session.DEVICE_COOKIE)
    phone.post("/api/auth/logout")
    # the same browser: the password alone
    assert phone.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}).status_code == 200
    # another browser still needs the code
    other = TestClient(health.app)
    assert other.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}).json()["code"] == "totp_required"
    # a device cookie of someone else's account does not help
    forged = TestClient(health.app, cookies={session.DEVICE_COOKIE: phone.cookies.get(session.DEVICE_COOKIE)})
    accounts.set_registration_mode(accounts.by_username("anna"), "open")
    register(TestClient(health.app), "bob")
    bob_secret, _ = enable_totp(TestClient(health.app, cookies={session.COOKIE: TestClient(health.app).post(
        "/api/auth/login", json={"username": "bob", "password": PASSWORD}).cookies.get(session.COOKIE)}), accounts, "bob")
    assert forged.post("/api/auth/login", json={"username": "bob", "password": PASSWORD}).json()["code"] == "totp_required"
    # a password change ends the remembered device
    phone.post("/api/account/password", json={"current": PASSWORD, "new": "another long passphrase"})
    phone.post("/api/auth/logout")
    r = phone.post("/api/auth/login", json={"username": "anna", "password": "another long passphrase"})
    assert r.json()["code"] == "totp_required"


def test_without_stay_logged_in_the_device_is_not_remembered(health, accounts):
    register(health)
    secret, _ = enable_totp(health, accounts)
    c = TestClient(health.app)
    code = totp.code_at(secret, time.time() + 30)
    assert c.post("/api/auth/login", json={"username": "anna", "password": PASSWORD, "totp": code, "remember": False}).status_code == 200
    assert not c.cookies.get(session.DEVICE_COOKIE)


def test_signing_up_with_the_trackers_of_choice(accounts, health):
    r = register(health, apps=["health", "wealth"])
    assert r.status_code == 200
    assert sorted(accounts.apps(accounts.by_username("anna")["id"])) == ["health", "wealth"]
    accounts.set_registration_mode(accounts.by_username("anna"), "open")
    bob = TestClient(health.app, base_url="https://health.example")
    assert register(bob, "bob", apps=["wealth"]).status_code == 200  # signed up here, but only for wealth
    assert sorted(accounts.apps(accounts.by_username("bob")["id"])) == ["wealth"]
    cleo = TestClient(health.app, base_url="https://health.example")
    assert register(cleo, "cleo", apps=["health"], consent=False).json()["code"] == "consent_required"
    assert register(cleo, "cleo", apps=["nope"]).json()["code"] == "unknown_app"


def test_the_admin_routes_also_answer_under_trackerai(accounts, health):
    register(health)
    enable_totp(health, accounts)  # the first account is an admin: two-step login first
    assert health.get("/api/trackerai/admin/accounts").json()[0]["username"] == "anna"
    r = health.get("/api/trackerai/admin/registration").json()
    assert r["settings"] == {"require_totp": "shared", "email": False, "session_days": 30}
    code = health.post("/api/trackerai/admin/invites", json={"days": 7, "apps": ["health", "wealth"]}).json()["code"]
    assert health.delete(f"/api/trackerai/admin/invites/{code}").status_code == 200
    bob = TestClient(health.app, base_url="https://health.example")
    assert bob.get("/api/trackerai/admin/accounts").status_code == 401


def test_front_door_router_has_no_default_app(accounts):
    """The front door's own API (trackerai-api) mounts the routes without an app: sign-up names the trackers."""
    accounts.config = replace(accounts.config, oauth_issuer="https://trackerai.example",
                              oauth_resources=json.dumps({"wealth": "https://wealth.example/api/mcp"}))
    door = TestClient(make_app(accounts, None), base_url="https://trackerai.example")
    r = register(door)
    assert r.status_code == 422 and r.json()["code"] == "unknown_app"
    assert register(door, apps=["wealth"]).status_code == 200
    assert door.get("/api/auth/account").json()["username"] == "anna"
    assert door.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}).status_code == 200
    # The agents' OAuth issuer is each app's own; the front door has none.
    assert door.get("/.well-known/oauth-authorization-server").status_code == 404
