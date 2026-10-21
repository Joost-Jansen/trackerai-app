"""
The shared trackerai account (packages/accounts) for wealth-tracker.

Who someone is (login, password, two-step login, admin of the installation,
suspended, which trackers they use) lives in the accounts database that every
tracker shares, with one session for all of them. What is wealth-tracker's own
stays here, keyed by the data folder's name (the account's `local_key`):
data/users/<folder>/, and in auth_config.yaml the beta flags, wealth-tracker's
admins and agent tokens.

    accounts             the Accounts, from ACCOUNTS_* (tests swap in their own with `use`)
    local_folder(s)      wealth-tracker's folder for a session's account, made on its first visit
    bring_in(name, pw)   a login from before the accounts becomes an account on its first use
    purge()              delete wealth-tracker's data of accounts that left it or were deleted

On a development machine without ACCOUNTS_DATABASE_URL (ALLOW_INSECURE_DEFAULTS),
the accounts live in SQLite in the data folder, with keys made there once.
"""

import os
import re
import secrets
import threading

from app.core import audit, auth_store, config, security
from domain import database
from trackerai_accounts import Accounts, Config, connect, crypto
from trackerai_accounts.routes import Session

APP = "wealth"

_current: Accounts | None = None
_lock = threading.Lock()


def _dev_config() -> Config:
    """SQLite and keys in the data folder: a laptop or a test run without the shared accounts."""
    root = database.data_root()
    os.makedirs(root, exist_ok=True)

    def kept(name: str, make) -> str:
        path = os.path.join(root, name)
        if not os.path.exists(path):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(make())
        with open(path) as f:
            return f.read().strip()

    env = Config.from_env()
    return Config(
        database_url=f"sqlite:///{os.path.join(root, 'accounts.db')}",
        session_secret=kept(".accounts_session_secret", lambda: secrets.token_hex(32)),
        encryption_key=kept(".accounts_key", crypto.new_key),
        cookie_domain=env.cookie_domain,
        cookie_secure=config.COOKIE_SECURE,
        session_days=config.SESSION_DAYS,
        require_totp=env.require_totp,
        front_door=env.front_door,
    )


def get() -> Accounts:
    global _current
    if _current is None:
        with _lock:
            if _current is None:
                cfg = Config.from_env()
                if cfg.problems() and config.ALLOW_INSECURE_DEFAULTS:
                    cfg = _dev_config()
                _current = Accounts(connect(cfg.database_url), cfg)
    return _current


def use(accounts: Accounts | None) -> None:
    """Tests: these accounts from now on (None: from the environment again)."""
    global _current
    _current = accounts


class _Proxy:
    """`accounts` reads like an Accounts, and follows `use`."""

    def __getattr__(self, name):
        return getattr(get(), name)


accounts = _Proxy()


def linked_folders() -> dict[str, dict]:
    """wealth-tracker's data folders of the accounts using it: {folder: {"account_id", "username"}}. One query, for
    the admin pages that map folders to accounts in bulk; a deleted account or one leaving wealth-tracker is left out."""
    out = {}
    for a in accounts.list_accounts():
        folder = (a.get("local_keys") or {}).get(APP)
        if folder:
            out[folder] = {"account_id": a["id"], "username": a["username"]}
    return out


# --- wealth-tracker's own user ------------------------------------------------

_making = threading.Lock()


def _folder_name(username: str, taken: set[str]) -> str:
    """A data folder for a new account: its name with what a folder may not hold made `_`, unique (any case)."""
    base = re.sub(r"[^A-Za-z0-9_-]", "_", username)[:36] or "user"
    name, n = base, 1
    while name.casefold() in taken or os.path.exists(database.user_data_dir(name)):
        n += 1
        name = f"{base}-{n}"
    return name


def local_folder(s: Session) -> str:
    """wealth-tracker's data folder for this account, made (with its entry in auth_config.yaml) on the first visit."""
    key = (s.apps.get(APP) or {}).get("local_key")
    if key:
        return key
    with _making:
        key = accounts.local_key(s.id, APP)
        if key:
            return key
        users = auth_store.users_or_empty()
        folder = _folder_name(s.username, {u.casefold() for u in users})
        used = [i["code"] for i in accounts.list_invites() if i["used_by"] == s.id]
        auth_store.ensure_user(folder, s.account.get("display_name") or s.username, auth_store.invite_betas(used))
        accounts.set_local_key(s.id, APP, folder)
        return folder


def bring_in(username: str, password: str) -> None:
    """A login from before the accounts (an entry with a password in auth_config.yaml) becomes an account on its
    first use, when its name is free: then nobody waits for the import. A name the accounts already have is left
    alone (the same name can be someone else in another tracker; the import settles that, packages/accounts
    migrate.py), and so is a folder that already belongs to an account."""
    if not username or accounts.by_username(username):
        return
    try:
        cfg = auth_store.load_config()
    except auth_store.AuthError:
        return
    folder = auth_store.canonical_username(username, cfg)
    user = (cfg.get("credentials", {}).get("usernames", {}) or {}).get(folder) if folder else None
    if not user or not user.get("password") or accounts.account_id_for_local_key(APP, folder) is not None:
        return
    if not security.verify_password(password or "", user["password"]):
        return
    state = user.get("totp") or {}
    secret = auth_store.decrypt_totp_secret(state.get("secret")) if state.get("enabled") else None
    app_admin = folder in (cfg.get("admins") or [])
    # someone must run the installation: wealth-tracker's admin, while there is no account admin yet
    first = app_admin and not any(a["is_admin"] for a in accounts.list_accounts())
    try:
        accounts.create_linked(
            username,
            user["password"],
            APP,
            folder,
            is_admin=first,
            app_admin=app_admin,
            display_name=user.get("name"),
            locale=user.get("locale"),
            suspended=bool(user.get("suspended")),
            totp_secret=secret,
            totp_backup=state.get("backup_codes") if secret else None,
        )
    except Exception:  # noqa: BLE001 - someone took the name meanwhile: the login is checked as usual
        return
    auth_store.forget_login(folder)  # the password and two-step secret live in the accounts now
    audit.log(folder, "account_created", target=folder)


def purge() -> int:
    """Delete wealth-tracker's data of every account that left it or was deleted; returns how many."""
    from app.services import account_data

    done = 0
    for p in accounts.pending_purges(APP):
        folder = p["local_key"]
        if folder:
            auth_store.remove_user(folder)
            account_data.remove_data(folder)
            audit.log("system", "delete_account", target=folder)
        accounts.purged(p["account_id"], APP)
        done += 1
    return done


# --- the account routes (packages/accounts), the same paths in every tracker ---


def _client_ip(request) -> str:
    from app.core import throttle

    return throttle.client_ip(request)


def _router():
    from app.core import throttle
    from trackerai_accounts import make_router
    from trackerai_accounts.routes import Guards

    # wealth-tracker's own limiters (core/throttle.py), so its limits and their reset in the tests stay one set
    guards = Guards(login_ip=throttle.LOGIN_PER_IP, login_name=throttle.LOGIN_PER_USER, register_ip=throttle.REGISTER_PER_IP)
    return make_router(accounts, APP, client_ip=_client_ip, guards=guards, after_leave=purge, before_login=bring_in)


router, sessions = _router()
