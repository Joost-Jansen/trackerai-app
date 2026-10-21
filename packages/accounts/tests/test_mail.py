"""Delivery uses verified TLS and does not expose codes or credentials on failure."""

import http.client
import json
import re
import ssl

import pytest
from fastapi.testclient import TestClient
from test_accounts import PASSWORD, config, make_app, register

from trackerai_accounts import Accounts, Config, connect, mail


@pytest.fixture
def transport(monkeypatch):
    class Connection:
        status = 201
        error = None
        instances = []

        def __init__(self, host, **options):
            self.host, self.options, self.closed = host, options, False
            self.instances.append(self)

        def request(self, method, path, **kwargs):
            self.method, self.path, self.request_options = method, path, kwargs
            if self.error:
                raise self.error

        def getresponse(self):
            return self

        def close(self):
            self.closed = True

    monkeypatch.setattr(mail.http.client, "HTTPSConnection", Connection)
    return Connection


def api_config(database_url="postgresql://never-connected/accounts", **kwargs):
    return config(database_url, resend_api_key="test-only-key", mail_from="trackerai <login@example.org>", **kwargs)


def test_resend_delivery_preserves_dutch_text_and_verifies_tls(transport):
    mail.mailer_for(api_config()).send("anna@example.org", "Je inlogcode", "Hij werkt één keer: 123456")
    connection = transport.instances[-1]
    assert connection.host == "api.resend.com" and connection.path == "/emails" and connection.method == "POST"
    assert connection.options["timeout"] == 15
    context = connection.options["context"]
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    assert connection.request_options["headers"]["Authorization"] == "Bearer test-only-key"
    assert connection.request_options["headers"]["Content-Type"] == "application/json"
    assert json.loads(connection.request_options["body"]) == {
        "from": "trackerai <login@example.org>",
        "to": ["anna@example.org"],
        "subject": "Je inlogcode",
        "text": "Hij werkt één keer: 123456",
    }
    assert connection.closed


@pytest.mark.parametrize("status", [301, 401, 429, 500])
def test_provider_rejections_do_not_redirect_retry_or_expose_message(transport, status):
    transport.status = status
    with pytest.raises(RuntimeError, match="^Email provider rejected the message$"):
        mail.mailer_for(api_config(smtp_host="smtp.example.org", smtp_from="login@example.org")).send(
            "anna@example.org", "Secret", "123456"
        )
    assert len(transport.instances) == 1 and transport.instances[0].closed


@pytest.mark.parametrize("error", [TimeoutError("private details"), http.client.RemoteDisconnected("private details")])
def test_connection_errors_are_generic_and_close_the_connection(transport, error):
    transport.error = error
    with pytest.raises(RuntimeError, match="^Email provider unavailable$"):
        mail.mailer_for(api_config()).send("anna@example.org", "Secret", "123456")
    assert transport.instances[0].closed


def test_environment_and_legacy_smtp_selection(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", " test-only-key ")
    monkeypatch.setenv("MAIL_FROM", " trackerai <login@example.org> ")
    cfg = Config.from_env()
    assert cfg.resend_api_key == "test-only-key" and cfg.mail_sender == "trackerai <login@example.org>"
    assert cfg.mail_configured and isinstance(mail.mailer_for(cfg), mail.ResendMailer)
    assert isinstance(mail.mailer_for(config(smtp_host="smtp.example.org", smtp_from="login@example.org")), mail.SmtpMailer)
    assert isinstance(mail.mailer_for(config(resend_api_key="test-only-key", smtp_from="login@example.org")), mail.ResendMailer)
    for settings in ({}, {"resend_api_key": "test-only-key"}, {"mail_from": "login@example.org"}):
        cfg = config(**settings)
        assert not cfg.mail_configured and mail.mailer_for(cfg) is None


def test_accounts_can_confirm_email_and_log_in_using_resend(pg_url, transport):
    cfg = api_config(pg_url)
    accounts = Accounts(connect(cfg.database_url), cfg)
    app = make_app(accounts, "health")
    client = TestClient(app, base_url="https://health.example")
    assert client.get("/api/auth/registration-status").json()["email_codes"] is True
    assert register(client).status_code == 200
    assert client.post("/api/account/email", json={"email": "anna@example.org", "password": PASSWORD}).status_code == 200

    def code():
        payload = json.loads(transport.instances[-1].request_options["body"])
        return re.search(r"\b(\d{6})\b", payload["text"]).group(1)

    assert client.post("/api/account/email/confirm", json={"code": code()}).json()["two_step"] is True
    fresh = TestClient(app, base_url="https://health.example")
    assert fresh.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}).json()["code"] == "email_code_sent"
    assert fresh.post("/api/auth/login", json={"username": "anna", "password": PASSWORD, "totp": code()}).status_code == 200
    transport.status = 429
    failed = TestClient(app, base_url="https://health.example")
    response = failed.post("/api/auth/login", json={"username": "anna", "password": PASSWORD})
    assert response.status_code == 503 and response.json()["code"] == "email_unavailable"
