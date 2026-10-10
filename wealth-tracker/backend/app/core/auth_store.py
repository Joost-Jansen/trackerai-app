"""
Reads/writes the same auth_config.yaml the Streamlit app (auth.py) uses —
accounts, invite code, admins and beta flags are shared between both apps
during the migration. This is auth.py's logic with every `st.*` call
removed; the YAML schema and bcrypt hashing are unchanged so either app can
create or modify accounts and the other sees it immediately.

Two things this backend adds to the schema that the old Streamlit app never
wrote — both additive, so an old config stays valid and Streamlit ignores the
extra keys it does not know about:
  * `registration_mode: open | invite | closed` — governs self-service signup.
    Absent on an old config, so it is *derived* from the legacy
    `registration_code` (present -> invite, absent -> closed): no migration.
  * per-user `created_at`, `last_login`, `suspended` — account bookkeeping the
    admin panel surfaces. Absent means "unknown"/not-suspended.
  * `invites: [{code, created_by, created_at, expires_at, used_by, used_at, beta}]` —
    an invite link per person: one use, with an expiry date, revocable. Invite
    mode accepts these; the old shared `registration_code` keeps working while
    it is set (the admin page shows it and can revoke it), so nothing breaks
    for a link that is already out there.

Every mutation goes through `_locked_update()`: an exclusive OS-level lock
serialises the read-modify-write so two writers (two logins, or a login racing
an admin edit, or the old Streamlit app) can't clobber each other, and
`save_config()` writes atomically (temp file + os.replace) so a concurrent
*reader* always sees a whole file, never a half-truncated one.
"""

import contextlib
import fcntl
import hmac
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

import yaml

from app.core import config, security
from trackerai_accounts import passwords
from domain.i18n import LOCALES, tr

# Must match database._safe_user so a username is always a valid folder name.
USERNAME_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")

# The single registry of beta flags: the admin panel renders it, /api/admin
# validates grants against it, and each gated router names its own key.
BETA_FEATURES = {
    "rebalancing": "Rebalancing tab",
    "returns": "Returns tab (TWR / IRR)",
    "dividends": "Dividend tab (calendar, years, per fund)",
    "calendar": "Calendar tab (publication and ex-dividend dates)",
    "money": "Money (accounts, spending, budget, net worth)",
}

REGISTRATION_MODES = ("open", "invite", "closed")

# A bcrypt digest of a value no one can log in with, hashed once at import so
# that `verify_credentials` can burn the same ~240ms on an unknown username as
# on a real one (see the comment there). Computed eagerly, not on first use:
# hashing lazily would make the first unknown-username login the slow one and
# reintroduce exactly the timing difference this exists to remove.
_ABSENT_USER_HASH = security.hash_password("absent-user-constant-time-placeholder")


class AuthError(Exception):
    """Raised for any user-facing auth failure (bad credentials, taken username, ...).

    `code` is set for failures the client may want to tell apart (see app/core/errors.py)."""

    code: str | None = None

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


