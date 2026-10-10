"""The session: a signed JWT in an httpOnly cookie, on the shared parent domain when SESSION_COOKIE_DOMAIN is set,
so logging in on one app logs you in on all of them (and logging out, out of all).

Claims: `sub` "a:<account id>", `sv` the account's session version (raising it ends the session), `iat` when the
cookie was issued (renewed once a day while in use) and `auth` when the password was typed (renewal stops
SESSION_MAX_DAYS after it).
"""

from __future__ import annotations

import time

import jwt
from fastapi import Response

from trackerai_accounts.config import Config

COOKIE = "trackerai_session"
DEVICE_COOKIE = "trackerai_device"  # this browser gave the two-step code and asked to be remembered
ALGORITHM = "HS256"


def issue(response: Response, config: Config, account_id: int, session_version: int, auth_time: int | None = None,
          remember: bool = True) -> None:
    """`remember` ("stay logged in"): the cookie lasts SESSION_DAYS after its last use. Without: a browser session,
    gone when the browser closes, and never longer than SHORT_SESSION_HOURS on the server."""
    now = int(time.time())
    lasts = config.session_days * 86400 if remember else config.short_session_hours * 3600
    claims = {"sub": f"a:{account_id}", "sv": session_version, "iat": now, "auth": int(auth_time or now),
              "exp": now + lasts, "rm": 1 if remember else 0}
    token = jwt.encode(claims, config.session_secret, algorithm=ALGORITHM)
    response.set_cookie(COOKIE, token, max_age=lasts if remember else None, httponly=True, secure=config.cookie_secure,
                        samesite="lax", path="/", domain=config.cookie_domain)


def remembered(c: dict) -> bool:
    return bool(c.get("rm", 1))


def issue_device(response: Response, config: Config, account_id: int, session_version: int) -> None:
    """This browser may skip the two-step code for SESSION_DAYS: the password is still asked. A password change, two-step
    login on or off and an admin reset (the session version) end it."""
    now = int(time.time())
    lasts = config.session_days * 86400
    token = jwt.encode({"sub": f"a:{account_id}", "sv": session_version, "typ": "device", "iat": now, "exp": now + lasts},
                       config.session_secret, algorithm=ALGORITHM)
    response.set_cookie(DEVICE_COOKIE, token, max_age=lasts, httponly=True, secure=config.cookie_secure, samesite="lax",
                        path="/", domain=config.cookie_domain)


def device_trusted(token: str | None, config: Config, account: dict) -> bool:
    c = claims(token, config)
    return bool(c and c.get("typ") == "device" and c.get("sub") == f"a:{account['id']}"
                and int(c.get("sv") or 0) == (account.get("session_version") or 0))


def clear(response: Response, config: Config, device: bool = False) -> None:
    """Logging out keeps the device cookie (the code is not asked again here); deleting the account does not."""
    if device:
        response.delete_cookie(DEVICE_COOKIE, path="/", domain=config.cookie_domain, secure=config.cookie_secure, httponly=True,
                               samesite="lax")
    response.delete_cookie(COOKIE, path="/", domain=config.cookie_domain, secure=config.cookie_secure, httponly=True, samesite="lax")


def claims(token: str | None, config: Config) -> dict | None:
    if not token or not config.session_secret:
        return None
    try:
        return jwt.decode(token, config.session_secret, algorithms=[ALGORITHM], options={"require": ["exp", "iat", "sub"]})
    except jwt.PyJWTError:
        return None


def due_for_renewal(c: dict, config: Config) -> bool:
    now = int(time.time())
    auth_time = int(c.get("auth") or c.get("iat") or now)
    return now - int(c.get("iat") or now) >= config.renew_after_s and now - auth_time < config.session_max_days * 86400
