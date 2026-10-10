"""
Password hashing and JWT issuing/verification.

Password hashes use `bcrypt` directly (cost factor 12) rather than pulling
`streamlit_authenticator` into the backend — it produces and reads the exact
same `$2b$...` hash format already stored in auth_config.yaml, so accounts
created via the old Streamlit UI and the new backend are fully interchangeable.
"""

import time

import bcrypt
import jwt

_ALGORITHM = "HS256"
_BCRYPT_ROUNDS = 12


def _bcrypt_input(password: str) -> bytes:
    # bcrypt only ever looked at the first 72 bytes; bcrypt 5 refuses longer
    # input with ValueError instead of ignoring the rest, which turned a long
    # password at sign-up into a 500 and made a long existing one unusable.
    # Cutting it here keeps exactly the old behaviour for both.
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_input(password), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_bcrypt_input(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(username: str, secret: str, expiry_days: int, auth_time: int | None = None) -> str:
    """`auth_time`: when the password was typed for this session (kept across
    sliding renewals, so a session cannot be renewed forever)."""
    now = int(time.time())
    payload = {"sub": username, "iat": now, "exp": now + expiry_days * 86400, "auth": int(auth_time or now)}
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def decode_access_claims(token: str, secret: str) -> dict | None:
    """Returns the whole payload if the token is valid and unexpired, else None.

    Callers that need more than the username use this: deps.py compares the
    token's `iat` against the account's `pw_changed_at` so a password change
    can retire tokens issued before it.
    """
    try:
        if not secret:
            return None  # never verify against an empty key
        return jwt.decode(token, secret, algorithms=[_ALGORITHM], options={"require": ["exp", "iat", "sub"]})
    except jwt.PyJWTError:
        return None


def decode_access_token(token: str, secret: str) -> str | None:
    """Returns the username if the token is valid and unexpired, else None."""
    payload = decode_access_claims(token, secret)
    return payload.get("sub") if payload else None
