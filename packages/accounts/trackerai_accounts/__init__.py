"""One trackerai account for every app: who someone is, their password and two-step login, and which apps they use.
See README.md."""

from trackerai_accounts.config import APPS, Config
from trackerai_accounts.errors import AccountError, install
from trackerai_accounts.routes import Session, Sessions, make_router
from trackerai_accounts.service import Accounts
from trackerai_accounts.store import connect

__all__ = ["APPS", "AccountError", "Accounts", "Config", "Session", "Sessions", "connect", "install", "make_router", "open_accounts"]


def open_accounts(config: Config | None = None) -> Accounts:
    """The accounts for this process, from the environment unless a config is given."""
    config = config or Config.from_env()
    return Accounts(connect(config.database_url), config)
