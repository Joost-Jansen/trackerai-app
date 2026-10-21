"""
Logging in is the shared trackerai account's (packages/accounts, mounted in
main.py): /api/auth/login, /logout, /registration-status, and the two-step and
password routes under /api/account. What is wealth-tracker's own is here:

    POST /api/auth/register          an account, made here: the site it came from decides the first betas
    POST /api/auth/change-password   the old path of a password change
    GET  /api/auth/me                who is logged in, also before wealth-tracker opens for them
    PUT  /api/auth/me/locale         the language, for every tracker
    POST /api/auth/join              start using wealth-tracker with an account from another tracker
"""

from fastapi import APIRouter, Body, Depends, Request, Response, status

from app.core import auth_store, throttle
from app.core.accounts import APP, accounts, local_folder, sessions
from app.core.errors import CodedError
from app.deps import CurrentUser, get_current_user
from app.schemas.auth import ChangePasswordRequest, LocaleRequest, MeResponse, RegisterRequest
from domain.i18n import tr
from trackerai_accounts import session as account_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _too_many(message: str) -> CodedError:
    return CodedError(status.HTTP_429_TOO_MANY_REQUESTS, "too_many_attempts", message)


@router.post("/register")
def register(body: RegisterRequest, request: Request, response: Response):
    """An account of its own, with wealth-tracker, or with the trackers chosen on the front door (`apps`). From the
    wealth-tracker site (`app` "money") it starts with Money; an invitation can bring betas the admin chose for it."""
    if not throttle.REGISTER_PER_IP.hit(throttle.client_ip(request)):
        raise _too_many(tr("Too many sign-ups from here. Try again later."))
    # A name with a login from before the accounts belongs to that person, until it moves (on their first login,
    # core/accounts.py bring_in): a sign-up must not take it from them.
    folder = auth_store.canonical_username((body.username or "").strip(), auth_store.load_config_or_empty())
    if folder and accounts.account_id_for_local_key(APP, folder) is None:
        raise CodedError(status.HTTP_409_CONFLICT, "username_taken", tr("That username is already taken."))
    if accounts.count() == 0 and auth_store.users_or_empty():
        # Nobody's login has moved to the accounts yet: the first sign-up would become the administrator of every
        # tracker. Signing up waits for the import (packages/accounts migrate.py) or the first existing login.
        raise CodedError(status.HTTP_403_FORBIDDEN, "registration_closed", tr("Self-service signup is currently closed."))
    account = accounts.register(
        body.username,
        body.password,
        APP,
        display_name=body.name,
        invite=body.invite_code or None,
        email=body.email,
        locale=body.locale if body.locale in ("nl", "en") else None,
        apps=body.apps or None,
        consent=body.consent,
    )
    s = sessions.resolve_account(account)
    if APP in s.apps:
        folder = local_folder(s)
        if body.app == "money":
            auth_store.grant_beta(folder, "money")
    account_session.issue(response, accounts.config, account["id"], account["session_version"] or 0)
    return {"ok": True}


@router.post("/join")
def join(request: Request, response: Response, money: bool = Body(False, embed=True), old_password: str | None = Body(None, embed=True)):
    """Start using wealth-tracker with an account from another tracker (an open installation, or the admin's).

    Had this person a wealth-tracker login of their own with the same name (from before the accounts, not moved
    yet), its password brings that data folder along (409 `old_login_password` asks for it): the same person with
    a login in both trackers, without waiting for the import."""
    s = sessions.current(request, response)
    cfg = auth_store.load_config_or_empty()
    old = auth_store.canonical_username(s.username, cfg)
    old_user = (cfg.get("credentials", {}).get("usernames", {}) or {}).get(old) if old else None
    if old_user and old_user.get("password") and accounts.account_id_for_local_key(APP, old) is None:
        if not old_password:
            raise CodedError(
                status.HTTP_409_CONFLICT,
                "old_login_password",
                tr("You had a login here with this name: enter its password to bring your data along."),
            )
        if not throttle.REAUTH_PER_USER.hit(old.casefold()):
            raise _too_many(tr("Too many failed attempts. Try again in a quarter of an hour."))
        from app.core import security

        if not security.verify_password(old_password, old_user["password"]):
            raise CodedError(status.HTTP_403_FORBIDDEN, "wrong_current_password", tr("Your password is not correct."))
        accounts.join_app(s.id, APP)
        accounts.set_local_key(s.id, APP, old)
        auth_store.forget_login(old)
        return {"ok": True}
    accounts.join_app(s.id, APP)
    folder = local_folder(sessions.resolve_account(accounts.get(s.id)))
    if money:
        auth_store.grant_beta(folder, "money")
    return {"ok": True}


@router.post("/change-password")
def change_password(body: ChangePasswordRequest, request: Request, response: Response):
    """Every other session ends, in every tracker; this browser gets a new one."""
    s = sessions.current(request, response)
    account = accounts.change_password(s.id, body.current_password, body.new_password)
    account_session.issue(
        response,
        accounts.config,
        account["id"],
        account["session_version"] or 0,
        s.claims.get("auth"),
        account_session.remembered(s.claims),
    )
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
def me(request: Request, response: Response):
    """Also before wealth-tracker opens: then it says what is missing first (two-step login, or joining
    wealth-tracker at all), and the site shows that instead of the pages."""
    if not request.cookies.get(account_session.COOKIE) and request.headers.get("authorization", "").lower().startswith("bearer "):
        user = get_current_user(request, response)
        return MeResponse(username=user.username, name=user.name, is_admin=user.is_admin, beta_features=user.beta_features)
    s = sessions.current(request, response)
    view = accounts.view(s.account, s.apps)
    out = MeResponse(
        username=s.username,
        name=s.account.get("display_name") or s.username,
        is_admin=False,
        beta_features=[],
        locale=s.account.get("locale"),
        totp_enabled=view["totp_enabled"],
        email_codes=view["email_codes"],
        two_step=view["two_step"],
        email=view["email"],
        email_verify_required=view["email_verify_required"],
        totp_required=view["totp_required"],
        totp_setup_required=view["totp_setup_required"],
        in_app=APP in s.apps,
        apps=view["apps"],
        account_admin=view["is_admin"],
    )
    if out.in_app and not out.totp_setup_required and not out.email_verify_required:
        user = get_current_user(request, response)
        out.name, out.is_admin, out.beta_features = user.name, user.is_admin, user.beta_features
    return out


@router.put("/me/locale")
def set_locale(body: LocaleRequest, user: CurrentUser = Depends(get_current_user)):
    """The language of the app for this account, so it follows the user to other devices and trackers."""
    accounts.update_profile(user.account_id, locale=body.locale)
    return {"ok": True, "locale": body.locale}
