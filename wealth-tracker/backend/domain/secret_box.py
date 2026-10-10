"""
secret_box.py — encrypting what must never be readable in a database.

For now one thing: the private key with which a user signs their own bank
connection (bank_link.py). With that key someone can read your accounts, so it
is stored encrypted in your database and never goes back to the browser.

The key used for encryption:

  * APP_ENCRYPTION_KEY in the environment, if the admin sets it (a Fernet key:
    `python -c "from cryptography.fernet import Fernet;
    print(Fernet.generate_key().decode())"`). The strongest: then it is not on
    the same disk as the data.
  * Otherwise the server makes one itself the first time, on the data volume,
    readable only by the owner. That way it works without anyone having to
    arrange anything; a copy of just a database is then still unreadable.

In production APP_ENCRYPTION_KEY is required (app/core/startup.py refuses to
start without it, unless ALLOW_INSECURE_DEFAULTS=true for development): the
key file next to the data is no protection for a stolen backup of the volume.

**Taking over the old key file.** Data encrypted before APP_ENCRYPTION_KEY was
set is readable as long as `.encryption_key` is still in the data folder: it
is tried after the key from the environment, and every value read with it is
encrypted again with the new key (`needs_rotation`/`rotate`). Simplest is to
set APP_ENCRYPTION_KEY to the content of that file; then nothing changes at
all. Once everything is rotated the file can go (keep a copy in the password
manager, with the new key).

Whoever loses or changes the key without the old file can no longer read data
encrypted earlier: then the app asks to upload the private key again.
"""

import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from domain import database
from domain.i18n import tr

_FILE = ".encryption_key"
# The key file's name before the English rename; moved to _FILE on first use,
# so data encrypted with it stays readable.
_LEGACY_FILE = ".versleutelsleutel"


class Unreadable(Exception):
    """Encrypted with a different key than the current one."""


def environment_key() -> bytes | None:
    value = os.environ.get("APP_ENCRYPTION_KEY", "").strip()
    return value.encode() if value else None


def _file_key(create: bool) -> bytes | None:
    path = os.path.join(database.data_root(), _FILE)
    legacy = os.path.join(database.data_root(), _LEGACY_FILE)
    if not os.path.exists(path) and os.path.exists(legacy):
        try:
            os.rename(legacy, path)
        except FileNotFoundError:
            pass  # another process moved it first
    if not os.path.exists(path):
        if not create:
            return None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            # O_EXCL: if two processes start at once, one creates the key and the other
            # reads it, instead of overwriting each other.
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())
    with open(path, "rb") as f:
        return f.read().strip()


def _keys() -> list[bytes]:
    """The key to encrypt with first, then older keys that may still decrypt."""
    primary = environment_key()
    if primary:
        old = _file_key(create=False)
        return [primary] + ([old] if old and old != primary else [])
    return [_file_key(create=True)]


def _key() -> bytes:
    return _keys()[0]


def validate_environment_key() -> None:
    """ValueError if APP_ENCRYPTION_KEY is set but not a Fernet key."""
    key = environment_key()
    if key:
        Fernet(key)


def encrypt(data: bytes) -> str:
    return Fernet(_key()).encrypt(data).decode()


def decrypt(token: str) -> bytes:
    try:
        return MultiFernet([Fernet(k) for k in _keys()]).decrypt(token.encode())
    except InvalidToken as e:
        raise Unreadable(tr("This data was encrypted with another key.")) from e


def needs_rotation(token: str) -> bool:
    """True if `token` is readable, but only with an older key."""
    keys = _keys()
    if len(keys) < 2:
        return False
    try:
        Fernet(keys[0]).decrypt(token.encode())
        return False
    except InvalidToken:
        return True


def rotate(token: str) -> str:
    """The same data, encrypted with the current key."""
    return MultiFernet([Fernet(k) for k in _keys()]).rotate(token.encode()).decode()


def looks_encrypted(value: str | None) -> bool:
    """A Fernet token (version byte 0x80, base64: starts with "gAAAAA")."""
    return bool(value) and value.startswith("gAAAAA")
