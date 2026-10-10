"""Password rules for a new password (registration, change, admin reset): long enough, not on the list of passwords
attackers try first, not the username. Returns an error code (the apps translate it) or None. Never checked at login,
so an existing account with an older, weaker password is not locked out.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

MIN_LENGTH = 10
MAX_LENGTH = 200  # bcrypt only reads 72 bytes; a cap also keeps hashing cheap
LIST = Path(__file__).with_name("common_passwords.txt")


@lru_cache(maxsize=1)
def common_passwords() -> frozenset[str]:
    try:
        lines = LIST.read_text(encoding="utf-8").splitlines()
    except OSError:
        return frozenset()
    return frozenset(line.strip().lower() for line in lines if line.strip() and not line.startswith("#"))


def check_password(password: str, username: str | None = None) -> str | None:
    """`password_too_short`, `password_too_long`, `password_too_common`, `password_is_username` or None."""
    password = password or ""
    if len(password) < MIN_LENGTH:
        return "password_too_short"
    if len(password) > MAX_LENGTH:
        return "password_too_long"
    folded = password.strip().lower()
    name = (username or "").strip().lower()
    if name and folded in {name, name * 2} | {name + d for d in ("1", "12", "123", "1234", "!")}:
        return "password_is_username"
    if folded in common_passwords() or len(set(folded)) <= 2:
        return "password_too_common"
    return None
