"""Two-step login by email: a code mailed at login, as an alternative to the authenticator app."""

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from test_accounts import PASSWORD, config, enable_totp, make_app, register

from trackerai_accounts import Accounts, connect
from trackerai_accounts.mail import Outbox
from trackerai_accounts.store import email_codes


@pytest.fixture
def outbox():
    return Outbox()


@pytest.fixture
def accounts(pg_url, outbox):
    cfg = config(pg_url)
    return Accounts(connect(cfg.database_url), cfg, mailer=outbox)


@pytest.fixture
def health(accounts):
    return TestClient(make_app(accounts, "health"), base_url="https://health.example")


def last_code(outbox) -> str:
    return re.search(r"\b(\d{6})\b", outbox.sent[-1]["text"]).group(1)


def turn_on(client, outbox, email="anna@example.org"):
    r = client.post("/api/account/email", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200 and r.json()["sent_to"] == email.lower()
    assert outbox.sent[-1]["to"] == email.lower()
    r = client.post("/api/account/email/confirm", json={"code": last_code(outbox)})
    assert r.status_code == 200 and r.json()["email_codes"] is True and r.json()["two_step"] is True
    return r


def login(name="anna", **kw):
    return {"username": name, "password": PASSWORD, **kw}


def test_turning_on_and_logging_in_with_a_code_by_email(health, outbox):
    register(health)
    turn_on(health, outbox)
    fresh = TestClient(health.app, base_url="https://health.example")
    r = fresh.post("/api/auth/login", json=login())
    assert r.status_code == 401 and r.json()["code"] == "email_code_sent"
    assert r.json()["params"]["to"] == "a…@example.org"
    assert "login code" in outbox.sent[-1]["subject"].lower() or "inlogcode" in outbox.sent[-1]["subject"].lower()
    r = fresh.post("/api/auth/login", json=login(totp=last_code(outbox)))
    assert r.status_code == 200
    assert fresh.get("/api/data").status_code == 200


def test_a_code_works_once_and_a_wrong_one_does_not(health, outbox):
    register(health)
    turn_on(health, outbox)
    c = TestClient(health.app, base_url="https://health.example")
    c.post("/api/auth/login", json=login())
    code = last_code(outbox)
    wrong = "000000" if code != "000000" else "111111"
    assert c.post("/api/auth/login", json=login(totp=wrong)).json()["code"] == "totp_invalid"
    assert c.post("/api/auth/login", json=login(totp=code)).status_code == 200
    assert TestClient(health.app).post("/api/auth/login", json=login(totp=code)).json()["code"] == "totp_invalid"


def test_a_code_expires_and_a_new_one_replaces_the_old(health, outbox, accounts):
    register(health)
    turn_on(health, outbox)
    c = TestClient(health.app, base_url="https://health.example")
    c.post("/api/auth/login", json=login())
    first = last_code(outbox)
    c.post("/api/auth/login", json=login())
    second = last_code(outbox)
    if first != second:
        assert c.post("/api/auth/login", json=login(totp=first)).json()["code"] == "totp_invalid"
    with accounts.engine.begin() as conn:
        conn.execute(update(email_codes).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    assert c.post("/api/auth/login", json=login(totp=second)).json()["code"] == "totp_invalid"


def test_five_wrong_tries_spend_a_code(health, outbox):
    register(health)
    turn_on(health, outbox)
    c = TestClient(health.app, base_url="https://health.example")
    c.post("/api/auth/login", json=login())
    code = last_code(outbox)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        c.post("/api/auth/login", json=login(totp=wrong))
    assert c.post("/api/auth/login", json=login(totp=code)).json()["code"] == "totp_invalid"


def test_codes_per_quarter_hour_are_limited(health, outbox):
    register(health)  # the welcome mail counts too
    health.post("/api/account/email/confirm", json={"code": last_code(outbox)})
    c = TestClient(health.app, base_url="https://health.example")
    codes = [c.post("/api/auth/login", json=login()).json()["code"] for _ in range(5)]
    assert codes[:4] == ["email_code_sent"] * 4 and codes[4] == "too_many_codes"


def test_with_the_app_too_the_page_offers_a_mail(health, outbox, accounts):
    register(health)
    enable_totp(health, accounts)
    r = health.post("/api/account/email", json={"email": "anna@example.org", "password": PASSWORD})
    assert r.json()["code"] == "totp_required"  # adding a second way asks for the first
    from test_accounts import code_for

    assert (
        health.post(
            "/api/account/email", json={"email": "anna@example.org", "password": PASSWORD, "code": code_for(accounts, "anna", 30)}
        ).status_code
        == 200
    )
    assert health.post("/api/account/email/confirm", json={"code": last_code(outbox)}).status_code == 200
    c = TestClient(health.app, base_url="https://health.example")
    r = c.post("/api/auth/login", json=login())
    assert r.json()["code"] == "totp_required" and r.json()["params"]["email"] is True
    assert c.post("/api/auth/login", json=login(send_email=True)).json()["code"] == "email_code_sent"
    assert c.post("/api/auth/login", json=login(totp=last_code(outbox))).status_code == 200


def test_signing_up_needs_an_address_and_confirming_it(accounts, health, outbox):
    assert register(health, email="").json()["code"] == "email_invalid"
    r = register(health)
    assert r.status_code == 200 and r.json()["email_verify_required"] is True
    welcome = outbox.sent[-1]
    assert welcome["to"] == "anna@example.org" and "anna" in welcome["text"]
    # nothing opens until the address is confirmed
    assert health.get("/api/data").json()["code"] == "email_verify_required"
    assert health.get("/api/auth/account").json()["email_verify_required"] is True
    wrong = "000000" if last_code(outbox) != "000000" else "111111"
    assert health.post("/api/account/email/confirm", json={"code": wrong}).json()["code"] == "totp_invalid"
    r = health.post("/api/account/email/confirm", json={"code": last_code(outbox)})
    assert r.status_code == 200 and r.json()["email_verified"] is True
    # confirmed, it is the two-step login, also where that is required (the first account is an admin)
    assert r.json()["email_codes"] is True and r.json()["totp_setup_required"] is False
    assert health.get("/api/data").status_code == 200
    c = TestClient(health.app, base_url="https://health.example")
    assert c.post("/api/auth/login", json=login()).json()["code"] == "email_code_sent"


def test_a_typo_in_the_address_can_be_corrected_until_confirmed(accounts, health, outbox):
    register(health, email="anna@exmple.org")
    r = health.post("/api/account/email/resend", json={"email": "anna@example.org"})
    assert r.json()["sent_to"] == "anna@example.org" and outbox.sent[-1]["to"] == "anna@example.org"
    assert health.post("/api/account/email/confirm", json={"code": last_code(outbox)}).status_code == 200
    assert health.post("/api/account/email/resend", json={}).json()["code"] == "email_already_verified"


def test_an_address_belongs_to_one_account(accounts, health, outbox):
    register(health)
    accounts.set_registration_mode(accounts.by_username("anna"), "open")
    r = register(TestClient(health.app, base_url="https://health.example"), "bob", email="anna@example.org")
    assert r.json()["code"] == "email_taken"


def test_without_a_mail_server_signing_up_still_needs_an_address(pg_url):
    cfg = config(pg_url)
    accounts = Accounts(connect(cfg.database_url), cfg)
    c = TestClient(make_app(accounts, "health"), base_url="https://health.example")
    assert register(c, email="nope").json()["code"] == "email_invalid"
    r = register(c)
    assert r.status_code == 200 and r.json()["email_verify_required"] is False


def test_address_checks(health, outbox, accounts):
    register(health)
    assert health.post("/api/account/email", json={"email": "not-an-address", "password": PASSWORD}).json()["code"] == "email_invalid"
    assert health.post("/api/account/email", json={"email": "a@b.org", "password": "wrong"}).json()["code"] == "wrong_current_password"
    turn_on(health, outbox, "Anna@Example.org")
    assert accounts.by_username("anna")["email"] == "anna@example.org"
    accounts.set_registration_mode(accounts.by_username("anna"), "open")
    bob = TestClient(health.app, base_url="https://health.example")
    register(bob, "bob")
    r = bob.post("/api/account/email", json={"email": "anna@example.org", "password": PASSWORD})
    assert r.json()["code"] == "email_taken"


def test_turning_off_asks_for_a_mailed_code(health, outbox, accounts):
    register(health)
    turn_on(health, outbox)
    assert health.post("/api/account/email/disable", json={"password": PASSWORD}).json()["code"] == "totp_required"
    assert health.post("/api/account/email/code").json()["sent_to"] == "a…@example.org"
    r = health.post("/api/account/email/disable", json={"password": PASSWORD, "code": last_code(outbox)})
    assert r.status_code == 200
    row = accounts.by_username("anna")
    assert row["email"] is None and row["email_codes_at"] is None


def test_deleting_the_account_with_a_mailed_code(health, outbox, accounts):
    register(health)
    turn_on(health, outbox)
    assert health.request("DELETE", "/api/account", json={"password": PASSWORD}).json()["code"] == "totp_required"
    health.post("/api/account/email/code")
    assert health.request("DELETE", "/api/account", json={"password": PASSWORD, "totp": last_code(outbox)}).status_code == 200


def test_the_admin_reset_turns_it_off(health, outbox, accounts):
    register(health)
    turn_on(health, outbox)
    me = accounts.by_username("anna")
    accounts.reset_totp(me, me["id"])
    assert accounts.by_username("anna")["email_codes_at"] is None


def test_without_a_mail_server_it_is_not_offered(pg_url):
    cfg = config(pg_url)
    accounts = Accounts(connect(cfg.database_url), cfg)
    assert accounts.mailer is None
    c = TestClient(make_app(accounts, "health"), base_url="https://health.example")
    register(c)
    assert c.get("/api/auth/registration-status").json()["email_codes"] is False
    assert c.get("/api/account/totp").json()["email_available"] is False
    assert c.post("/api/account/email", json={"email": "a@b.org", "password": PASSWORD}).json()["code"] == "email_unavailable"


def test_a_remembered_device_skips_the_mail(health, outbox):
    register(health)
    turn_on(health, outbox)
    c = TestClient(health.app, base_url="https://health.example")
    c.post("/api/auth/login", json=login())
    assert c.post("/api/auth/login", json=login(totp=last_code(outbox))).status_code == 200
    sent = len(outbox.sent)
    c.cookies.delete("trackerai_session")
    assert c.post("/api/auth/login", json=login()).status_code == 200
    assert len(outbox.sent) == sent
