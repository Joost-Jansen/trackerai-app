"""FastAPI dependencies — current-user resolution and per-request DB connection.

No function in database.py accepts an implicit "current user" anymore (see
database.py's module docstring) — every request gets its own connection,
scoped explicitly to the user identified by that request's cookie, and nothing
else. A missing/invalid cookie fails the request with 401 before any handler
or domain-module call runs.
"""

import re
import sqlite3
from dataclasses import dataclass
from typing import Generator

from fastapi import Depends, HTTPException, Request, Response, status

from app.core import auth_store, throttle
from app.core.accounts import APP, accounts, local_folder
from app.core.errors import CodedError

from trackerai_accounts.oauth import OAuth, PREFIX
from trackerai_accounts.routes import Session

from domain import database  # repo-root module, see app/__init__.py for the sys.path setup
from domain.i18n import tr


@dataclass(frozen=True)
class CurrentUser:
    username: str
    name: str
    is_admin: bool
    beta_features: list[str]
    # "cookie" (browser) or "agent" (Bearer agent token, see auth_store); for an
    # agent also the token's scope and id.
    via: str = "cookie"
    scope: str = ""
    token_id: str = ""
    # The shared trackerai account behind this data folder (core/accounts.py).
    account_id: int = 0
    account_admin: bool = False  # manages accounts in every tracker, not only wealth-tracker's


# What an agent token with scope "write" may change: bookkeeping, nothing
# else. That is labelling, budgets, rules (adding and deleting one), a
# category's name, group and type, the month layout and the other settings of
# Spending and Net worth, a balance on an account and a manual transaction.
# Everything not listed here (uploads, deleting transactions, categories or
# accounts, creating accounts or categories, bank connections, admin) stays
# browser-only. A "read" token changes nothing at all.
AGENT_WRITES = [
    ("PUT", re.compile(r"^/api/bank-transactions/category$")),
    ("PUT", re.compile(r"^/api/bank-transactions/\d+/category$")),
    ("POST", re.compile(r"^/api/labelling/decision$")),
    ("PUT", re.compile(r"^/api/budget/[^/]+$")),
    ("POST", re.compile(r"^/api/categories/rules$")),
    ("POST", re.compile(r"^/api/categories/relabel$")),  # after a new rule
    ("DELETE", re.compile(r"^/api/categories/rules/\d+$")),
    ("PUT", re.compile(r"^/api/categories/\d+/(type|name|group)$")),
    ("PUT", re.compile(r"^/api/month-periods$")),
    ("PUT", re.compile(r"^/api/spending/shared-costs$")),
    ("PUT", re.compile(r"^/api/spending/fixed-costs/choice$")),
    ("PUT", re.compile(r"^/api/accounts/\d+/balance$")),
    ("DELETE", re.compile(r"^/api/accounts/\d+/balance/\d{4}-\d{2}-\d{2}$")),  # a wrong balance
    ("POST", re.compile(r"^/api/bank-transactions$")),  # a manual transaction
]
# Never for an agent, not even to read: account and token management (export,
# deletion, two-step login), admin, and the bank connection (its keys and
# consent flow, also under its old Dutch path).
AGENT_BLOCKED = re.compile(r"^/api/(admin|agent-tokens|connections|koppelingen|account|auth/(change-password|delete))(/|$)")


def resolve_agent_token(request: Request, token: str, cfg: dict) -> tuple[str, dict]:
    """(username, token entry) for a valid agent token, counting failures per IP.

    A token is long and random, so guessing one is hopeless; the limit only stops
    someone from using the endpoint as a free CPU and log flood (S13: 20 failed
    attempts per 15 minutes per IP, then 429 before anything is looked up).
    """
    ip = throttle.client_ip(request)
    if throttle.AGENT_FAILURES_PER_IP.blocked(ip):
        raise CodedError(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_attempts",
                         tr("Too many failed attempts. Try again in a quarter of an hour."))
    if token.startswith(PREFIX):
        access = OAuth(accounts).resolve(token, APP)
        found = None if not access else (local_folder(Session(access["account"], access["apps"], {})),
            {"id": access["id"], "scope": access["scope"], "oauth": True})
    else:
        found = auth_store.resolve_agent_token(token, cfg)
    if not found:
        throttle.AGENT_FAILURES_PER_IP.hit(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, tr("Unknown or revoked agent token"), headers=OAuth(accounts).challenge(APP))
    return found


