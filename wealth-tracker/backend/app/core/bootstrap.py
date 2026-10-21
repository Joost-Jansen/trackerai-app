"""
The first account on an empty server.

On the Pi you create it with `manage_users.py add` in a shell on the machine. A
host like Railway has no such shell out of the box, and the app refuses every
login while auth_config.yaml is missing — so without this you never get in.

If ADMIN_USERNAME and ADMIN_PASSWORD are in the environment and the file does
not exist yet, the first start creates it with that one account as admin and
self sign-up closed. After that this does nothing: an existing file is never
touched, so a forgotten variable can never reset a password later. Remove
ADMIN_PASSWORD after the first start; only the hash is kept.
"""

import os
import secrets
from datetime import UTC, datetime, timezone

import yaml

from app.core import auth_store, config, security


def first_account() -> str | None:
    """Creates the first account when that is needed and possible.

    Returns the username if an account was created, otherwise None.
    """
    path = config.AUTH_CONFIG_PATH
    if os.path.exists(path):
        return None
    name = os.environ.get("ADMIN_USERNAME", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not name or not password:
        return None
    if not auth_store.USERNAME_RE.fullmatch(name):
        raise ValueError("ADMIN_USERNAME may only contain letters, digits, '_' and '-' (max 40).")

    cfg = {
        "cookie": {
            "name": "stock_tracker_auth",
            # Signs the session tokens. Random per server and stored only here.
            "key": secrets.token_hex(32),
            "expiry_days": config.DEFAULT_TOKEN_EXPIRY_DAYS,
        },
        "credentials": {
            "usernames": {
                name: {
                    "name": name,
                    "email": f"{name}@local",
                    "password": security.hash_password(password),
                    "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
                },
            },
        },
        "admins": [name],
        # Closed until the admin chooses otherwise in the admin panel.
        "registration_mode": "closed",
    }

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        # O_EXCL: if two processes start at the same time, one wins and the other
        # overwrites nothing.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return None
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    return name
