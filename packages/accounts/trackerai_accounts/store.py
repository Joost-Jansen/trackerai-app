"""The accounts database: who someone is, shared by every app. What someone has stays in each app's own database.

    accounts        one row per person: username, password, two-step login, admin, suspended, language
    email_codes     login codes sent by email, and codes confirming an address (hashed, short-lived, used once)
    account_apps    which apps an account uses, and the app's own key for it (`local_key`: health-tracker's user id,
                    wealth-tracker's data folder); `leaving_at` while the app still has to delete its data
    invites         one-use invitation codes, with the apps they open
    settings        installation settings (registration mode)
    audit           what admins did
    daily_use       page visits per day, app and account: a count, never which pages (the admin page's usage figures)

SQLAlchemy Core, so the same code runs on Postgres (production) and SQLite (one machine, tests).
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.engine import Engine

meta = MetaData()

accounts = Table(
    "accounts",
    meta,
    Column("id", Integer, primary_key=True),
    Column("username", String(40), nullable=False, unique=True),
    Column("display_name", String(80)),
    Column("password_hash", String(100), nullable=False),
    # Passwords this person had in an app before the accounts were joined: each still opens the account until the
    # password is changed (see migrate.py).
    Column("legacy_password_hashes", JSON),
    Column("password_changed_at", DateTime(timezone=True)),
    # Raised on a password change, two-step login on or off, and an admin reset: ends every session issued before.
    Column("session_version", Integer, nullable=False, default=0),
    Column("totp_secret", Text),  # encrypted (crypto.py); set between setup and enable too
    Column("totp_enabled_at", DateTime(timezone=True)),
    Column("totp_last_step", BigInteger),  # a code is good once
    Column("totp_backup", JSON),  # hashes of the unused backup codes
    # Two-step login by email: a code is mailed at login. The address is confirmed with a code before it is saved.
    Column("email", String(254)),
    Column("email_verified_at", DateTime(timezone=True)),
    Column("email_codes_at", DateTime(timezone=True)),  # login codes by email are on
    Column("is_admin", Boolean, nullable=False, default=False),  # manages accounts, for every app
    Column("suspended", Boolean, nullable=False, default=False),
    Column("locale", String(5)),
    Column("failed_logins", Integer, nullable=False, default=0),
    Column("failed_since", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True)),
    Column("last_login_at", DateTime(timezone=True)),
    Column("deleted_at", DateTime(timezone=True)),  # deleting: the apps still remove their data
)

account_apps = Table(
    "account_apps",
    meta,
    Column("account_id", Integer, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
    Column("app", String(20), primary_key=True),
    Column("local_key", String(80)),
    Column("is_admin", Boolean, nullable=False, default=False),  # the app's own admin pages (feedback, beta flags)
    Column("consent_at", DateTime(timezone=True)),
    Column("privacy_version", String(20)),
    Column("enabled_at", DateTime(timezone=True)),
    Column("leaving_at", DateTime(timezone=True)),
)

Index("ix_accounts_email", accounts.c.email, unique=True)

email_codes = Table(
    "email_codes",
    meta,
    Column("id", Integer, primary_key=True),
    Column("account_id", Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("purpose", String(10), nullable=False),  # "login", or "verify" for a new address
    Column("email", String(254), nullable=False),  # where it went
    Column("code_hash", String(64), nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
)

invites = Table(
    "invites",
    meta,
    Column("code", String(40), primary_key=True),
    Column("created_by", Integer),
    Column("created_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True)),
    Column("used_by", Integer),
    Column("used_at", DateTime(timezone=True)),
    Column("apps", JSON),
)

settings = Table("settings", meta, Column("key", String(64), primary_key=True), Column("value", JSON, nullable=False))

audit = Table(
    "audit",
    meta,
    Column("id", Integer, primary_key=True),
    Column("at", DateTime(timezone=True)),
    Column("actor", String(40)),
    Column("action", String(40)),
    Column("target", String(40)),
    Column("detail", String(200)),
)

# One row per day, app and account that visited: how often, nothing about what. Deleting the account deletes its rows.
daily_use = Table(
    "daily_use",
    meta,
    Column("day", Date, primary_key=True),
    Column("app", String(20), primary_key=True),
    Column("account_id", Integer, ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True),
    Column("visits", Integer, nullable=False),
)


oauth_clients = Table(
    "oauth_clients",
    meta,
    Column("id", String(80), primary_key=True),
    Column("name", String(100), nullable=False),
    Column("redirects", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

oauth_requests = Table(
    "oauth_requests",
    meta,
    Column("digest", String(64), primary_key=True),
    Column("query", Text, nullable=False),
    Column("account_id", Integer, ForeignKey("accounts.id", ondelete="CASCADE")),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
)

oauth_grants = Table(
    "oauth_grants",
    meta,
    Column("id", String(80), primary_key=True),
    Column("account_id", Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("client_id", String(80), ForeignKey("oauth_clients.id"), nullable=False),
    Column("app", String(20), nullable=False),
    Column("resource", Text, nullable=False),
    Column("scope", String(80), nullable=False),
    Column("session_version", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_used_at", DateTime(timezone=True)),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
)

oauth_codes = Table(
    "oauth_codes",
    meta,
    Column("digest", String(64), primary_key=True),
    Column("grant_id", String(80), ForeignKey("oauth_grants.id", ondelete="CASCADE"), nullable=False),
    Column("redirect_uri", Text, nullable=False),
    Column("challenge", String(128), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
)

oauth_tokens = Table(
    "oauth_tokens",
    meta,
    Column("digest", String(64), primary_key=True),
    Column("refresh_digest", String(64), unique=True, nullable=False),
    Column("grant_id", String(80), ForeignKey("oauth_grants.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("scope", String(80), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("used_at", DateTime(timezone=True)),
)


def connect(url: str) -> Engine:
    """An engine for the accounts database, with its tables created."""
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    if url.startswith("sqlite"):
        engine = create_engine(url, future=True, connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _fk(dbapi, _):
            dbapi.execute("PRAGMA foreign_keys=ON")
    else:
        engine = create_engine(url, future=True, pool_pre_ping=True)
    meta.create_all(engine)
    _add_columns(engine)
    return engine


# Columns added after the first release: create_all makes new tables, not new columns in existing ones.
LATER_COLUMNS = {"accounts": ("email", "email_verified_at", "email_codes_at")}


def _add_columns(engine: Engine) -> None:
    for table_name, names in LATER_COLUMNS.items():
        table = meta.tables[table_name]
        have = {c["name"] for c in inspect(engine).get_columns(table_name)}
        missing = [table.c[n] for n in names if n not in have]
        if not missing:
            continue
        with engine.begin() as c:
            for col in missing:
                kind = col.type.compile(dialect=engine.dialect)
                c.execute(text(f'ALTER TABLE {table_name} ADD COLUMN "{col.name}" {kind}'))
        for index in table.indexes:
            index.create(engine, checkfirst=True)