def _agent_user(request: Request) -> CurrentUser | None:
    header = request.headers.get("authorization") or ""
    if not header.lower().startswith("bearer "):
        return None
    cfg = auth_store.load_config()
    username, entry = resolve_agent_token(request, header[7:].strip(), cfg)
    user_cfg = cfg.get("credentials", {}).get("usernames", {}).get(username) or {}
    account = accounts.account_for_local_key(APP, username)
    if not account:
        # deleted, suspended, or no longer using wealth-tracker: the token goes with it
        throttle.AGENT_FAILURES_PER_IP.hit(throttle.client_ip(request))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, tr("Unknown or revoked agent token"))

    path, method = request.url.path, request.method.upper()
    if AGENT_BLOCKED.match(path):
        raise HTTPException(status.HTTP_403_FORBIDDEN, tr("Not available for an agent token."))
    if method not in ("GET", "HEAD"):
        allowed = entry.get("scope") == "write" and any(
            m == method and rx.match(path) for m, rx in AGENT_WRITES
        )
        if not allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                tr("This agent token may not change this.")
                + ("" if entry.get("scope") == "write" else tr(" It only has read access.")),
            )
    if not entry.get("oauth"):
        auth_store.record_agent_use(username, entry.get("id", ""))
    return CurrentUser(
        username=username,
        name=user_cfg.get("name", username),
        is_admin=False,  # a token never carries admin rights
        beta_features=auth_store.user_beta_features(username, cfg),
        via="agent",
        scope=entry.get("scope", ""),
        token_id=entry.get("id", ""),
        account_id=account["id"],
    )


def get_current_user(request: Request, response: Response) -> CurrentUser:
    """The caller: an agent by its Bearer token, else the shared trackerai session (core/accounts.py). Until the
    account has set up a two-step login it is required to have, or while it does not use wealth-tracker, only the
    account pages answer (403 `totp_setup_required` or `not_in_app`): the site shows those first."""
    from app.core.accounts import sessions

    # Explicit Bearer credentials keep their own identity and scope even when
    # a browser also supplies a cookie. A read-only connection must not acquire
    # the cookie's editing or admin permissions.
    agent = _agent_user(request)
    if agent:
        return agent
    s = sessions.ready(request, response)
    app = s.apps.get(APP)
    if not app:
        raise CodedError(status.HTTP_403_FORBIDDEN, "not_in_app", tr("This account does not use wealth-tracker yet."))
    folder = local_folder(s)
    cfg = auth_store.load_config_or_empty()
    user_cfg = cfg.get("credentials", {}).get("usernames", {}).get(folder) or {}
    return CurrentUser(
        username=folder,
        name=s.account.get("display_name") or user_cfg.get("name") or s.username,
        is_admin=auth_store.is_admin(folder, cfg),
        beta_features=auth_store.user_beta_features(folder, cfg),
        account_id=s.id,
        account_admin=bool(s.account["is_admin"]),
    )


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, tr("Admins only."))
    return user


def require_money(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Money (accounts, spending, budget, net worth) sits behind a beta flag, turned
    on per account under Admin.

    Set on every money router, not only in the sidebar: a hidden tab whose
    endpoints answer everyone is not gated, only unlinked.
    """
    if "money" not in user.beta_features:
        raise HTTPException(status.HTTP_403_FORBIDDEN, tr("Money is not turned on for this account."))
    return user


# Where the tour's example data may stand in for the user's own: the data pages,
# nothing personal. Auth, admin, onboarding, preferences, tokens, the bank
# connection, uploads, feedback and MCP always read the real user.
EXAMPLE_PATHS = (
    "/api/accounts", "/api/bank-transactions", "/api/benchmarks", "/api/budget", "/api/calendar",
    "/api/categories", "/api/dashboard", "/api/details", "/api/dividend", "/api/etf-analysis",
    "/api/holdings", "/api/labelling", "/api/month-periods", "/api/net-worth", "/api/news",
    "/api/portfolio", "/api/rebalancing", "/api/returns", "/api/spending",
)


def example_mode(request: Request, user: CurrentUser) -> bool:
    """The web client asks for example data (the tour's walk) on a data page."""
    if request.headers.get("x-example-data") != "1" or user.via != "cookie":
        return False
    path = request.url.path
    return any(path == p or path.startswith(p + "/") for p in EXAMPLE_PATHS)


def get_db(request: Request, user: CurrentUser = Depends(get_current_user)) -> Generator[sqlite3.Connection, None, None]:
    username = user.username
    if example_mode(request, user):
        # Example data can only be looked at.
        if request.method not in ("GET", "HEAD"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, tr("This is example data; it can't be changed."))
        from app.services import example_service
        example_service.ensure()
        username = example_service.USER
    # same_thread_only=False because FastAPI runs a sync dependency's setup and
    # its post-yield teardown as separate threadpool tasks, which are not
    # guaranteed to land on the same thread — with sqlite3's default check that
    # made conn.close() below raise ProgrammingError under concurrent requests
    # (the dashboard fires its 4 chart endpoints at once), failing them 500 at
    # random. The connection stays private to this request and is only ever
    # touched by one thread at a time, so lifting the check is safe here.
    conn = database.connect(username, same_thread_only=False)
    database.init_db(conn)
    try:
        yield conn
    finally:
        conn.close()
