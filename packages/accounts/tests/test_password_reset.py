"""A forgotten password: a code by email to the account's confirmed address, then a new password."""

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from test_accounts import PASSWORD, config, enable_totp, make_app, register

from trackerai_accounts import Accounts, connect, session
from trackerai_accounts.mail import Outbox
from trackerai_accounts.store import accounts as accounts_table
from trackerai_accounts.store import email_codes

NEW = "a brand new passphrase"


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


def confirmed(client, outbox, name="anna", **kw):
    """An account whose address from sign-up is confirmed (so codes by email are its two-step login)."""
    assert register(client, name, **kw).status_code == 200
    assert client.post("/api/account/email/confirm", json={"code": last_code(outbox)}).status_code == 200
    return client


def stranger(client) -> TestClient:
    return TestClient(client.app, base_url="https://health.example")


def forgot(client, login):
    return client.post("/api/auth/password/forgot", json={"login": login})


def reset(client, login, code, new=NEW):
    return client.post("/api/auth/password/reset", json={"login": login, "code": code, "new_password": new})


def wrong(code: str) -> str:
    return "000000" if code != "000000" else "111111"


def test_registration_status_tells_whether_a_reset_can_work(health, pg_url):
    assert health.get("/api/auth/registration-status").json()["password_reset"] is True
    cfg = config(pg_url)
    without = TestClient(make_app(Accounts(connect(cfg.database_url), cfg, mailer=None), "health"))
    assert without.get("/api/auth/registration-status").json()["password_reset"] is False


def test_resetting_a_forgotten_password(health, outbox, accounts):
    confirmed(health, outbox)
    token = health.cookies.get(session.COOKIE)
    other = TestClient(make_app(accounts, "wealth"), base_url="https://wealth.example", cookies={session.COOKIE: token})
    assert other.get("/api/auth/account").status_code == 200
    c = stranger(health)
    before = len(outbox.sent)
    r = forgot(c, "Anna")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert len(outbox.sent) == before + 1
    mail = outbox.sent[-1]
    assert mail["to"] == "anna@example.org" and "anna" in mail["text"]
    assert "herstellen" in mail["subject"] or "reset" in mail["subject"].lower()
    assert reset(c, "anna", last_code(outbox)).json() == {"ok": True}
    # every session ended, in every app
    assert health.get("/api/auth/account").json()["code"] == "not_logged_in"
    assert other.get("/api/auth/account").json()["code"] == "not_logged_in"
    # the old password is gone, the new one works (and two-step login still asks its code: here by email)
    assert c.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}).json()["code"] == "bad_credentials"
    r = c.post("/api/auth/login", json={"username": "anna", "password": NEW})
    assert r.status_code == 401 and r.json()["code"] == "email_code_sent"
    assert c.post("/api/auth/login", json={"username": "anna", "password": NEW, "totp": last_code(outbox)}).status_code == 200
    assert accounts.list_audit()[0]["action"] == "reset_password_by_email"


def test_by_email_address_too_and_a_code_works_once(health, outbox):
    confirmed(health, outbox)
    c = stranger(health)
    forgot(c, " Anna@Example.org ")
    code = last_code(outbox)
    assert reset(c, "anna@example.org", code).status_code == 200
    assert reset(c, "anna@example.org", code, "yet another passphrase").json()["code"] == "reset_code_invalid"


def test_an_unknown_login_answers_exactly_the_same(health, outbox):
    confirmed(health, outbox)
    c = stranger(health)
    known = forgot(c, "anna")
    sent = len(outbox.sent)
    for login in ("nobody", "nobody@example.org", ""):
        r = forgot(c, login)
        assert (r.status_code, r.json(), r.headers.get("content-length")) == (
            known.status_code,
            known.json(),
            known.headers.get("content-length"),
        )
    assert len(outbox.sent) == sent
    # and so does a reset for it
    assert reset(c, "nobody", "123456").json()["code"] == "reset_code_invalid"


def test_no_mail_without_a_confirmed_address(health, outbox, accounts):
    register(health)  # the welcome mail went out, the address is not confirmed
    sent = len(outbox.sent)
    c = stranger(health)
    assert forgot(c, "anna").json() == {"ok": True}
    assert forgot(c, "anna@example.org").json() == {"ok": True}
    assert len(outbox.sent) == sent


