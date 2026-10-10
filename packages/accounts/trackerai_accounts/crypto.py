"""Encryption for the two-step login secrets in the accounts database.

The key is ACCOUNTS_ENCRYPTION_KEY, a Fernet key that every app using the accounts database must share (each app's
own APP_ENCRYPTION_KEY stays its own, for its own secrets). A value carries the key's id (`k1:<id>:<token>`, the
format health-tracker uses), so a process with another key says so instead of failing unreadably.
"""

from __future__ import annotations

import hashlib

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "k1:"


class WrongKey(Exception):
    """Encrypted with another key."""


def key_id(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def valid_key(key: str) -> bool:
    try:
        Fernet(key.encode())
        return True
    except (ValueError, TypeError):
        return False


def new_key() -> str:
    return Fernet.generate_key().decode()


def encrypt(value: str, key: str) -> str:
    return f"{PREFIX}{key_id(key)}:" + Fernet(key.encode()).encrypt(value.encode()).decode()


def decrypt(value: str, key: str) -> str:
    token = value
    if value.startswith(PREFIX):
        kid, _, token = value[len(PREFIX):].partition(":")
        if kid != key_id(key):
            raise WrongKey(kid)
    try:
        return Fernet(key.encode()).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError) as e:
        raise WrongKey("?") from e
