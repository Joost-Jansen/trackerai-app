#!/usr/bin/env python3
"""
manage_users.py — create and manage login accounts (self-hosted, no Big Tech).

Passwords are stored only as bcrypt hashes in auth_config.yaml; the plaintext
is never written to disk. Run this on the server (in the venv):

    python scripts/manage_users.py add <username>       # create an account
    python scripts/manage_users.py passwd <username>    # change a password
    python scripts/manage_users.py remove <username>    # delete an account
    python scripts/manage_users.py list                 # list accounts
    python scripts/manage_users.py set-code <code>      # enable self-service signup
    python scripts/manage_users.py set-code             # disable self-service signup
    python scripts/manage_users.py admin <username>     # grant admin (invite-link panel)
    python scripts/manage_users.py unadmin <username>   # revoke admin

The password is read from the terminal (hidden). For scripting you may also
pipe it in:  echo 'secret' | python scripts/manage_users.py add bob
"""

import os
import re
import sys
import getpass
import secrets

import yaml
import bcrypt

# bcrypt directly, not streamlit_authenticator's Hasher. This script was the last
# thing importing it, and through it the whole of Streamlit, for one call. A
# bcrypt hash carries its own cost factor, so hashes written by either one verify
# fine against the other — this is a change of generator, not of format.
# Same 12 rounds as backend/app/core/security.py.
_BCRYPT_ROUNDS = 12


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("utf-8")

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the repo root, where auth_config.yaml lives
# The same variable as backend/app/core/config.py, so on a host with the file on
# a volume this script manages the same file as the app.
_CONFIG_PATH = os.environ.get("AUTH_CONFIG_PATH") or os.path.join(_HERE, "auth_config.yaml")

# Must match database._safe_user so a username is always a valid folder name.
_USERNAME_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")


def _canonical(users: dict, username: str) -> str | None:
    """The account as spelled in the config, ignoring capitalisation.

    Mirrors auth_store.canonical_username — this script deliberately imports
    nothing from the app, so the rule lives twice. Both exist because a name
    that differs only in case is a second account with its own (empty) data
    folder, not the account its owner meant.
    """
    if username in users:
        return username
    lowered = (username or "").casefold()
    return next((name for name in users if name.casefold() == lowered), None)


def _load() -> dict:
    if os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {
        "cookie": {
            "name": "stock_tracker_auth",
            "key": secrets.token_hex(16),   # random secret that signs the login cookie
            "expiry_days": 14,
        },
        "credentials": {"usernames": {}},
    }


def _save(cfg: dict) -> None:
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    os.chmod(_CONFIG_PATH, 0o600)   # only the owner may read the hashes/cookie key


def _read_password() -> str | None:
    if sys.stdin.isatty():
        pw1 = getpass.getpass("Password: ")
        pw2 = getpass.getpass("Repeat password: ")
        if pw1 != pw2:
            print("Passwords do not match.")
            return None
        return pw1 or None
    return sys.stdin.readline().strip() or None


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    cmd = args[0]
    cfg = _load()
    users = cfg["credentials"]["usernames"]

    if cmd == "list":
        if not users:
            print("(no accounts yet)")
        for u, info in users.items():
            print(f"  {u}  ({info.get('name', '')})")
        return

    if cmd in ("add", "passwd"):
        if len(args) < 2:
            print(f"Usage: python scripts/manage_users.py {cmd} <username>")
            return
        username = args[1]
        if not _USERNAME_RE.fullmatch(username):
            print("Username must be letters, digits, '_' or '-' (max 40 chars).")
            return
        stored = _canonical(users, username)
        if cmd == "add" and stored:
            print(f"'{stored}' already exists — use 'passwd' to change the password.")
            return
        if cmd == "passwd":
            if not stored:
                print(f"'{username}' does not exist.")
                return
            username = stored   # change the password of the account that exists,
                                # not of a new one differing only in capitals

        password = _read_password()
        if not password:
            print("No password given; nothing changed.")
            return

        existing = users.get(username, {})
        users[username] = {
            "name": existing.get("name") or username,
            "email": existing.get("email", f"{username}@local"),
            "password": _hash(password),
        }
        _save(cfg)
        print(f"Saved account '{username}'.")
        return

    if cmd == "set-code":
        # The old shared invite code that lets friends self-register. No arg disables it.
        # The admin panel hands out a link per person instead (one use, expires).
        code = args[1] if len(args) > 1 else None
        if code:
            cfg["registration_code"] = code
            _save(cfg)
            print("Self-service signup enabled. Share this invite code with people you trust.")
        else:
            cfg.pop("registration_code", None)
            _save(cfg)
            print("Self-service signup disabled.")
        return

    if cmd in ("admin", "unadmin"):
        if len(args) < 2:
            print(f"Usage: python scripts/manage_users.py {cmd} <username>")
            return
        username = args[1]
        admins = cfg.setdefault("admins", [])
        if cmd == "admin":
            if username not in users:
                print(f"'{username}' has no account yet; create it first with 'add'.")
                return
            if username not in admins:
                admins.append(username)
            print(f"'{username}' is now an admin.")
        else:
            if username in admins:
                admins.remove(username)
            print(f"'{username}' is no longer an admin.")
        _save(cfg)
        return

    if cmd == "remove":
        if len(args) < 2:
            print("Usage: python scripts/manage_users.py remove <username>")
            return
        username = args[1]
        stored = _canonical(users, username)
        if stored:
            del users[stored]
            _save(cfg)
            print(f"Removed account '{stored}'.")
            print(f"Its data directory (data/users/{stored}/) is left in place — "
                  f"delete or archive it by hand once you are sure.")
        else:
            print(f"'{username}' does not exist.")
        return

    print(__doc__)


if __name__ == "__main__":
    main()