def test_a_wrong_code_an_expired_code_and_too_many_tries(health, outbox, accounts):
    confirmed(health, outbox)
    c = stranger(health)
    forgot(c, "anna")
    code = last_code(outbox)
    r = reset(c, "anna", wrong(code))
    assert r.status_code == 422 and r.json()["code"] == "reset_code_invalid"
    # a login code is no reset code
    c.post("/api/auth/login", json={"username": "anna", "password": PASSWORD})
    assert reset(c, "anna", last_code(outbox)).json()["code"] == "reset_code_invalid"
    # five wrong tries spend it
    for _ in range(4):
        reset(c, "anna", wrong(code))
    assert reset(c, "anna", code).json()["code"] == "reset_code_invalid"
    # expired
    forgot(c, "anna")
    fresh = last_code(outbox)
    with accounts.engine.begin() as conn:
        conn.execute(update(email_codes).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    assert reset(c, "anna", fresh).json()["code"] == "reset_code_invalid"
    assert c.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}).json()["code"] == "email_code_sent"


def test_a_refused_password_keeps_the_code(health, outbox):
    confirmed(health, outbox)
    c = stranger(health)
    forgot(c, "anna")
    code = last_code(outbox)
    assert reset(c, "anna", code, "short").json()["code"] == "password_too_short"
    assert reset(c, "anna", code, "aaaaaaaaaaaa").json()["code"] == "password_too_common"
    assert reset(c, "anna", code).status_code == 200


def test_reset_codes_are_limited_and_leave_the_login_codes_alone(health, outbox):
    confirmed(health, outbox)
    c = stranger(health)
    sent = len(outbox.sent)
    answers = [forgot(c, "anna").json() for _ in range(5)]
    assert answers == [{"ok": True}] * 5  # the same answer, also over the limit
    assert len(outbox.sent) == sent + 3
    # asking for reset codes did not use up the login codes
    assert c.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}).json()["code"] == "email_code_sent"


def test_per_ip_limits(health, outbox):
    confirmed(health, outbox)
    c = stranger(health)
    codes = [forgot(c, f"someone{i}").status_code for i in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429
    for _ in range(10):
        reset(c, "anna", "123456")
    r = reset(c, "anna", "123456")
    assert r.status_code == 429 and r.json()["code"] == "too_many_attempts"


def test_two_step_login_is_still_asked_afterwards(health, outbox, accounts):
    confirmed(health, outbox)
    enable_totp(health, accounts)
    c = stranger(health)
    forgot(c, "anna")
    assert reset(c, "anna", last_code(outbox)).status_code == 200
    r = c.post("/api/auth/login", json={"username": "anna", "password": NEW})
    assert r.status_code == 401 and r.json()["code"] == "totp_required"
    assert c.get("/api/auth/account").json()["code"] == "not_logged_in"
    account = accounts.by_username("anna")
    assert account["totp_enabled_at"] and account["email_codes_at"]


def test_a_remembered_device_is_asked_for_the_code_again(health, outbox, accounts):
    confirmed(health, outbox)
    c = stranger(health)
    c.post("/api/auth/login", json={"username": "anna", "password": PASSWORD})
    assert c.post("/api/auth/login", json={"username": "anna", "password": PASSWORD, "totp": last_code(outbox)}).status_code == 200
    assert c.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}).status_code == 200  # remembered
    forgot(c, "anna")
    assert reset(c, "anna", last_code(outbox)).status_code == 200
    assert c.post("/api/auth/login", json={"username": "anna", "password": NEW}).json()["code"] == "email_code_sent"


def test_failed_logins_are_cleared(health, outbox, accounts):
    confirmed(health, outbox)
    for _ in range(10):
        accounts._failed(accounts.by_username("anna"))
    c = stranger(health)
    assert c.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}).json()["code"] == "too_many_attempts"
    forgot(c, "anna")
    assert reset(c, "anna", last_code(outbox)).status_code == 200
    assert accounts.by_username("anna")["failed_logins"] == 0
    assert c.post("/api/auth/login", json={"username": "anna", "password": NEW}).json()["code"] == "email_code_sent"


def test_a_suspended_account_gets_no_code(health, outbox, accounts):
    confirmed(health, outbox)
    with accounts.engine.begin() as conn:
        conn.execute(update(accounts_table).where(accounts_table.c.username == "anna").values(suspended=True))
    sent = len(outbox.sent)
    assert forgot(stranger(health), "anna").json() == {"ok": True}
    assert len(outbox.sent) == sent


def test_the_mail_in_both_languages():
    from trackerai_accounts import mail

    en = mail.reset_mail("123456", "anna", "en", 10)
    nl = mail.reset_mail("123456", "anna", "nl", 10)
    assert "123456" in en[0] and "123456" in en[1] and "10 minutes" in en[1]
    assert "123456" in nl[0] and "wachtwoord" in nl[1] and "10 minuten" in nl[1]