def check_new_password(password: str, username: str) -> None:
    """S7: the password policy of the shared account (packages/accounts), whenever
    a password is set here (an admin reset of a login not moved to the accounts
    yet). Never at login, so an existing account with an older, weaker password
    is not locked out."""
    code = passwords.check_password(password, username)
    if code == "password_too_short":
        raise AuthError(tr("Choose a password of at least {0} characters.", passwords.MIN_LENGTH), code)
    if code == "password_too_long":
        raise AuthError(tr("Choose a password of at most {0} characters.", passwords.MAX_LENGTH), code)
    if code == "password_too_common":
        raise AuthError(tr("This password is one of the most common ones; choose another."), code)
    if code == "password_is_username":
        raise AuthError(tr("Your password can't be the same as your username."), code)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_config() -> dict:
    if not os.path.exists(config.AUTH_CONFIG_PATH):
        raise AuthError(tr("No accounts configured yet. Run manage_users.py add <username> on the server."))
    # A shared lock so a reader never observes the truncate-then-write window of
    # a concurrent `_locked_update` writer, which holds LOCK_EX on this file.
    with open(config.AUTH_CONFIG_PATH, "r", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        try:
            return _upgrade(yaml.safe_load(f))
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# Beta flags and token scopes renamed with the move to English names; an older
# config still has the old values. Read under the new name, written back on the
# next change.
_RENAMED_BETA = {"geldzaken": "money"}
_RENAMED_SCOPES = {"lezen": "read", "bijhouden": "write"}


def _upgrade(cfg: dict | None) -> dict | None:
    beta = (cfg or {}).get("beta")
    if isinstance(beta, dict):
        for old, new in _RENAMED_BETA.items():
            if old in beta:
                users = beta.pop(old) or []
                beta[new] = list(dict.fromkeys([*(beta.get(new) or []), *users]))
    users = (((cfg or {}).get("credentials") or {}).get("usernames") or {})
    for user in users.values():
        for token in (user or {}).get("agent_tokens") or []:
            if token.get("scope") in _RENAMED_SCOPES:
                token["scope"] = _RENAMED_SCOPES[token["scope"]]
    return cfg


def _dir_writable() -> bool:
    """The config's folder is writable: a bind-mounted directory (the mini PC,
    Railway's volume, a laptop) rather than a single bind-mounted file (the
    original Pi setup, whose parent dir in the container is read-only)."""
    return os.access(os.path.dirname(os.path.abspath(config.AUTH_CONFIG_PATH)) or ".", os.W_OK)


def _write_atomically(cfg: dict) -> None:
    """Temp file in the same folder, fsync, rename: a crash mid-write can never
    leave a half-written config (which would lock everyone out)."""
    import tempfile

    folder = os.path.dirname(os.path.abspath(config.AUTH_CONFIG_PATH))
    fd, tmp = tempfile.mkstemp(prefix=".auth_config.", suffix=".tmp", dir=folder)  # mode 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, config.AUTH_CONFIG_PATH)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.remove(tmp)
        raise


def save_config(cfg: dict) -> None:
    # Atomically when the folder allows it. With the config bind-mounted as a
    # single file (the original Pi setup) no neighbouring file can be created,
    # so it is written in place; `_locked_update` serialises writers and
    # `load_config` takes a shared lock, so that is safe against readers.
    if _dir_writable():
        with _lock_file():
            _write_atomically(cfg)
        return
    with open(config.AUTH_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    os.chmod(config.AUTH_CONFIG_PATH, 0o600)


@contextlib.contextmanager
def _lock_file():
    """An exclusive lock on a sidecar file. Used with atomic writes, where the
    config file itself is replaced (a lock on it would be on the old inode)."""
    path = config.AUTH_CONFIG_PATH + ".lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@contextlib.contextmanager
def _locked_update():
    """Serialise a read-modify-write of the config across processes and threads.

    With a writable folder: an exclusive lock on a sidecar `.lock` file, then
    an atomic replace of the config (readers always see a whole file).

    With the config bind-mounted as a single file (its parent dir isn't
    writable by the app user, so no neighbouring file can exist): the lock and
    the write both target the config file *itself*; `load_config`'s shared lock
    keeps readers off the truncate-then-rewrite window.

    Do NOT call `load_config` (or anything that does) inside the `with`: in
    the single-file mode it would try to take a shared lock on this
    already-exclusively-locked file and deadlock. Every mutator here threads
    the yielded cfg through instead.
    """
    if not os.path.exists(config.AUTH_CONFIG_PATH):
        raise AuthError(tr("No accounts configured yet. Run manage_users.py add <username> on the server."))
    if _dir_writable():
        with _lock_file():
            with open(config.AUTH_CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = _upgrade(yaml.safe_load(f)) or {}
            yield cfg
            _write_atomically(cfg)
        return
    with open(config.AUTH_CONFIG_PATH, "r+", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.seek(0)
            cfg = _upgrade(yaml.safe_load(f)) or {}
            yield cfg
            f.seek(0)
            f.truncate()
            yaml.safe_dump(cfg, f, sort_keys=False)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def is_admin(username: str, cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    return username in (cfg.get("admins") or [])


def is_suspended(username: str, cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    user = cfg.get("credentials", {}).get("usernames", {}).get(username)
    return bool(user and user.get("suspended"))


def has_beta(username: str, feature: str, cfg: dict | None = None) -> bool:
    cfg = cfg or load_config()
    if is_admin(username, cfg):
        return True
    beta = cfg.get("beta") or {}
    return username in (beta.get(feature) or [])


def user_beta_features(username: str, cfg: dict | None = None) -> list[str]:
    cfg = cfg or load_config()
    return [key for key in BETA_FEATURES if has_beta(username, key, cfg)]


def registration_mode(cfg: dict | None = None) -> str:
    """How self-service signup behaves right now.

    Falls back to the legacy meaning of `registration_code` when the newer
    `registration_mode` key is absent, so a config written by the old Streamlit
    app (or manage_users.py set-code) keeps behaving exactly as before.
    """
    cfg = cfg or load_config()
    mode = cfg.get("registration_mode")
    if mode in REGISTRATION_MODES:
        return mode
    return "invite" if cfg.get("registration_code") else "closed"


def canonical_username(username: str, cfg: dict | None = None) -> str | None:
    """The account name as stored, matched regardless of capitalisation.

    Every per-user path is derived from this string — data/users/<name>/ holds
    the portfolio database — so a login has to resolve to the *stored* spelling.
    Signing in as "Rene-001" when the account is "rene-001" otherwise opens a
    second, empty portfolio next to the real one and looks like data loss.

    Returns None if no account matches, in either spelling.
    """
    cfg = cfg if cfg is not None else load_config()
    users = cfg.get("credentials", {}).get("usernames", {}) or {}
    if username in users:
        return username
    lowered = (username or "").casefold()
    for stored in users:
        if stored.casefold() == lowered:
            return stored
    return None


def verify_credentials(username: str, password: str) -> dict | None:
    """Returns the user's config entry on success, None on bad username/password.

    A suspended account is *not* handled here — the caller distinguishes "wrong
    password" (401) from "suspended" (403), so this only proves the password.
    """
    cfg = load_config()
    stored_name = canonical_username(username, cfg)
    user = cfg.get("credentials", {}).get("usernames", {}).get(stored_name) if stored_name else None
    if not user:
        # Hash against a throwaway digest anyway. Short-circuiting on an unknown
        # username used to skip bcrypt entirely, so the *response time* answered
        # "does this account exist" on its own: ~236ms for a real name against
        # ~0.3ms for an unknown one, a difference far too large to need
        # statistics. Spending the same work here flattens that signal.
        security.verify_password(password, _ABSENT_USER_HASH)
        return None
    if not security.verify_password(password, user.get("password", "")):
        return None
    return user


def token_secret_and_expiry(cfg: dict | None = None) -> tuple[str, int]:
    """The key that signs session cookies, and how many days a session lasts
    (SESSION_DAYS; the old `cookie.expiry_days` in the file is ignored).

    A missing or short key is refused: a JWT signed with an empty key can be
    made by anyone."""
    cfg = cfg or load_config()
    key = str((cfg.get("cookie") or {}).get("key") or "")
    if len(key) < 16:
        raise AuthError(tr("The session signing key in auth_config.yaml is missing or too short."))
    return key, config.SESSION_DAYS


def register_user(
    username: str, name: str, password: str, invite_code: str, beta: tuple[str, ...] = ()
) -> None:
    """`beta`: flags the new account gets straight away (wealth-tracker grants `money`)."""
    with _locked_update() as cfg:
        mode = registration_mode(cfg)
        if mode == "closed":
            raise AuthError(tr("Self-service signup is currently closed."))
        personal = None
        if mode == "invite":
            personal = _usable_invite(cfg, invite_code)
            configured_code = cfg.get("registration_code")
            legacy_ok = bool(configured_code) and hmac.compare_digest(invite_code or "", str(configured_code))
            if not personal and not legacy_ok:
                raise AuthError(tr("Wrong invite code."))
        # mode == "open": anyone may sign up, no code required.

        if not USERNAME_RE.fullmatch(username or ""):
            raise AuthError(tr("Username must be letters, digits, '_' or '-' (max 40)."))
        # The tour's example account lives in data/users/ under these names.
        if (username or "").lower().startswith("_example"):
            raise AuthError(tr("That username is already taken."))

        users = cfg.setdefault("credentials", {}).setdefault("usernames", {})
        # Capitalisation does not make a new account. Two names that differ only
        # in case each get their own data/users/ folder, so the second one is an
        # empty portfolio that its owner cannot tell apart from a broken app —
        # which is exactly how two accounts for the same person came to exist.
        if canonical_username(username, cfg):
            raise AuthError(tr("That username is already taken."))
        if not password:
            raise AuthError(tr("Password is required."))
        check_new_password(password, username)

        users[username] = {
            "name": name or username,
            "email": f"{username}@local",
            "password": security.hash_password(password),
            "created_at": _now_iso(),
        }
        if personal is not None:
            personal["used_by"] = username
            personal["used_at"] = _now_iso()
            # Betas the admin chose for this link come with the account.
            beta = (*beta, *(personal.get("beta") or []))
        for feature in beta:
            if feature in BETA_FEATURES:
                granted = cfg.setdefault("beta", {}).setdefault(feature, [])
                if username not in granted:
                    granted.append(username)


def record_login(username: str) -> None:
    """Stamp the user's last successful login. Best-effort — never blocks login."""
    try:
        with _locked_update() as cfg:
            user = cfg.get("credentials", {}).get("usernames", {}).get(username)
            if user is not None:
                user["last_login"] = _now_iso()
    except Exception:
        pass


def set_locale(username: str, locale: str) -> None:
    """The language the user chose in the app ("nl" or "en"), stored with the account."""
    if locale not in LOCALES:
        raise AuthError(tr("Choose a language: {0}.", ", ".join(LOCALES)))
    with _locked_update() as cfg:
        user = cfg.get("credentials", {}).get("usernames", {}).get(username)
        if user is None:
            raise AuthError(tr("No such account: {0}.", username))
        user["locale"] = locale


def get_locale(username: str) -> str | None:
    """The stored language of the account, or None when it never chose one."""
    user = load_config().get("credentials", {}).get("usernames", {}).get(username) or {}
    return user.get("locale")


# --- Admin-only mutations -------------------------------------------------
# Each re-checks admin against the freshly-loaded config rather than trusting
# the caller: the session cookie says who you are, the config says what that is
# allowed to do. The router's require_admin dependency enforces it too — this
# is defence in depth, not the only gate.


def _require_admin(actor: str, cfg: dict) -> None:
    if not is_admin(actor, cfg):
        raise AuthError(tr("Admin only."))


def _existing_user(cfg: dict, username: str) -> dict:
    user = cfg.get("credentials", {}).get("usernames", {}).get(username)
    if user is None:
        raise AuthError(tr("No such account: {0}.", username))
    return user


def set_registration_mode(actor: str, mode: str, code: str | None = None) -> None:
    if mode not in REGISTRATION_MODES:
        raise AuthError(tr("Unknown registration mode: {0}.", mode))
    with _locked_update() as cfg:
        _require_admin(actor, cfg)
        if code and code.strip():
            # The old shared code, still settable (manage_users.py, scripts); the
            # admin page hands out a link per person instead (create_invite).
            cfg["registration_code"] = code.strip()
        cfg["registration_mode"] = mode


# --- invite links -------------------------------------------------------------


def _parse(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None


def _usable_invite(cfg: dict, code: str | None) -> dict | None:
    """The unused, unexpired personal invite with this code, or None."""
    if not code:
        return None
    now = datetime.now(timezone.utc)
    for inv in cfg.get("invites") or []:
        if inv.get("used_by") or not hmac.compare_digest(str(inv.get("code", "")), code):
            continue
        expires = _parse(inv.get("expires_at"))
        if expires is None or expires > now:
            return inv
    return None


def create_invite(actor: str, days: int | None, beta: list[str] | None = None) -> dict:
    """A link for one person. `days` None: no expiry. `beta`: flags the account
    gets straight away when it signs up with this link."""
    if days is not None and not 1 <= days <= 90:
        raise AuthError(tr("An invite is valid for 1 to 90 days."))
    unknown = set(beta or []) - set(BETA_FEATURES)
    if unknown:
        raise AuthError(tr("Unknown beta feature(s): {0}", ", ".join(sorted(unknown))))
    with _locked_update() as cfg:
        _require_admin(actor, cfg)
        inv = {
            "code": secrets.token_urlsafe(9),
            "created_by": actor,
            "created_at": _now_iso(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=days)).replace(microsecond=0).isoformat() if days else None,
            "used_by": None,
            "used_at": None,
            "beta": [f for f in BETA_FEATURES if f in (beta or [])],
        }
        # Keep the list short: drop links that were used or expired more than 30 days ago.
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        keep = []
        for old in cfg.get("invites") or []:
            ended = _parse(old.get("used_at")) or _parse(old.get("expires_at"))
            if ended is None or ended > cutoff:
                keep.append(old)
        cfg["invites"] = keep + [inv]
        return dict(inv)


def list_invites(cfg: dict | None = None) -> list[dict]:
    """Open invites (unused, unexpired), newest first."""
    cfg = cfg or load_config()
    now = datetime.now(timezone.utc)
    out = []
    for inv in cfg.get("invites") or []:
        expires = _parse(inv.get("expires_at"))
        if not inv.get("used_by") and (expires is None or expires > now):
            out.append(dict(inv))
    return sorted(out, key=lambda i: i.get("created_at") or "", reverse=True)


def delete_invite(actor: str, code: str) -> bool:
    with _locked_update() as cfg:
        _require_admin(actor, cfg)
        before = cfg.get("invites") or []
        cfg["invites"] = [i for i in before if i.get("code") != code]
        return len(cfg["invites"]) < len(before)


def clear_registration_code(actor: str) -> None:
    """Retire the old shared invite code: from now on only personal links work."""
    with _locked_update() as cfg:
        _require_admin(actor, cfg)
        cfg.pop("registration_code", None)


def set_beta_features(actor: str, selections: dict[str, list[str]]) -> None:
    with _locked_update() as cfg:
        _require_admin(actor, cfg)
        new_beta = {f: sorted(set(users)) for f, users in selections.items() if users}
        if new_beta:
            cfg["beta"] = new_beta
        else:
            cfg.pop("beta", None)


def set_beta(actor: str, folder: str, feature: str, enabled: bool) -> None:
    """One beta flag on or off for one data folder (the trackerai.nl admin page), in the same `beta` lists."""
    if feature not in BETA_FEATURES:
        raise AuthError(tr("Unknown beta feature(s): {0}", feature))
    with _locked_update() as cfg:
        _require_admin(actor, cfg)
        granted = set((cfg.get("beta") or {}).get(feature) or [])
        if enabled:
            granted.add(folder)
        else:
            granted.discard(folder)
        if granted:
            cfg.setdefault("beta", {})[feature] = sorted(granted)
        else:
            (cfg.get("beta") or {}).pop(feature, None)
            if not cfg.get("beta"):
                cfg.pop("beta", None)


def granted_betas(folder: str, cfg: dict | None = None) -> list[str]:
    """The betas granted to this folder, in BETA_FEATURES order: not the ones an admin has for being admin."""
    beta = (cfg if cfg is not None else load_config_or_empty()).get("beta") or {}
    return [f for f in BETA_FEATURES if folder in (beta.get(f) or [])]


def reset_password(actor: str, target: str, new_password: str | None = None) -> str | None:
    """Set a new password. Without one, a temporary password is made and returned, for the admin to pass on."""
    temporary = None
    if not new_password:
        new_password = temporary = secrets.token_urlsafe(12)
    else:
        check_new_password(new_password, target)
    with _locked_update() as cfg:
        _require_admin(actor, cfg)
        user = _existing_user(cfg, target)
        user["password"] = security.hash_password(new_password)
        # The admin reset is also the way back for someone who lost their
        # authenticator and backup codes: it turns two-step login off.
        user.pop("totp", None)
        user.pop("totp_pending", None)
        # An admin reset is the response to a suspected compromise, so it has to
        # log the intruder out too: without this the target's existing cookies
        # kept working for the rest of their 30 days. Nothing re-issues a cookie
        # here — the target is signed out everywhere, which is the intent.
        user["pw_changed_at"] = int(time.time())
    return temporary


def set_admin(actor: str, target: str, value: bool) -> None:
    with _locked_update() as cfg:
        _require_admin(actor, cfg)
        _existing_user(cfg, target)
        admins = cfg.setdefault("admins", [])
        if value:
            if target not in admins:
                admins.append(target)
        else:
            # Never let the last admin be demoted — that locks everyone out of
            # the panel with no way back except editing YAML on the server.
            if target in admins and len(admins) == 1:
                raise AuthError(tr("Can't remove the last admin."))
            if target in admins:
                admins.remove(target)


def set_suspended(actor: str, target: str, value: bool) -> None:
    with _locked_update() as cfg:
        _require_admin(actor, cfg)
        if target == actor:
            raise AuthError(tr("You can't suspend your own account."))
        user = _existing_user(cfg, target)
        if value:
            user["suspended"] = True
        else:
            user.pop("suspended", None)


def delete_user(actor: str, target: str) -> None:
    """Remove an account from the config. Caller deletes the data dir separately."""
    with _locked_update() as cfg:
        _require_admin(actor, cfg)
        if target == actor:
            raise AuthError(tr("You can't delete your own account."))
        users = cfg.get("credentials", {}).get("usernames", {})
        if target not in users:
            raise AuthError(tr("No such account: {0}.", target))
        admins = cfg.get("admins") or []
        if target in admins and len(admins) == 1:
            raise AuthError(tr("Can't delete the last admin."))
        del users[target]
        if target in admins:
            admins.remove(target)
        # Drop the departed user from every beta grant list too.
        for grantees in (cfg.get("beta") or {}).values():
            if target in grantees:
                grantees.remove(target)


def delete_own_account(username: str) -> None:
    """Remove the account itself from the config (S10). The last admin cannot:
    nobody would be left to run the server's admin page."""
    with _locked_update() as cfg:
        users = cfg.get("credentials", {}).get("usernames", {})
        if username not in users:
            raise AuthError(tr("No such account: {0}.", username))
        admins = cfg.get("admins") or []
        if username in admins and len(admins) == 1:
            raise AuthError(tr("You are the last admin. Make someone else admin first."), "last_admin")
        del users[username]
        if username in admins:
            admins.remove(username)
        for grantees in (cfg.get("beta") or {}).values():
            if username in grantees:
                grantees.remove(username)


# --- wealth-tracker's own users, under the shared accounts (core/accounts.py) ---
#
# The login, password and two-step login moved to the shared trackerai account.
# What stays here per data folder: the display name, the beta flags, the admins
# of wealth-tracker, agent tokens and bookkeeping.


def users_or_empty() -> dict:
    try:
        return load_config().get("credentials", {}).get("usernames", {}) or {}
    except AuthError:
        return {}


def _ensure_file() -> None:
    """An empty config on a fresh installation, where the first account comes from the shared accounts."""
    if os.path.exists(config.AUTH_CONFIG_PATH):
        return
    os.makedirs(os.path.dirname(os.path.abspath(config.AUTH_CONFIG_PATH)) or ".", exist_ok=True)
    try:
        fd = os.open(config.AUTH_CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.safe_dump({"credentials": {"usernames": {}}}, f, sort_keys=False)


def ensure_user(folder: str, name: str, beta: list[str] | tuple[str, ...] = ()) -> None:
    """wealth-tracker's entry for a data folder (an account's first visit), with the betas it starts with."""
    _ensure_file()
    with _locked_update() as cfg:
        users = cfg.setdefault("credentials", {}).setdefault("usernames", {})
        users.setdefault(folder, {"name": name or folder, "created_at": _now_iso()})
        for feature in beta:
            if feature in BETA_FEATURES:
                granted = cfg.setdefault("beta", {}).setdefault(feature, [])
                if folder not in granted:
                    granted.append(folder)


def grant_beta(folder: str, feature: str) -> None:
    ensure_user(folder, folder, (feature,))


def invite_betas(codes: list[str]) -> list[str]:
    """The betas an admin chose for these invitation codes (set_invite_betas)."""
    chosen = load_config_or_empty().get("invite_betas") or {}
    return sorted({b for c in codes for b in chosen.get(c) or []})


def set_invite_betas(code: str, beta: list[str]) -> None:
    _ensure_file()
    with _locked_update() as cfg:
        if beta:
            cfg.setdefault("invite_betas", {})[code] = [b for b in beta if b in BETA_FEATURES]


def load_config_or_empty() -> dict:
    try:
        return load_config() or {}
    except AuthError:
        return {}


def decrypt_totp_secret(value: str | None) -> str | None:
    return _decrypt_secret(value) if value else None


def forget_login(folder: str) -> None:
    """The password and two-step secret of a folder whose login moved to the shared accounts."""
    with _locked_update() as cfg:
        user = cfg.get("credentials", {}).get("usernames", {}).get(folder)
        if user is not None:
            for key in ("password", "totp", "totp_pending", "pw_changed_at", "email"):
                user.pop(key, None)


def remove_user(folder: str) -> None:
    """A folder's entry, its admin flag and its betas (the account left wealth-tracker or was deleted)."""
    if not os.path.exists(config.AUTH_CONFIG_PATH):
        return
    with _locked_update() as cfg:
        cfg.get("credentials", {}).get("usernames", {}).pop(folder, None)
        admins = cfg.get("admins") or []
        if folder in admins:
            admins.remove(folder)
        for grantees in (cfg.get("beta") or {}).values():
            if folder in grantees:
                grantees.remove(folder)


def list_users(actor: str) -> list[dict]:
    cfg = load_config()
    _require_admin(actor, cfg)
    admins = set(cfg.get("admins") or [])
    beta = cfg.get("beta") or {}
    out = []
    for uname, info in (cfg.get("credentials", {}).get("usernames", {}) or {}).items():
        out.append({
            "username": uname,
            "name": info.get("name", uname),
            "is_admin": uname in admins,
            "suspended": bool(info.get("suspended")),
            "created_at": info.get("created_at"),
            "last_login": info.get("last_login"),
            "beta_features": [f for f, users in beta.items() if uname in users],
        })
    return sorted(out, key=lambda u: u["username"])


# --- agent tokens (MCP and scripts) -----------------------------------------
#
# A token lets an AI assistant (over MCP, see routers/mcp.py) or a script act as
# one account, without that account's password. Only a SHA-256 of the token is
# stored, next to the account in auth_config.yaml; the token itself is shown once.
#
# Every token has a scope:
#   read       read everything the account can read, change nothing
#   write      read, plus the handful of bookkeeping writes in deps.AGENT_WRITES
#              (labelling, budgets, category rules) — never uploads, deletes,
#              bank connections, accounts or admin.

AGENT_SCOPES = ("read", "write")
AGENT_TOKEN_PREFIX = "st_"


def _token_hash(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode()).hexdigest()


AGENT_MAX_DAYS = 365


def create_agent_token(username: str, name: str, scope: str, expires_days: int | None = None) -> dict:
    """Make a token for `username`. Returns the stored entry plus the token itself (shown once).

    `expires_days`: after that many days the token stops working (S8); None: no
    end date, the user revokes it."""
    import secrets

    if scope not in AGENT_SCOPES:
        raise AuthError(tr("Choose a level: {0}.", ', '.join(AGENT_SCOPES)))
    if expires_days is not None and not 1 <= int(expires_days) <= AGENT_MAX_DAYS:
        raise AuthError(tr("A token is valid for 1 to {0} days, or without an end date.", AGENT_MAX_DAYS))
    name = (name or "").strip()[:60] or "Agent"
    token = AGENT_TOKEN_PREFIX + secrets.token_urlsafe(32)
    entry = {
        "id": secrets.token_hex(8),
        "name": name,
        "scope": scope,
        "hash": _token_hash(token),
        "created_at": _now_iso(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=int(expires_days))).replace(microsecond=0).isoformat()
        if expires_days else None,
    }
    with _locked_update() as cfg:
        user = _existing_user(cfg, username)
        user.setdefault("agent_tokens", []).append(entry)
    return {**_public_token(entry), "token": token}


def _expired(entry: dict) -> bool:
    expires = _parse(entry.get("expires_at"))
    return expires is not None and expires <= datetime.now(timezone.utc)


def _public_token(entry: dict) -> dict:
    out = {k: entry.get(k) for k in ("id", "name", "scope", "created_at", "last_used", "expires_at")}
    out["expired"] = _expired(entry)
    return out


def list_agent_tokens(username: str, cfg: dict | None = None) -> list[dict]:
    cfg = cfg or load_config()
    user = cfg.get("credentials", {}).get("usernames", {}).get(username) or {}
    return [_public_token(t) for t in user.get("agent_tokens") or []]


def delete_agent_token(username: str, token_id: str) -> bool:
    with _locked_update() as cfg:
        user = _existing_user(cfg, username)
        tokens = user.get("agent_tokens") or []
        kept = [t for t in tokens if t.get("id") != token_id]
        user["agent_tokens"] = kept
        return len(kept) != len(tokens)


def resolve_agent_token(token: str, cfg: dict | None = None) -> tuple[str, dict] | None:
    """(username, token entry) for a valid token, else None. Compares hashes in constant time."""
    if not token or not token.startswith(AGENT_TOKEN_PREFIX):
        return None
    cfg = cfg or load_config()
    wanted = _token_hash(token)
    for username, user in (cfg.get("credentials", {}).get("usernames", {}) or {}).items():
        for entry in user.get("agent_tokens") or []:
            if hmac.compare_digest(entry.get("hash", ""), wanted):
                return None if _expired(entry) else (username, entry)
    return None


def record_agent_use(username: str, token_id: str) -> None:
    """Stamp when a token was last used, at most every five minutes. Best-effort, like record_login."""
    try:
        cfg = load_config()
        user = cfg.get("credentials", {}).get("usernames", {}).get(username) or {}
        entry = next((t for t in user.get("agent_tokens") or [] if t.get("id") == token_id), None)
        last = (entry or {}).get("last_used")
        if entry is None or (last and (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() < 300):
            return
        with _locked_update() as cfg:
            user = cfg.get("credentials", {}).get("usernames", {}).get(username) or {}
            for t in user.get("agent_tokens") or []:
                if t.get("id") == token_id:
                    t["last_used"] = _now_iso()
    except Exception:
        pass


# --- two-step login from before the accounts (S14) ----------------------------
#
# Two-step login is the shared account's now (packages/accounts). A login not
# moved yet still has, in auth_config.yaml,
#   totp: {secret: <encrypted>, enabled: true, last_step: <int>, backup_codes: [<sha256>, ...]}
# encrypted with the bank keys' key (secret_box); it moves along on the first
# login (core/accounts.py bring_in).


def _encrypt_secret(value: str) -> str:
    from domain import secret_box

    return secret_box.encrypt(value.encode())


def _decrypt_secret(value: str) -> str | None:
    from domain import secret_box

    try:
        return secret_box.decrypt(value).decode()
    except secret_box.Unreadable:
        return None
