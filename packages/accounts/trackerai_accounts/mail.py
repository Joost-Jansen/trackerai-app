"""Sending login codes through Resend HTTPS or an SMTP server.

`Accounts.mailer` has `send(to, subject, text)`: a configured transport, or in tests `Outbox`, which keeps the messages.
"""

from __future__ import annotations

import http.client
import json
import smtplib
import ssl
from email.message import EmailMessage

from trackerai_accounts.config import Config


class ResendMailer:
    """HTTPS delivery for hosts that block SMTP. Never follow redirects or log mail contents."""

    def __init__(self, config: Config):
        self.config = config

    def send(self, to: str, subject: str, text: str) -> None:
        body = json.dumps({"from": self.config.mail_sender, "to": [to], "subject": subject, "text": text},
                          ensure_ascii=False).encode("utf-8")
        connection = http.client.HTTPSConnection("api.resend.com", context=ssl.create_default_context(), timeout=15)
        try:
            connection.request("POST", "/emails", body=body, headers={
                "Authorization": f"Bearer {self.config.resend_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "trackerai-accounts/0.1",
            })
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                raise RuntimeError("Email provider rejected the message")
        except (OSError, http.client.HTTPException):
            raise RuntimeError("Email provider unavailable") from None
        finally:
            connection.close()


class SmtpMailer:
    def __init__(self, config: Config):
        self.config = config

    def send(self, to: str, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.config.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        context = ssl.create_default_context()
        if self.config.smtp_port == 465:
            server = smtplib.SMTP_SSL(self.config.smtp_host, 465, context=context, timeout=15)
        else:
            server = smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=15)
            server.starttls(context=context)
        with server:
            if self.config.smtp_username:
                server.login(self.config.smtp_username, self.config.smtp_password)
            server.send_message(msg)


class Outbox:
    """A mailer for tests and local development: the messages stay here."""

    def __init__(self):
        self.sent: list[dict] = []

    def send(self, to: str, subject: str, text: str) -> None:
        self.sent.append({"to": to, "subject": subject, "text": text})


def mailer_for(config: Config):
    if config.resend_api_key and config.mail_sender:
        return ResendMailer(config)
    if config.smtp_host and config.smtp_from:
        return SmtpMailer(config)
    return None


def welcome_mail(code: str, username: str, locale: str | None, minutes: int) -> tuple[str, str]:
    """The mail after signing up: welcome, and the code that confirms the address (it then sends the login codes)."""
    if locale == "en":
        return (f"Welcome to trackerai: your code is {code}",
                f"Welcome to trackerai, {username}.\n\nEnter {code} to confirm your email address and continue. It works "
                f"for {minutes} minutes; the page can send a new one.\n\nFrom then on, logging in also mails you a code: "
                f"your two-step login. You can add an authenticator app in Settings > Account.\n\n"
                f"Didn't sign up? Then ignore this mail.\n")
    return (f"Welkom bij trackerai: je code is {code}",
            f"Welkom bij trackerai, {username}.\n\nVul {code} in om je e-mailadres te bevestigen en verder te gaan. Hij "
            f"werkt {minutes} minuten; de pagina kan een nieuwe sturen.\n\nDaarna mailt het inloggen je ook een code: "
            f"je inloggen in twee stappen. Een authenticator-app kun je toevoegen bij Instellingen › Account.\n\n"
            f"Niet aangemeld? Negeer deze mail dan.\n")


def login_code_mail(code: str, locale: str | None, minutes: int, verify: bool) -> tuple[str, str]:
    """Subject and text of a code mail, in the account's language."""
    if locale == "en":
        if verify:
            return (f"Your trackerai code: {code}",
                    f"Enter {code} to confirm this address for login codes.\n\n"
                    f"The code works for {minutes} minutes. Didn't ask for it? Then ignore this mail.\n")
        return (f"Your trackerai login code: {code}",
                f"Your login code is {code}.\n\nIt works once, for {minutes} minutes.\n\n"
                f"Not trying to log in? Then someone knows your password: change it in Settings > Account.\n")
    if verify:
        return (f"Je trackerai-code: {code}",
                f"Vul {code} in om dit adres te bevestigen voor inlogcodes.\n\n"
                f"De code werkt {minutes} minuten. Niet aangevraagd? Negeer deze mail dan.\n")
    return (f"Je inlogcode voor trackerai: {code}",
            f"Je inlogcode is {code}.\n\nHij werkt één keer, {minutes} minuten lang.\n\n"
            f"Probeer je niet in te loggen? Dan kent iemand je wachtwoord: wijzig het bij Instellingen › Account.\n")
