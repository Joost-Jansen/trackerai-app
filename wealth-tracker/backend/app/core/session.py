"""
The session cookie (S11): issued at login, renewed while in use.

A session lasts SESSION_DAYS (default 30). A request that arrives with a
cookie more than a day old gets a fresh one with a new expiry (sliding), so
someone who uses the app stays logged in, and a stolen cookie that is not
used dies within SESSION_DAYS. Renewal keeps the moment the password was typed
(`auth`), and stops SESSION_MAX_DAYS after it. A password change still
retires every cookie issued before it (deps.get_current_user).
"""

import time

from fastapi import Request, Response

from app.core import auth_store, config, security


def issue(response: Response, username: str, auth_time: int | None = None) -> None:
    cfg = auth_store.load_config()
    secret, days = auth_store.token_secret_and_expiry(cfg)
    token = security.create_access_token(username, secret, days, auth_time)
    response.set_cookie(
        key=config.ACCESS_COOKIE_NAME,
        value=token,
        max_age=days * 86400,
        httponly=True,
        secure=config.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def mark_for_renewal(request: Request, username: str, claims: dict) -> None:
    """Called for every valid cookie: note when it is due for a fresh one."""
    now = int(time.time())
    auth_time = int(claims.get("auth") or claims.get("iat") or now)
    if now - int(claims.get("iat", now)) < config.SESSION_RENEW_AFTER_SECONDS:
        return
    if now - auth_time > config.SESSION_MAX_DAYS * 86400:
        return
    request.state.renew_session = (username, auth_time)


def renew_if_due(request: Request, response: Response) -> None:
    """After the handler: hand out the fresh cookie, unless the response set or
    cleared the cookie itself (login, logout, password change)."""
    due = getattr(request.state, "renew_session", None)
    if not due or response.status_code >= 400:
        return
    for name, value in response.raw_headers:
        if name.lower() == b"set-cookie" and value.startswith(config.ACCESS_COOKIE_NAME.encode() + b"="):
            return
    try:
        issue(response, *due)
    except auth_store.AuthError:
        pass
