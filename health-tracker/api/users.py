"""Who is calling.

Who someone is lives in the shared trackerai account (packages/accounts): login, password, two-step login and which
apps someone uses, with one session for every tracker. What is health-tracker's own is here: its `users` row for an
account (made on the account's first visit, linked by the account's `local_key`) and the `current_user` dependency of
every route. The people themselves are managed on the shared admin page (packages/marketing, /api/trackerai/admin).

`current_user` (built by `make_auth`) returns a `User` with that user's own `DataStore`, so a route can only reach the
caller's data. Browser: the shared session cookie. Agents: Bearer token from `agent_tokens` (or the legacy env hash,
which belongs to the first admin); a token works while its account does.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from api import auth, betas, example
from api.data import DataStore
from api.errors import ApiError
from tools import db, secretbox
from trackerai_accounts import Accounts, Sessions
from trackerai_accounts.oauth import PREFIX, OAuth
from trackerai_accounts.routes import Session
from trackerai_accounts.service import PRIVACY_VERSION
from trackerai_websec.client_ip import client_ip, trusted_networks
from trackerai_websec.throttle import Limiter

APP = "health"  # this app's name in the accounts
LOCALES = ("nl", "en")


@dataclass
class Guards:
    """Rate limits and the client address. Login limits live in the accounts; what is left here is for agent tokens.

    In memory: a restart forgets them; the durable layer is a rate-limit rule at the edge (Cloudflare)."""

    trusted: list = field(default_factory=list)  # TRUSTED_PROXIES
    token_ip: Limiter = field(default_factory=lambda: Limiter(20, 15 * 60))  # failed agent/MCP tokens

    @classmethod
    def from_env(cls, trusted_proxies: str) -> Guards:
        return cls(trusted=trusted_networks(trusted_proxies))

    def ip(self, request: Request) -> str:
        return client_ip(request, self.trusted)

    def too_many(self, limiter: Limiter, key: str) -> ApiError:
        return ApiError(429, "too_many_attempts", headers={"Retry-After": str(limiter.remaining_s(key) or 60)})


@dataclass
class User:
    id: int  # health-tracker's own user id
    username: str
    display_name: str | None
    is_admin: bool  # health-tracker's admin pages (feedback, its people)
    via: str  # cookie | agent
    store: DataStore = field(repr=False)
    example: bool = False  # the store is the read-only example account (api/example.py), not this user's data
    totp_enabled: bool = False
    account_id: int = 0
    account_admin: bool = False  # manages everyone's account, in every tracker
    agent_scope: str = "write"  # legacy health tokens keep their previous access
    agent_oauth: bool = False

    @property
    def scope(self) -> db.Scope:
        return self.store.scope

    @property
    def author(self) -> str:
        """Who wrote something: shown next to log entries, plans and documents."""
        return "agent" if self.via == "agent" else self.username

    def public(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "is_admin": self.is_admin,
            "via": self.via,
            "totp_enabled": self.totp_enabled,
            "account_admin": self.account_admin,
        }


class Stores:
    """One DataStore (with its short cache) per user."""

    def __init__(self, engine):
        self.engine = engine
        self._stores: dict[int, DataStore] = {}

    def get(self, user_id: int) -> DataStore:
        if user_id not in self._stores:
            self._stores[user_id] = DataStore(db.Scope(self.engine, user_id))
        return self._stores[user_id]

    def drop(self, user_id: int) -> None:
        self._stores.pop(user_id, None)


def check_locale(locale: str | None) -> None:
    if locale is not None and locale not in LOCALES:
        raise ApiError(422, "invalid_locale", options=list(LOCALES))


def privacy_info() -> dict:
    """Who runs this installation (the controller under the GDPR): PRIVACY_CONTROLLER, PRIVACY_CONTACT."""
    return {
        "controller": os.environ.get("PRIVACY_CONTROLLER", "").strip() or None,
        "contact": os.environ.get("PRIVACY_CONTACT", "").strip() or None,
        "version": PRIVACY_VERSION,
    }


def bootstrap(engine, accounts: Accounts, username: str, password_hash: str, key: str = "") -> int:
    """At startup. A fresh installation's first admin comes from the environment (TRAINING_USER,
    TRAINING_PASSWORD_HASH): health-tracker's user 1 (data migrated from the single-user database already belongs to
    it). Without them, the first person to register becomes admin. Then `bring_in` moves every login from before the
    shared accounts over; returns how many."""
    if username and password_hash and not db.count_users(engine) and not accounts.count():
        db.create_user(engine, username, password_hash, is_admin=True, user_id=1)
    return bring_in(engine, accounts, key)


def bring_in(engine, accounts: Accounts, key: str = "") -> int:
    """Every health-tracker user with a login from before the shared accounts gets an account with that login: its
    current password hash, its two-step login (re-encrypted with the accounts' key), its admin flag, language and
    suspension. Users the accounts made (no password of their own) and the example account have nothing to move.
    A name the accounts already have is left alone and reported: the same name can be someone else in another
    tracker (packages/accounts migrate.py settles that). The first admin moved becomes the accounts' admin while
    there is none. Running it again moves nothing twice."""
    moved = 0
    for listed in db.list_users(engine):
        uid, name = listed["id"], listed["username"]
        if name == example.USERNAME or name.startswith("_") or accounts.account_id_for_local_key(APP, str(uid)) is not None:
            continue
        row = db.get_user(engine, uid, with_hash=True)
        if not row.get("password_hash") or row["password_hash"] == "!":
            continue
        if accounts.by_username(name):
            print(f"accounts: health-tracker's {name!r} not moved: the accounts already have that name", flush=True)
            continue
        secret = None
        if row.get("totp_enabled_at") and row.get("totp_secret"):
            try:
                secret = secretbox.decrypt(row["totp_secret"], key)
            except secretbox.WrongKey:
                print(f"accounts: {name!r} sets up two-step login again (its secret is not readable with this key)", flush=True)
        first = bool(row["is_admin"]) and not any(a["is_admin"] for a in accounts.list_accounts())
        accounts.create_linked(
            name,
            row["password_hash"],
            APP,
            str(uid),
            is_admin=first,
            app_admin=bool(row["is_admin"]),
            display_name=row.get("display_name"),
            locale=db.get_setting(db.Scope(engine, uid), "locale"),
            suspended=bool(row["suspended"]),
            totp_secret=secret,
            totp_backup=row.get("totp_backup") if secret else None,
        )
        moved += 1
    return moved


def make_auth(
    engine,
    stores: Stores,
    accounts: Accounts,
    sessions: Sessions,
    legacy_agent_hash: str = "",
    examples: example.ExampleData | None = None,
    guards: Guards | None = None,
) -> tuple[Callable, Callable, Callable]:
    """Returns (current_user dependency, token_user(token) -> User | None, local_user(session) -> user id). With
    `examples`, a site login that asks for example data on a data route gets the example account's read-only store
    instead of its own (api/example.py)."""
    guards = guards or Guards()
    making = threading.Lock()

    def local_user(s: Session) -> int:
        """health-tracker's own user for this account, made on its first visit."""
        key = (s.apps.get(APP) or {}).get("local_key")
        if key and key.isdigit() and db.get_user(engine, int(key)):
            return int(key)
        with making:  # two first requests at once make one user
            key = accounts.local_key(s.id, APP)
            if key and key.isdigit() and db.get_user(engine, int(key)):
                return int(key)
            name, n = s.username, 1
            while db.get_user_by_name(engine, name):
                n += 1
                name = f"{s.username}-{n}"
            app = s.apps.get(APP) or {}
            uid = db.create_user(
                engine,
                name,
                "!",
                display_name=s.account.get("display_name"),
                consent_at=app.get("consent_at"),
                privacy_version=app.get("privacy_version"),
            )
            accounts.set_local_key(s.id, APP, str(uid))
            return uid

    def load(user_id: int | None, via: str) -> User | None:
        u = db.get_user(engine, user_id) if user_id else None
        if not u:
            return None
        account = accounts.account_for_local_key(APP, str(user_id))
        if not account:
            return None  # deleted, suspended, or no longer using health-tracker
        app_admin = bool((accounts.apps(account["id"]).get(APP) or {}).get("is_admin"))
        return User(
            u["id"],
            account["username"],
            account.get("display_name"),
            app_admin,
            via,
            stores.get(u["id"]),
            totp_enabled=bool(account.get("totp_enabled_at")),
            account_id=account["id"],
        )

    def token_user(token: str | None) -> User | None:
        if not token:
            return None
        if token.startswith(PREFIX):
            access = OAuth(accounts).resolve(token, APP)
            if not access:
                return None
            uid = local_user(Session(access["account"], access["apps"], {}))
            u = load(uid, "agent")
            if u:
                u.is_admin, u.agent_scope, u.agent_oauth = False, access["scope"], True
            return u
        digest = hashlib.sha256(token.encode()).hexdigest()
        found = db.token_for_hash(engine, digest)
        uid, access = (found["user_id"], found["scope"]) if found else (None, "write")
        if uid is None and legacy_agent_hash and auth.same(digest, legacy_agent_hash):
            uid = next((u["id"] for u in db.list_users(engine) if u["is_admin"]), None)
        u = load(uid, "agent")
        if u:
            u.agent_scope = access  # a read token sees no write tools (mcp.py) and may not write (guards)
        return u

    def current_user(request: Request, response: Response) -> User:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            ip = guards.ip(request)
            if guards.token_ip.blocked(ip):
                raise guards.too_many(guards.token_ip, ip)
            u = token_user(header[7:].strip())
            if not u:
                guards.token_ip.hit(ip)  # someone guessing tokens
                raise ApiError(401, "invalid_agent_token", headers=OAuth(accounts).challenge(APP))
            if u.agent_oauth and request.url.path != "/api/mcp":
                raise ApiError(403, "tokens_site_only")
            # A read-only token reads: outside MCP (which hides and refuses its write tools) only GET and HEAD.
            if u.agent_scope == "read" and request.url.path != "/api/mcp" and request.method not in ("GET", "HEAD"):
                raise ApiError(403, "read_only_token")
            return u
        s = sessions.ready(request, response)  # 401 without a session; 403 until required two-step login is on
        app = s.apps.get(APP)
        if not app:
            raise ApiError(403, "not_in_app")
        if app["consent_at"] is None:
            raise ApiError(403, "consent_required")  # given health-tracker by an admin: consents on the first visit
        uid = local_user(s)
        u = User(
            uid,
            s.username,
            s.account.get("display_name"),
            bool(app["is_admin"]),
            "cookie",
            stores.get(uid),
            totp_enabled=bool(s.account.get("totp_enabled_at")),
            account_id=s.id,
            account_admin=bool(s.account["is_admin"]),
        )
        if examples is not None and example.serves(request):
            # only the data comes from the example account; never another real user's, and never writable
            return User(example.EXAMPLE_USER_ID, u.username, u.display_name, False, "cookie", examples.store(), example=True)
        return u

    return current_user, token_user, local_user


# --- routes ------------------------------------------------------------------------------------------------------


class AccountPatch(BaseModel):
    display_name: str | None = None
    locale: str | None = None


def make_router(engine, stores: Stores, accounts: Accounts, sessions: Sessions, current_user: Callable, local_user: Callable) -> APIRouter:
    r = APIRouter()

    def person(u: User = Depends(current_user)) -> User:
        if u.via != "cookie":
            raise ApiError(403, "site_login_only")
        return u

    @r.get("/api/auth/config")
    def auth_config():
        """Public: what the login and registration pages should offer, who runs this installation (privacy page), and
        the front door to link to (trackerai.nl, its admin page; null for a tracker on its own)."""
        return {
            "registration": accounts.registration_mode(),
            "first_user": accounts.count() == 0,
            "privacy": privacy_info(),
            "session_days": accounts.config.session_days,
            "front_door_url": accounts.config.front_door_url,
        }

    @r.get("/api/me")
    def me(request: Request, response: Response):
        """Who is logged in. Also before health-tracker opens for them: then it says what is missing first (two-step
        login, consent, or joining health-tracker at all), and the site shows that instead of the pages."""
        if request.headers.get("authorization", "").lower().startswith("bearer "):
            u = current_user(request, response)
            return {**u.public(), "betas": betas.of_user(engine, u.id)}
        s = sessions.current(request, response)
        view = accounts.view(s.account, s.apps)
        app = s.apps.get(APP)
        out = {
            "id": None,
            "username": s.username,
            "display_name": s.account.get("display_name"),
            "is_admin": False,
            "via": "cookie",
            "locale": s.account.get("locale"),
            "account_admin": view["is_admin"],
            "apps": view["apps"],
            "totp_enabled": view["totp_enabled"],
            "email_codes": view["email_codes"],
            "two_step": view["two_step"],
            "email": view["email"],
            "email_verify_required": view["email_verify_required"],
            "totp_required": view["totp_required"],
            "totp_setup_required": view["totp_setup_required"],
            "in_app": app is not None,
            "consent_needed": app is not None and app["consent_at"] is None,
            "betas": [],
        }
        if app is not None and not out["consent_needed"] and not out["totp_setup_required"] and not out["email_verify_required"]:
            out["id"], out["is_admin"] = local_user(s), bool(app["is_admin"])
            out["betas"] = betas.of_user(engine, out["id"])  # gate a beta feature on the site with these
        return out

    @r.patch("/api/account")
    def update_account(body: AccountPatch, u: User = Depends(person)):
        check_locale(body.locale)
        account = accounts.update_profile(u.account_id, body.display_name, body.locale)
        if body.display_name is not None:
            db.update_user(engine, u.id, display_name=account.get("display_name"))
        return {
            **db.get_user(engine, u.id),
            "username": account["username"],
            "display_name": account.get("display_name"),
            "locale": account.get("locale"),
        }

    return r
