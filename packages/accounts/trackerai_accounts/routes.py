"""The account routes every app mounts, the same paths everywhere:

    GET    /api/auth/registration-status     {mode, first_user, session_days, email_codes, password_reset, front_door_url,
                                              tracker_urls}
    POST   /api/auth/login                   {username, password, totp?, remember?, send_email?}
    POST   /api/auth/logout
    POST   /api/auth/register                {username, password, email, display_name?, invite?, locale?, consent?, app?,
                                              apps?}: apps, the trackers to start with (default: this app)
    POST   /api/auth/password/forgot         {login}: a username or email address; a code goes to the account's confirmed
                                              address. Always {ok: true}, whether or not that account exists
    POST   /api/auth/password/reset          {login, code, new_password}: the new password; every session ends
    GET    /api/auth/account                 the account (`Accounts.view`)
    PATCH  /api/auth/account                 {display_name?, locale?}
    POST   /api/account/password             {current, new}
    GET    /api/account/totp                 {enabled, required, backup_codes_left}
    POST   /api/account/totp/setup           -> {secret, otpauth_uri}
    POST   /api/account/totp/enable          {code} -> {backup_codes}, shown once
    POST   /api/account/totp/disable         {password, code}
    POST   /api/account/totp/backup-codes    {code} -> {backup_codes}, the old ones stop working
    POST   /api/account/email                {email, password, code?}: codes by email, a code goes to that address
    POST   /api/account/email/confirm        {code}: the address is confirmed, codes by email are on
    POST   /api/account/email/disable        {password, code}: off, the address is forgotten
    POST   /api/account/email/code           a login code by email, for a step that asks for one (deleting, leaving)
    POST   /api/account/email/resend         {email?}: the welcome code again (and a corrected address), until confirmed
    POST   /api/account/apps/{app}           {consent?}: start using another app
    DELETE /api/account/apps/{app}           {password, totp?}: stop using it; its data is deleted
    DELETE /api/account                      {password, totp?}: the whole account, in every app
    POST   /api/account/visit                one page visit in this app, for the admin page's usage figures (a count)
    /api/admin/accounts...                   the admin's tools (account admins only); also at /api/trackerai/admin/...,
                                              where no app's own admin routes shadow them (trackerai.nl/admin)
    GET    /api/admin/usage                  page visits and active accounts per app and week (`Accounts.usage`)

`make_router` also returns the dependencies the app builds its own on:

    current = Depends(sessions.current)      the logged-in account (401 without one); renews the cookie
    ready = Depends(sessions.ready)          the same, but 403 `totp_setup_required` until two-step login is set up
                                             where it is required: put it on everything except the account pages
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Request, Response
from pydantic import BaseModel

from trackerai_accounts import session
from trackerai_accounts.errors import AccountError
from trackerai_accounts.limits import Limiter
from trackerai_accounts.service import Accounts

log = logging.getLogger(__name__)


@dataclass
class Session:
    account: dict
    apps: dict
    claims: dict = field(repr=False)

    @property
    def id(self) -> int:
        return self.account["id"]

    @property
    def username(self) -> str:
        return self.account["username"]


class Credentials(BaseModel):
    username: str
    password: str
    totp: str | None = None  # the authenticator code (or a backup code) when two-step login is on
    remember: bool = True  # "stay logged in" (SESSION_DAYS); also: do not ask this browser for the code again for as long
    send_email: bool = False  # mail a login code (an account with both the app and codes by email)


class Registration(BaseModel):
    username: str
    password: str
    display_name: str | None = None
    name: str | None = None  # wealth-tracker's form calls it so
    invite: str | None = None
    invite_code: str | None = None  # likewise
    locale: str | None = None
    consent: bool = False
    app: str | None = None
    email: str | None = None  # required; the welcome mail confirms it
    apps: list[str] | None = None  # the trackers to start with (the front door's choice); default: this app


class ForgotPassword(BaseModel):
    login: str  # a username or an email address


class PasswordReset(BaseModel):
    login: str
    code: str
    new_password: str


class Profile(BaseModel):
    display_name: str | None = None
    locale: str | None = None


class PasswordChange(BaseModel):
    current: str
    new: str


class Code(BaseModel):
    code: str


class Reauth(BaseModel):
    password: str
    totp: str | None = None
    code: str | None = None  # the name health-tracker's two-step form uses


class EmailStart(BaseModel):
    email: str
    password: str
    code: str | None = None  # when two-step login is on already


class EmailResend(BaseModel):
    email: str | None = None


class Join(BaseModel):
    consent: bool = False


class AdminFlags(BaseModel):
    is_admin: bool | None = None
    suspended: bool | None = None


class AdminApp(BaseModel):
    enabled: bool | None = None
    is_admin: bool | None = None


class Mode(BaseModel):
    registration: str


class InviteIn(BaseModel):
    days: int | None = 14
    apps: list[str] | None = None


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@dataclass
class Guards:
    """Per-IP limits in memory (the per-account login limit lives in the database, shared by every app)."""

    login_ip: Limiter = field(default_factory=lambda: Limiter(30, 15 * 60))
    login_name: Limiter = field(default_factory=lambda: Limiter(10, 15 * 60))  # also for names that do not exist
    register_ip: Limiter = field(default_factory=lambda: Limiter(5, 60 * 60))
    forgot_ip: Limiter = field(default_factory=lambda: Limiter(10, 15 * 60))  # every request counts
    reset_ip: Limiter = field(default_factory=lambda: Limiter(30, 15 * 60))  # wrong codes
    reset_name: Limiter = field(default_factory=lambda: Limiter(10, 15 * 60))  # wrong codes per login, also unknown ones


def too_many(limiter: Limiter, key: str) -> AccountError:
    remaining = getattr(limiter, "remaining_s", None)  # an app may pass limiters of its own (any with blocked/hit/reset)
    return AccountError(429, "too_many_attempts", headers={"Retry-After": str((remaining(key) if remaining else 0) or 60)})


class Sessions:
    """The dependencies: who is logged in."""

    def __init__(self, accounts: Accounts):
        self.accounts = accounts

    def resolve(self, request: Request) -> Session | None:
        c = session.claims(request.cookies.get(session.COOKIE), self.accounts.config)
        account = self.accounts.session_account(c)
        if not account:
            return None
        return Session(account, self.accounts.apps(account["id"]), c)

    def resolve_account(self, account: dict) -> Session:
        """A Session for an account an app just made or changed (its registration), without a cookie yet."""
        return Session(account, self.accounts.apps(account["id"]), {})

    def current(self, request: Request, response: Response) -> Session:
        s = self.resolve(request)
        if not s:
            raise AccountError(401, "not_logged_in")
        if session.due_for_renewal(s.claims, self.accounts.config):  # sliding: renewed while in use
            session.issue(
                response, self.accounts.config, s.id, s.account["session_version"] or 0, s.claims.get("auth"), session.remembered(s.claims)
            )
        return s

    def ready(self, request: Request, response: Response) -> Session:
        s = self.current(request, response)
        if self.accounts.email_verify_required(s.account):
            raise AccountError(403, "email_verify_required")
        if self.accounts.totp_required(s.account, s.apps) and not self.accounts.two_step(s.account):
            raise AccountError(403, "totp_setup_required")
        return s


def make_router(
    accounts: Accounts,
    app: str | None,
    client_ip: Callable[[Request], str] = _client_ip,
    guards: Guards | None = None,
    aliases: dict[str, str] | None = None,
    after_leave: Callable[[], None] | None = None,
    before_login: Callable[[str, str], None] | None = None,
) -> tuple[APIRouter, Sessions]:
    """The routes for `app` ("health" or "wealth": where someone registers, and the app they get). `app=None` is the
    front door's own API (trackerai-api): a sign-up must name its trackers (`apps`), and there is no OAuth issuer for
    agents, which is each app's own. `aliases` answers
    an app's older paths too, e.g. {"/api/login": "/api/auth/login"}, while its clients move over. `after_leave` runs
    after someone left an app or an account was deleted: the app deletes its part at once instead of at its next sweep.
    `before_login(username, password)` runs before a login is checked: an app can turn a login of its own from before
    the accounts into an account there (it must check the password itself, and leave taken names alone)."""
    r = APIRouter()
    guards = guards or Guards()
    sessions = Sessions(accounts)

    def swept() -> None:
        if after_leave:
            after_leave()

    def fresh_session(response: Response, account: dict, auth_time: int | None = None, remember: bool = True) -> None:
        session.issue(response, accounts.config, account["id"], account["session_version"] or 0, auth_time, remember)

    def admin(s: Session = Depends(sessions.ready)) -> Session:
        if not s.account["is_admin"]:
            raise AccountError(403, "admins_only")
        return s

    # --- login and registration ------------------------------------------------------------------------------------

    @r.get("/api/auth/registration-status")
    def registration_status():
        return {
            "mode": accounts.registration_mode(),
            "first_user": accounts.count() == 0,
            "session_days": accounts.config.session_days,
            "email_codes": bool(accounts.mailer),
            "password_reset": accounts.password_reset_available(),
            "front_door_url": accounts.config.front_door_url,
            "tracker_urls": accounts.config.tracker_urls,
        }

    @r.post("/api/auth/login")
    def login(creds: Credentials, request: Request, response: Response):
        name, ip = creds.username.strip().lower()[:40], client_ip(request)
        for limiter, who in ((guards.login_name, name), (guards.login_ip, ip)):
            if limiter.blocked(who):
                raise too_many(limiter, who)
        if before_login:
            before_login(name, creds.password)
        device = request.cookies.get(session.DEVICE_COOKIE)
        try:
            account = accounts.login(
                name,
                creds.password,
                creds.totp,
                trusted_device=lambda a: session.device_trusted(device, accounts.config, a),
                send_email=creds.send_email,
            )
        except AccountError as e:
            if e.code in ("bad_credentials", "totp_invalid"):
                guards.login_name.hit(name)
                guards.login_ip.hit(ip)
            raise
        guards.login_name.reset(name)
        fresh_session(response, account, remember=creds.remember)
        if creds.remember and (creds.totp or "").strip() and accounts.two_step(account):
            session.issue_device(response, accounts.config, account["id"], account["session_version"] or 0)
        v = accounts.view(account)
        return {"ok": True, "username": account["username"], "totp_setup_required": v["totp_setup_required"], "apps": v["apps"]}

    @r.post("/api/auth/logout")
    def logout(response: Response):
        session.clear(response, accounts.config)
        return {"ok": True}

    @r.post("/api/auth/register")
    def register(body: Registration, request: Request, response: Response):
        ip = client_ip(request)
        if not guards.register_ip.hit(ip):  # every attempt counts: also guessing invite codes
            raise too_many(guards.register_ip, ip)
        account = accounts.register(
            body.username,
            body.password,
            body.app or app,
            display_name=body.display_name or body.name,
            invite=body.invite or body.invite_code,
            locale=body.locale,
            consent=body.consent,
            email=body.email,
            apps=body.apps,
        )
        fresh_session(response, account)
        v = accounts.view(account)
        return {
            "ok": True,
            "username": account["username"],
            "is_admin": v["is_admin"],
            "totp_setup_required": v["totp_setup_required"],
            "email_verify_required": v["email_verify_required"],
        }

    # --- a forgotten password --------------------------------------------------------------------------------------

    def send_reset_code(login: str) -> None:
        try:
            accounts.forgot_password(login)
        except Exception as e:  # after the answer went out: only the log knows (never the login, it may be an address)
            log.error("Sending a password reset code failed: %s", type(e).__name__)

    @r.post("/api/auth/password/forgot")
    def password_forgot(body: ForgotPassword, request: Request, background: BackgroundTasks):
        """The same answer for every login, given before the account is even looked up: neither the answer nor its
        timing tells whether that account exists or has an address."""
        ip = client_ip(request)
        if not guards.forgot_ip.hit(ip):
            raise too_many(guards.forgot_ip, ip)
        background.add_task(send_reset_code, body.login.strip().lower()[:254])
        return {"ok": True}

    @r.post("/api/auth/password/reset")
    def password_reset(body: PasswordReset, request: Request):
        """A new password with the code from the mail. Not logged in after: the login page asks for the password, and
        for the two-step code where the account has one."""
        name, ip = body.login.strip().lower()[:254], client_ip(request)
        for limiter, who in ((guards.reset_name, name), (guards.reset_ip, ip)):
            if limiter.blocked(who):
                raise too_many(limiter, who)
        try:
            account = accounts.reset_forgotten_password(name, body.code, body.new_password)
        except AccountError as e:
            if e.code == "reset_code_invalid":
                guards.reset_name.hit(name)
                guards.reset_ip.hit(ip)
            raise
        guards.reset_name.reset(name)
        guards.login_name.reset(account["username"])  # earlier wrong passwords no longer stand in the way
        return {"ok": True}

    # --- the account -----------------------------------------------------------------------------------------------

    @r.get("/api/auth/account")
    def account_view(s: Session = Depends(sessions.current)):
        return accounts.view(s.account, s.apps)

    @r.patch("/api/auth/account")
    def account_update(body: Profile, s: Session = Depends(sessions.current)):
        return accounts.view(accounts.update_profile(s.id, body.display_name, body.locale))

    @r.post("/api/account/password")
    def change_password(body: PasswordChange, response: Response, s: Session = Depends(sessions.current)):
        """Every other session ends (a stolen cookie with it); this browser gets a new one."""
        fresh_session(response, accounts.change_password(s.id, body.current, body.new), remember=session.remembered(s.claims))
        return {"ok": True}

    @r.get("/api/account/totp")
    def totp_status(s: Session = Depends(sessions.current)):
        v = accounts.view(s.account, s.apps)
        return {
            "enabled": v["totp_enabled"],
            "required": v["totp_required"],
            "backup_codes_left": v["totp_backup_codes_left"],
            "email_codes": v["email_codes"],
            "email": v["email"],
            "email_available": bool(accounts.mailer),
        }

    @r.post("/api/account/totp/setup")
    def totp_setup(s: Session = Depends(sessions.current)):
        return accounts.totp_setup(s.id)

    @r.post("/api/account/totp/enable")
    def totp_enable(body: Code, response: Response, s: Session = Depends(sessions.current)):
        codes = accounts.totp_enable(s.id, body.code)
        fresh_session(response, accounts.get(s.id), s.claims.get("auth"), session.remembered(s.claims))
        return {"backup_codes": codes}

    @r.post("/api/account/totp/disable")
    def totp_disable(body: Reauth, response: Response, s: Session = Depends(sessions.current)):
        fresh_session(
            response,
            accounts.totp_disable(s.id, body.password, body.code or body.totp or ""),
            s.claims.get("auth"),
            session.remembered(s.claims),
        )
        return {"ok": True}

    @r.post("/api/account/totp/backup-codes")
    def backup_codes(body: Code, s: Session = Depends(sessions.current)):
        return {"backup_codes": accounts.new_backup_codes(s.id, body.code)}

    @r.post("/api/account/email")
    def email_start(body: EmailStart, s: Session = Depends(sessions.current)):
        return {"sent_to": accounts.email_start(s.id, body.password, body.email, body.code)}

    @r.post("/api/account/email/confirm")
    def email_confirm(body: Code, response: Response, s: Session = Depends(sessions.current)):
        account = accounts.email_confirm(s.id, body.code)
        fresh_session(response, account, s.claims.get("auth"), session.remembered(s.claims))
        return accounts.view(account)

    @r.post("/api/account/email/disable")
    def email_disable(body: Reauth, response: Response, s: Session = Depends(sessions.current)):
        account = accounts.email_disable(s.id, body.password, body.code or body.totp or "")
        fresh_session(response, account, s.claims.get("auth"), session.remembered(s.claims))
        return {"ok": True}

    @r.post("/api/account/email/resend")
    def email_resend(body: EmailResend = Body(default_factory=lambda: EmailResend()), s: Session = Depends(sessions.current)):
        return {"sent_to": accounts.resend_signup_code(s.id, body.email)}

    @r.post("/api/account/email/code")
    def email_code(s: Session = Depends(sessions.current)):
        return {"sent_to": accounts.send_login_code(s.account)}

    @r.post("/api/account/apps/{name}")
    def join(name: str, body: Join = Body(default_factory=Join), s: Session = Depends(sessions.current)):
        accounts.join_app(s.id, name, body.consent)
        return accounts.view(accounts.get(s.id))

    @r.delete("/api/account/apps/{name}")
    def leave(name: str, body: Reauth, s: Session = Depends(sessions.current)):
        accounts.reauthenticate(s.id, body.password, body.totp or body.code)
        accounts.leave_app(s.id, name)
        swept()
        return accounts.view(accounts.get(s.id))

    @r.post("/api/account/visit", status_code=204)
    def visit(s: Session = Depends(sessions.ready)):
        """The app's pages call this on every page they show: a count per day, never which page."""
        if app in s.apps:
            accounts.record_visit(s.id, app)
        return Response(status_code=204)

    @r.delete("/api/account")
    def delete_account(body: Reauth, response: Response, s: Session = Depends(sessions.current)):
        accounts.reauthenticate(s.id, body.password, body.totp or body.code)
        accounts.delete_account(s.id)
        session.clear(response, accounts.config, device=True)
        swept()
        return {"ok": True}

    # --- admin -----------------------------------------------------------------------------------------------------

    @r.get("/api/admin/accounts")
    def admin_list(a: Session = Depends(admin)):
        return accounts.list_accounts()

    @r.get("/api/admin/usage")
    def admin_usage(a: Session = Depends(admin)):
        return accounts.usage()

    @r.patch("/api/admin/accounts/{account_id}")
    def admin_flags(account_id: int, body: AdminFlags, a: Session = Depends(admin)):
        return accounts.view(accounts.set_flags(a.account, account_id, body.is_admin, body.suspended))

    @r.patch("/api/admin/accounts/{account_id}/apps/{name}")
    def admin_app(account_id: int, name: str, body: AdminApp, a: Session = Depends(admin)):
        accounts.set_app(a.account, account_id, name, body.enabled, body.is_admin)
        if body.enabled is False:
            swept()
        return accounts.view(accounts.get(account_id))

    @r.post("/api/admin/accounts/{account_id}/reset-password")
    def admin_reset_password(account_id: int, a: Session = Depends(admin)):
        return {"password": accounts.reset_password(a.account, account_id)}

    @r.delete("/api/admin/accounts/{account_id}/totp")
    def admin_reset_totp(account_id: int, a: Session = Depends(admin)):
        return accounts.view(accounts.reset_totp(a.account, account_id))

    @r.delete("/api/admin/accounts/{account_id}")
    def admin_delete(account_id: int, confirm: str, a: Session = Depends(admin)):
        accounts.admin_delete(a.account, account_id, confirm)
        swept()
        return {"ok": True}

    @r.get("/api/admin/registration")
    def admin_registration(a: Session = Depends(admin)):
        return {
            "registration": accounts.registration_mode(),
            "invites": accounts.list_invites(),
            "audit": accounts.list_audit(),
            "settings": {
                "require_totp": accounts.config.require_totp,
                "email": bool(accounts.mailer),
                "session_days": accounts.config.session_days,
            },
        }

    @r.patch("/api/admin/registration")
    def admin_registration_update(body: Mode, a: Session = Depends(admin)):
        accounts.set_registration_mode(a.account, body.registration)
        return admin_registration(a)

    @r.post("/api/admin/invites")
    def admin_invite(body: InviteIn, a: Session = Depends(admin)):
        return accounts.create_invite(a.account, body.days, body.apps)

    @r.delete("/api/admin/invites/{code}")
    def admin_invite_delete(code: str, a: Session = Depends(admin)):
        accounts.delete_invite(a.account, code)
        return {"ok": True}

    # The admin routes once more under /api/trackerai/admin: an app may answer some /api/admin paths itself (wealth-
    # tracker's invites), and the admin page on the front door needs the shared ones.
    for route in [x for x in r.routes if getattr(x, "path", "").startswith("/api/admin/")]:
        r.add_api_route("/api/trackerai" + route.path[len("/api") :], route.endpoint, methods=list(route.methods), include_in_schema=False)

    for old, new in (aliases or {}).items():
        for route in [x for x in r.routes if getattr(x, "path", None) == new]:
            r.add_api_route(old, route.endpoint, methods=list(route.methods), include_in_schema=False)
    if app is not None:
        from trackerai_accounts.oauth import make_router as oauth_router

        r.include_router(oauth_router(accounts, sessions, app, client_ip))
    return r, sessions
