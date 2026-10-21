"""Two-step login with an authenticator app: TOTP as in RFC 6238 (HMAC-SHA1, 6 digits, 30-second steps), the
variant every authenticator app supports. Standard library only.

    secret = new_secret()                                    # store it encrypted
    uri = otpauth_uri(secret, "anna", "health-tracker")       # as a QR code for the app
    step = verify(secret, "123456", last_used_step)           # None when wrong; store `step` to refuse a replay

One step either side of now is accepted (clock drift). A code is only good once: `verify` refuses any step at or
before `last_used_step`. Backup codes are for a lost phone: shown once, stored as hashes, each usable once.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

DIGITS = 6
PERIOD = 30
WINDOW = 1  # steps accepted before and after the current one


def new_secret() -> str:
    """160 random bits (RFC 4226's recommendation), base32 without padding."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def hotp(secret: str, counter: int, digits: int = DIGITS) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def step_at(t: float | None = None) -> int:
    return int((time.time() if t is None else t) // PERIOD)


def code_at(secret: str, t: float | None = None) -> str:
    return hotp(secret, step_at(t))


def otpauth_uri(secret: str, account: str, issuer: str) -> str:
    label = quote(f"{issuer}:{account}", safe="")
    return f"otpauth://totp/{label}?" + urlencode(
        {"secret": secret, "issuer": issuer, "algorithm": "SHA1", "digits": DIGITS, "period": PERIOD}
    )


def verify(secret: str, code: str, last_used_step: int | None = None, t: float | None = None) -> int | None:
    """The step the code belongs to when it is right and not used before, else None."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    now = step_at(t)
    found = None
    for step in range(now - WINDOW, now + WINDOW + 1):
        if hmac.compare_digest(hotp(secret, step), code) and found is None:
            found = step  # no early exit: every candidate costs the same
    if found is None or (last_used_step is not None and found <= last_used_step):
        return None
    return found


def _normal(code: str) -> str:
    return "".join(ch for ch in (code or "").lower() if ch.isalnum())


def new_backup_codes(n: int = 10) -> tuple[list[str], list[str]]:
    """(codes to show once, like "4f7a-91c2-0be3", their hashes to store)."""
    codes = []
    for _ in range(n):
        raw = secrets.token_hex(6)
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return codes, [hash_backup_code(c) for c in codes]


def hash_backup_code(code: str) -> str:
    """SHA-256 of the normalised code: 48 random bits per code, so no slow hash is needed against guessing."""
    return hashlib.sha256(_normal(code).encode()).hexdigest()


def use_backup_code(code: str, hashes: list[str]) -> list[str] | None:
    """The remaining hashes when `code` is one of them (it is used up), else None."""
    digest = hash_backup_code(code)
    match = None
    for h in hashes:
        if hmac.compare_digest(h, digest):
            match = h
    if match is None:
        return None
    return [h for h in hashes if h != match]
