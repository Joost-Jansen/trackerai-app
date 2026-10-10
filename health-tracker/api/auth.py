"""Login primitives: bcrypt password check and the session, a signed JWT in an httpOnly cookie.

The token carries the user (`sub`), when it was issued (`iat`, renewed while in use) and the user's session version
(`sv`): raising the version (a password change, two-step login switched on or off) ends every session issued before.
Rate limits live in packages/websec (trackerai_websec.throttle; per username and per IP, api/users.py).
"""

from __future__ import annotations

import hmac
import time

import bcrypt
import jwt

ALGORITHM = "HS256"
COOKIE = "training_session"
# Checked when the username does not exist, so a wrong name costs as much time as a wrong password (no user
# enumeration by timing). Made once at import, at the cost factor real hashes use.
DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    """Constant work: without a hash (unknown user) the dummy hash is checked and the answer is False."""
    try:
        ok = bcrypt.checkpw(password.encode()[:72], (hashed or DUMMY_HASH).encode())
    except (ValueError, TypeError):
        return False
    return ok and bool(hashed)


def create_token(subject: str, secret: str, days: int, session_version: int = 0) -> str:
    now = int(time.time())
    return jwt.encode({"sub": subject, "iat": now, "exp": now + days * 86400, "sv": session_version}, secret, algorithm=ALGORITHM)


def token_claims(token: str | None, secret: str) -> dict | None:
    if not token or not secret:
        return None
    try:
        return jwt.decode(token, secret, algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return None


def token_user(token: str | None, secret: str) -> str | None:
    claims = token_claims(token, secret)
    return claims.get("sub") if claims else None


def same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
