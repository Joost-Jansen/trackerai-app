"""Errors as codes, in the shape both apps answer: `{"detail": ..., "code": ..., "params": {...}}`.

`detail` here is English; an app that answers in another language passes `translate` to `install` (health-tracker
renders the code itself, wealth-tracker runs `detail` through `tr()`).
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

MESSAGES: dict[str, str] = {
    "not_logged_in": "Not logged in.",
    "bad_credentials": "Incorrect username or password.",
    "account_suspended": "This account is suspended; contact the administrator.",
    "too_many_attempts": "Too many attempts. Try again in a quarter of an hour.",
    "registration_closed": "Registration is closed.",
    "invalid_invite": "This invitation code is not valid or already used.",
    "invalid_username": "Username: 3 to 40 characters, letters, digits, dot, dash or underscore.",
    "username_taken": "That username is taken.",
    "username_reserved": "That username is reserved.",
    "password_too_short": "Choose a password of at least {min} characters.",
    "password_too_long": "Choose a password of at most {max} characters.",
    "password_too_common": "This password is one of the most common ones; choose another.",
    "password_is_username": "Your password can't be your username.",
    "wrong_current_password": "Your current password is not correct.",
    "consent_required": "Give your consent to the processing of your health data to use health-tracker.",
    "name_too_long": "A name of at most {max} characters.",
    "invalid_locale": "The language is one of {options}.",
    "totp_required": "Enter the code from your authenticator app or your email.",
    "totp_invalid": "That code is not correct (or already used). Check the time on your phone and try the newest code.",
    "totp_already_enabled": "Two-step login is already on.",
    "totp_not_set_up": "Two-step login is not set up yet.",
    "totp_setup_required": "Set up two-step login first.",
    "totp_cannot_disable": "Two-step login is required for this account.",
    "accounts_key_missing": "The server has no key to store the two-step secret safely (ACCOUNTS_ENCRYPTION_KEY).",
    "unknown_app": "Unknown app; one of {options}.",
    "app_not_available": "Ask the administrator to give you access to this app.",
    "app_leaving": "Your data in this app is still being deleted; try again in a minute.",
    "not_in_app": "This account does not use this app.",
    "admins_only": "Admins only.",
    "site_login_only": "Only when logged in on the site.",
    "account_not_found": "Account not found.",
    "cannot_demote_self": "You can't remove your own admin rights or suspend yourself.",
    "cannot_delete_self": "You can't delete yourself here; use your own account settings.",
    "confirm_username": "Type the username to confirm.",
    "last_admin": "You are the only administrator; make someone else administrator first.",
    "invalid_registration_mode": "Registration is one of {options}.",
    "email_code_sent": "We sent a code to {to}. Enter it here.",
    "email_invalid": "That is not an email address.",
    "email_taken": "That address belongs to another account.",
    "email_unavailable": "Sending email doesn't work right now; use your authenticator app or a backup code.",
    "email_codes_off": "Codes by email are off for this account.",
    "too_many_codes": "Too many codes sent. Try again in a quarter of an hour.",
    "email_verify_required": "Confirm your email address first: enter the code from the welcome mail.",
    "email_already_verified": "Your email address is already confirmed.",
    "reset_code_invalid": "That code is not correct or no longer works. Ask for a new one.",
}


class AccountError(Exception):
    def __init__(self, status: int, code: str, headers: dict | None = None, **params):
        self.status = status
        self.code = code
        self.params = params
        self.headers = headers
        template = MESSAGES.get(code, code)
        try:
            self.detail = template.format(**params)
        except (KeyError, IndexError):
            self.detail = template
        super().__init__(self.detail)


def install(app: FastAPI, translate: Callable[[AccountError], str] | None = None) -> None:
    """Answer an AccountError as `{detail, code, params}`; `translate` gives `detail` in the reader's language."""

    async def handle(_: Request, exc: AccountError) -> JSONResponse:
        detail = translate(exc) if translate else exc.detail
        return JSONResponse({"detail": detail, "code": exc.code, "params": exc.params}, status_code=exc.status, headers=exc.headers)

    app.add_exception_handler(AccountError, handle)
