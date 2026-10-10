"""Symmetric encryption for secrets kept in the database (Garmin and Wahoo sessions, two-step login secrets).

Key: APP_ENCRYPTION_KEY (a Fernet key; TOKEN_ENCRYPTION_KEY is the older name and still read). Set the same key on
every service (web, sync) so they can read each other's values. The web service refuses to start without one in
production (api/main.py) unless ALLOW_INSECURE_DEFAULTS=true. Older deploys ran without it, on a key derived from
TRAINING_JWT_SECRET; to keep their stored connections readable, set that derived key explicitly:

    TRAINING_JWT_SECRET=... python -m tools.secretbox --print-derived-key

Encrypted values carry the key's id (`k1:<id>:<token>`), so a process with a different key says so instead of failing
with an unreadable error. Values from before the tag (plain Fernet tokens) still decrypt.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "k1:"
KEY_VARS = ("APP_ENCRYPTION_KEY", "TOKEN_ENCRYPTION_KEY")  # the first one set wins


class WrongKey(Exception):
    """The value was encrypted with another key (another service or a rotated key): reconnect."""


def key_id(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def configured_key() -> str:
    """The key set in the environment, or "" (then only the derived fallback is left)."""
    return next((os.environ[v].strip() for v in KEY_VARS if os.environ.get(v, "").strip()), "")


def derived_key(jwt_secret: str | None = None) -> str:
    secret = os.environ.get("TRAINING_JWT_SECRET", "") if jwt_secret is None else jwt_secret
    if not secret:
        return ""
    return base64.urlsafe_b64encode(hashlib.sha256(b"training-secretbox:" + secret.encode()).digest()).decode()


def default_key() -> str:
    return configured_key() or derived_key()


def valid_key(key: str) -> bool:
    try:
        Fernet(key.encode())
        return True
    except (ValueError, TypeError):
        return False


def encrypt(value: str, key: str) -> str:
    return f"{PREFIX}{key_id(key)}:" + Fernet(key.encode()).encrypt(value.encode()).decode()


def decrypt(token: str, key: str) -> str:
    if token.startswith(PREFIX):
        kid, _, body = token[len(PREFIX):].partition(":")
        if kid != key_id(key):
            raise WrongKey("versleuteld met een andere sleutel")
        token = body
    try:
        return Fernet(key.encode()).decrypt(token.encode()).decode()
    except InvalidToken as err:
        raise WrongKey("versleuteld met een andere sleutel") from err


def main(argv: list[str]) -> int:
    if argv[:1] == ["--print-derived-key"]:
        key = derived_key()
        if not key:
            print("TRAINING_JWT_SECRET is not set", file=sys.stderr)
            return 1
        print(key)
        return 0
    if argv[:1] == ["--new-key"]:
        print(Fernet.generate_key().decode())
        return 0
    print("usage: python -m tools.secretbox --print-derived-key | --new-key", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
