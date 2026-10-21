"""Settings of the accounts layer, from the environment. Every app that shares the accounts must have the same values
for the first four, or a session from one is not valid in the other:

    ACCOUNTS_DATABASE_URL     the accounts database, postgresql://... (on a laptop: compose.dev.yml's `accounts`)
    ACCOUNTS_SESSION_SECRET   signs the session cookie (any long random string)
    ACCOUNTS_ENCRYPTION_KEY   a Fernet key that encrypts the two-step login secrets
    SESSION_COOKIE_DOMAIN     the shared parent domain, e.g. "trackerai.nl", so one login holds on every subdomain;
                              empty: the cookie stays on the host that set it (one app, or local development)

and per app, as before:

    COOKIE_SECURE             false only for local http:// development
    SESSION_DAYS              "stay logged in": a session lasts this long after its last use (default 30), never
                              beyond 90 days after the password was typed; also how long a device that gave the
                              two-step code is not asked for it again
    SHORT_SESSION_HOURS       without "stay logged in": a browser session, at most this long (default 24)
    REQUIRE_TOTP              who must use two-step login: "shared" (default: admins and anyone using more than one
                              app), "all", "admins" or "off"
    FRONT_DOOR_URL            the front door (trackerai.nl) the apps link to, e.g. its admin page; empty: derived as
                              https://www.<SESSION_COOKIE_DOMAIN>, or none without a shared domain (a tracker on its own)
    LANDING_HEALTH_URL,       where each tracker lives, for the link from one to the other; empty: derived as
    LANDING_WEALTH_URL        https://<app>.<SESSION_COOKIE_DOMAIN>, or none without a shared domain

and, for login codes by email (without these, two-step login is the authenticator app only):

    RESEND_API_KEY, MAIL_FROM  Resend over HTTPS (works where outbound SMTP is blocked)
    or:
    SMTP_HOST, SMTP_PORT      the mail server (port 587: STARTTLS, 465: TLS from the start)
    SMTP_USERNAME, SMTP_PASSWORD
    SMTP_FROM                 the sender, e.g. "trackerai <login@trackerai.nl>"
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass, field

from trackerai_accounts import crypto

APPS = ("health", "wealth")
# Apps whose data is special under the GDPR (art. 9): joining asks for explicit consent.
CONSENT_APPS = ("health",)
TOTP_POLICIES = ("shared", "all", "admins", "off")
LOCALES = ("nl", "en")


def front_door_origins(cookie_domain: str | None) -> list[str]:
    """The front door (trackerai.nl) at the shared cookie's own domain, bare and www: the admin hub there posts to
    every tracker, and that domain can set the session cookie anyway, so each tracker's CSRF origin check accepts it."""
    d = (cookie_domain or "").strip().lstrip(".").lower()
    return [f"https://{d}", f"https://www.{d}"] if d else []


def front_door_url(explicit: str, cookie_domain: str | None) -> str | None:
    """FRONT_DOOR_URL without a trailing slash; empty: the www host of the shared cookie's domain, or None."""
    url = (explicit or "").strip().rstrip("/")
    if url:
        return url
    d = (cookie_domain or "").strip().lstrip(".").lower()
    return f"https://www.{d}" if d else None


