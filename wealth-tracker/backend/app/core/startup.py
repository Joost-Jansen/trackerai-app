"""
Refuse to run in production with insecure defaults (S9).

APP_ENCRYPTION_KEY encrypts what gives access to someone's bank (the Enable
Banking private key and session) and their two-step login secret. Without it
the server keeps a key file next to the data, so a copy of the data volume
(a backup, a stolen disk) carries its own key. In production it is required;
ALLOW_INSECURE_DEFAULTS=true is the single opt-out, for development and tests.
"""

import logging
import os

from app.core import config
from domain import secret_box

_log = logging.getLogger("uvicorn.error")

HOW_TO = (
    "Set APP_ENCRYPTION_KEY to a Fernet key. On an existing server take over the key the app made "
    "itself: APP_ENCRYPTION_KEY=$(cat <DATA_DIR>/.encryption_key). A new one: python -c "
    '"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())". '
    "For development only: ALLOW_INSECURE_DEFAULTS=true."
)


def check() -> None:
    """Raises RuntimeError when the server must not start."""
    insecure = config.ALLOW_INSECURE_DEFAULTS or os.environ.get("ALLOW_INSECURE_DEFAULTS", "").lower() == "true"
    try:
        secret_box.validate_environment_key()
    except Exception as e:
        raise RuntimeError(f"APP_ENCRYPTION_KEY is not a valid Fernet key. {HOW_TO}") from e
    if not secret_box.environment_key():
        if not insecure:
            raise RuntimeError(f"APP_ENCRYPTION_KEY is required in production. {HOW_TO}")
        _log.warning(
            "[startup] APP_ENCRYPTION_KEY is not set; using a key file in the data folder "
            "(ALLOW_INSECURE_DEFAULTS=true). Do not run like this in production."
        )
    from trackerai_accounts import Config

    problems = Config.from_env().problems()
    if problems:
        if not insecure:
            raise RuntimeError("The shared accounts are not set up: " + "; ".join(problems) + " (packages/accounts/README.md)")
        _log.warning("[startup] ACCOUNTS_* not set; accounts in SQLite in the data folder (ALLOW_INSECURE_DEFAULTS=true).")
    if insecure and config.COOKIE_SECURE:
        _log.warning("[startup] ALLOW_INSECURE_DEFAULTS=true while COOKIE_SECURE is on: is this production?")