def tracker_url(app: str, explicit: str, cookie_domain: str | None) -> str | None:
    """Where a tracker lives, for the link from the other one: LANDING_<APP>_URL as set, else `https://<app>.<domain>` of
    the shared cookie's domain, else None (a tracker on its own has no other one to link to)."""
    url = (explicit or "").strip().rstrip("/")
    if url:
        return url
    d = (cookie_domain or "").strip().lstrip(".").lower()
    return f"https://{app}.{d}" if d else None


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return default if not value else value in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, "") or default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    database_url: str
    session_secret: str
    encryption_key: str
    cookie_domain: str | None = None
    cookie_secure: bool = True
    session_days: int = 30
    short_session_hours: int = 24
    session_max_days: int = 90
    renew_after_s: int = 24 * 3600
    require_totp: str = "shared"
    issuer: str = "trackerai"  # the name in the authenticator app
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    resend_api_key: str = ""
    mail_from: str = ""
    front_door: str = ""  # FRONT_DOOR_URL as set; front_door_url is what the apps link to
    trackers: dict = field(default_factory=dict)  # LANDING_<APP>_URL as set, by app; tracker_urls is what the apps link to
    # Shared by every service. The issuer hosts the consent page; resources are
    # exact public MCP URLs, keyed by app. Empty keeps OAuth disabled.
    oauth_issuer: str = ""
    oauth_resources: str = ""
    agent_plugin_url: str = ""

    @property
    def front_door_url(self) -> str | None:
        return front_door_url(self.front_door, self.cookie_domain)

    @property
    def tracker_urls(self) -> dict[str, str | None]:
        return {app: tracker_url(app, self.trackers.get(app, ""), self.cookie_domain) for app in ("health", "wealth")}

    @property
    def resources(self) -> dict[str, str]:
        try:
            value = json.loads(self.oauth_resources or "{}")
            return value if isinstance(value, dict) else {}
        except ValueError:
            return {}

    @property
    def mail_sender(self) -> str:
        return self.mail_from or self.smtp_from

    @property
    def mail_configured(self) -> bool:
        return bool((self.resend_api_key and self.mail_sender) or (self.smtp_host and self.smtp_from))

    @classmethod
    def from_env(cls) -> "Config":
        policy = os.environ.get("REQUIRE_TOTP", "").strip().lower() or "shared"
        return cls(
            database_url=os.environ.get("ACCOUNTS_DATABASE_URL", "").strip(),
            session_secret=os.environ.get("ACCOUNTS_SESSION_SECRET", "").strip(),
            encryption_key=os.environ.get("ACCOUNTS_ENCRYPTION_KEY", "").strip(),
            cookie_domain=os.environ.get("SESSION_COOKIE_DOMAIN", "").strip().lstrip(".") or None,
            front_door=os.environ.get("FRONT_DOOR_URL", "").strip(),
            trackers={app: os.environ.get(f"LANDING_{app.upper()}_URL", "").strip() for app in ("health", "wealth")},
            cookie_secure=_flag("COOKIE_SECURE", True),
            session_days=_int("SESSION_DAYS", 30),
            short_session_hours=_int("SHORT_SESSION_HOURS", 24),
            require_totp=policy if policy in TOTP_POLICIES else "shared",
            smtp_host=os.environ.get("SMTP_HOST", "").strip(),
            smtp_port=_int("SMTP_PORT", 587),
            smtp_username=os.environ.get("SMTP_USERNAME", "").strip(),
            smtp_password=os.environ.get("SMTP_PASSWORD", ""),
            smtp_from=os.environ.get("SMTP_FROM", "").strip(),
            resend_api_key=os.environ.get("RESEND_API_KEY", "").strip(),
            mail_from=os.environ.get("MAIL_FROM", "").strip(),
            oauth_issuer=os.environ.get("ACCOUNTS_OAUTH_ISSUER", "").strip().rstrip("/"),
            oauth_resources=os.environ.get("ACCOUNTS_OAUTH_RESOURCES", "").strip(),
            agent_plugin_url=os.environ.get("AGENT_PLUGIN_URL", "").strip(),
        )

    def problems(self) -> list[str]:
        """What is missing or wrong; an app refuses to start in production while this is not empty."""
        out = []
        if not self.database_url:
            out.append("ACCOUNTS_DATABASE_URL is not set")
        if len(self.session_secret) < 32:
            out.append("ACCOUNTS_SESSION_SECRET is not set or shorter than 32 characters")
        if not self.encryption_key:
            out.append("ACCOUNTS_ENCRYPTION_KEY is not set")
        elif not crypto.valid_key(self.encryption_key):
            out.append("ACCOUNTS_ENCRYPTION_KEY is not a Fernet key")
        return out
