"""The rules of one account for every app: registration, login, password, two-step login, which apps an account uses,
and the admin's tools. The routes (routes.py) are a thin layer over this; the apps call it for what is theirs (for
instance `local_key` and `pending_purges`).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta, timezone

import bcrypt
from sqlalchemy import and_, delete, func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from trackerai_accounts import crypto, mail, passwords, totp
from trackerai_accounts.config import APPS, CONSENT_APPS, LOCALES, Config
from trackerai_accounts.errors import AccountError
from trackerai_accounts.store import account_apps, accounts, audit, daily_use, email_codes, invites, settings

USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,39}$")
RESERVED = frozenset({"admin", "root", "system", "example", "_example", "trackerai", "support"})
REGISTRATION_MODES = ("closed", "invite", "open")
PRIVACY_VERSION = "2026-10-07"
LOGIN_FAILURES = 10  # per account, within LOGIN_WINDOW: shared by every app, since it lives in the database
LOGIN_WINDOW = timedelta(minutes=15)
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
CODE_MINUTES = 10  # how long a code by email works
CODE_ATTEMPTS = 5  # wrong tries before a code is spent
CODES_PER_WINDOW = 5  # codes sent per account within LOGIN_WINDOW
# Checked when the username does not exist, so a wrong name costs as much time as a wrong password.
DUMMY_HASH = bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt(rounds=12)).decode()


def now() -> datetime:
    return datetime.now(UTC)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    """Constant work: without a hash the dummy is checked and the answer is False."""
    try:
        ok = bcrypt.checkpw((password or "").encode()[:72], (hashed or DUMMY_HASH).encode())
    except (ValueError, TypeError):
        return False
    return ok and bool(hashed)


def check_new_password(password: str, username: str | None = None) -> None:
    code = passwords.check_password(password, username)
    if code == "password_too_short":
        raise AccountError(422, code, min=passwords.MIN_LENGTH)
    if code == "password_too_long":
        raise AccountError(422, code, max=passwords.MAX_LENGTH)
    if code:
        raise AccountError(422, code)


def _check_app(app: str) -> None:
    if app not in APPS:
        raise AccountError(422, "unknown_app", options=list(APPS))


def _check_locale(locale: str | None) -> None:
    if locale is not None and locale not in LOCALES:
        raise AccountError(422, "invalid_locale", options=list(LOCALES))


def mask_email(email: str | None) -> str | None:
    """j…@gmail.com: enough to recognise your own address, not enough to read someone else's."""
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    return f"{local[0]}…@{domain}"


def _check_email(email: str | None) -> str:
    email = (email or "").strip().lower()
    if len(email) > 254 or not EMAIL.match(email):
        raise AccountError(422, "email_invalid")
    return email


def _check_name(name: str | None) -> str | None:
    name = (name or "").strip()
    if len(name) > 80:
        raise AccountError(422, "name_too_long", max=80)
    return name or None


class Accounts:
    def __init__(self, engine: Engine, config: Config, mailer=None):
        self.engine = engine
        self.config = config
        # Sends the codes by email (mail.py); None: two-step login is the authenticator app only.
        self.mailer = mailer if mailer is not None else mail.mailer_for(config)

    # --- reading ---------------------------------------------------------------------------------------------------

    def get(self, account_id: int) -> dict | None:
        with self.engine.connect() as c:
            row = c.execute(select(accounts).where(accounts.c.id == account_id)).mappings().first()
        return dict(row) if row else None

    def by_username(self, username: str) -> dict | None:
        with self.engine.connect() as c:
            row = c.execute(select(accounts).where(accounts.c.username == (username or "").strip().lower())).mappings().first()
        return dict(row) if row else None

    def apps(self, account_id: int, with_leaving: bool = False) -> dict[str, dict]:
        """The apps this account uses: {app: row}. Without `with_leaving`, apps still deleting its data are left out."""
        with self.engine.connect() as c:
            rows = c.execute(select(account_apps).where(account_apps.c.account_id == account_id)).mappings().all()
        return {r["app"]: dict(r) for r in rows if with_leaving or r["leaving_at"] is None}

    def count(self) -> int:
        with self.engine.connect() as c:
            return c.execute(select(func.count()).select_from(accounts).where(accounts.c.deleted_at.is_(None))).scalar_one()

    def totp_required(self, account: dict, apps: dict | None = None) -> bool:
        """Whether this account must use two-step login, by REQUIRE_TOTP."""
        policy = self.config.require_totp
        if policy == "off":
            return False
        if policy == "all":
            return True
        if account.get("is_admin"):
            return True
        if policy == "admins":
            return False
        apps = self.apps(account["id"]) if apps is None else apps
        return len(apps) > 1

    def view(self, account: dict, apps: dict | None = None) -> dict:
        """What the site may know about an account (never a hash or a secret)."""
        apps = self.apps(account["id"]) if apps is None else apps
        enabled = bool(account.get("totp_enabled_at"))
        by_email = bool(account.get("email_codes_at"))
        required = self.totp_required(account, apps)
        return {
            "id": account["id"],
            "username": account["username"],
            "display_name": account.get("display_name"),
            "locale": account.get("locale"),
            "is_admin": bool(account.get("is_admin")),
            "apps": sorted(apps),
            "app_admin": sorted(a for a, r in apps.items() if r.get("is_admin")),
            "totp_enabled": enabled,  # the authenticator app
            "email_codes": by_email,  # codes by email
            "email": account.get("email"),
            "email_verified": bool(account.get("email_verified_at")),
            # signed up with an address that is not confirmed yet: nothing opens until it is (with a mail server)
            "email_verify_required": self.email_verify_required(account),
            "two_step": enabled or by_email,  # either: the code a drastic step asks for
            "totp_required": required,
            "totp_setup_required": required and not (enabled or by_email),
            "totp_backup_codes_left": len(account.get("totp_backup") or []) if enabled else 0,
        }

    # --- registration ----------------------------------------------------------------------------------------------

    def registration_mode(self) -> str:
        if self.count() == 0:
            return "open"
        with self.engine.connect() as c:
            value = c.execute(select(settings.c.value).where(settings.c.key == "registration")).scalar_one_or_none()
        return value if value in REGISTRATION_MODES else "closed"

    def register(
        self,
        username: str,
        password: str,
        app: str,
        display_name: str | None = None,
        invite: str | None = None,
        locale: str | None = None,
        consent: bool = False,
        email: str | None = None,
        apps: list[str] | None = None,
    ) -> dict:
        """A new account. It needs an email address: a welcome mail brings a code that confirms it, and until then the
        account answers `email_verify_required` (Sessions.ready). Confirmed, it is the account's two-step login.
        `apps`: the trackers it starts with, chosen at sign-up on the front door (default: just `app`)."""
        chosen = list(dict.fromkeys(apps or [app]))
        for a in chosen:
            _check_app(a)
        _check_locale(locale)
        email = _check_email(email)
        mode = self.registration_mode()
        first = self.count() == 0
        if mode == "closed":
            raise AccountError(403, "registration_closed")
        code = (invite or "").strip()
        invite_row = self._usable_invite(code) if mode == "invite" else None
        if mode == "invite" and not invite_row:
            raise AccountError(403, "invalid_invite")
        name = (username or "").strip().lower()
        if not USERNAME.match(name):
            raise AccountError(422, "invalid_username")
        if name in RESERVED:
            raise AccountError(409, "username_reserved")
        if self.by_username(name):
            raise AccountError(409, "username_taken")
        check_new_password(password, name)
        if self._email_taken(email):
            raise AccountError(409, "email_taken")
        display = _check_name(display_name)
        apps = list(dict.fromkeys([*chosen, *((invite_row or {}).get("apps") or [])]))
        apps = [a for a in apps if a in APPS]
        if any(a in CONSENT_APPS for a in apps) and not consent:
            raise AccountError(422, "consent_required")
        t = now()
        with self.engine.begin() as c:
            if invite_row:
                # one use: the second of two sign-ups racing for one code loses it
                used = c.execute(
                    update(invites).where(and_(invites.c.code == code, invites.c.used_by.is_(None))).values(used_at=t, used_by=-1)
                ).rowcount
                if not used:
                    raise AccountError(403, "invalid_invite")
            account_id = c.execute(
                insert(accounts).values(
                    username=name,
                    display_name=display,
                    password_hash=hash_password(password),
                    password_changed_at=t,
                    session_version=0,
                    is_admin=first,
                    suspended=False,
                    locale=locale,
                    failed_logins=0,
                    created_at=t,
                    last_login_at=t,
                    email=email,
                )
            ).inserted_primary_key[0]
            for a in apps:
                c.execute(
                    insert(account_apps).values(
                        account_id=account_id,
                        app=a,
                        is_admin=first,
                        enabled_at=t,
                        consent_at=t if a in CONSENT_APPS else None,
                        privacy_version=PRIVACY_VERSION,
                    )
                )
            if invite_row:
                c.execute(update(invites).where(invites.c.code == code).values(used_by=account_id))
        account = self.get(account_id)
        if self.mailer:
            try:
                self._send_code(account, "verify", email, welcome=True)
            except AccountError:
                pass  # the account stands; the page offers to send the code again
        return account

    def bootstrap(self, username: str, password_hash: str, app: str, local_key: str) -> dict | None:
        """A fresh installation whose first admin comes from the environment (an app's own old login setting):
        that account, linked to the app's existing user. Does nothing once there is any account."""
        if self.count() or not (username and password_hash):
            return None
        return self.create_linked(username, password_hash, app, local_key, is_admin=True)

    def create_linked(
        self,
        username: str,
        password_hash: str,
        app: str,
        local_key: str,
        is_admin: bool = False,
        display_name: str | None = None,
        locale: str | None = None,
        suspended: bool = False,
        totp_secret: str | None = None,
        totp_backup: list | None = None,
        app_admin: bool | None = None,
    ) -> dict:
        """An account for a user an app already has (a seeded demo user, the environment's first admin, someone from
        before the accounts logging in for the first time), with that user's password hash and, when they had it, their
        two-step login (`totp_secret` in plain, encrypted here). The app consented on the person's behalf when it made
        the user."""
        _check_app(app)
        name = username.strip().lower()
        if self.by_username(name):
            raise AccountError(409, "username_taken")
        t = now()
        totp_values = {}
        if totp_secret:
            totp_values = dict(
                totp_secret=crypto.encrypt(totp_secret, self.config.encryption_key), totp_enabled_at=t, totp_backup=list(totp_backup or [])
            )
        with self.engine.begin() as c:
            account_id = c.execute(
                insert(accounts).values(
                    username=name,
                    display_name=display_name,
                    password_hash=password_hash,
                    password_changed_at=t,
                    session_version=0,
                    is_admin=is_admin,
                    suspended=suspended,
                    locale=locale if locale in LOCALES else None,
                    failed_logins=0,
                    created_at=t,
                    **totp_values,
                )
            ).inserted_primary_key[0]
            c.execute(
                insert(account_apps).values(
                    account_id=account_id,
                    app=app,
                    local_key=str(local_key),
                    is_admin=is_admin if app_admin is None else app_admin,
                    enabled_at=t,
                    consent_at=t,
                    privacy_version=PRIVACY_VERSION,
                )
            )
        return self.get(account_id)

    # --- login -----------------------------------------------------------------------------------------------------

    def _password_ok(self, account: dict | None, password: str) -> bool:
        if verify_password(password, account["password_hash"] if account else None):
            return True
        return any(verify_password(password, h) for h in (account or {}).get("legacy_password_hashes") or [])

    def _throttled(self, account: dict) -> bool:
        since = account.get("failed_since")
        return bool(since and now() - since < LOGIN_WINDOW and (account.get("failed_logins") or 0) >= LOGIN_FAILURES)

    def _failed(self, account: dict) -> None:
        since = account.get("failed_since")
        with self.engine.begin() as c:
            if since and now() - since < LOGIN_WINDOW:
                c.execute(update(accounts).where(accounts.c.id == account["id"]).values(failed_logins=accounts.c.failed_logins + 1))
            else:
                c.execute(update(accounts).where(accounts.c.id == account["id"]).values(failed_logins=1, failed_since=now()))

    def login(self, username: str, password: str, code: str | None = None, trusted_device=None, send_email: bool = False) -> dict:
        """The account for a right username, password and (with two-step login on) code. Raises AccountError.
        `trusted_device(account)`: this browser gave the code before and asked to be remembered (session.py), so the
        code is not asked again. With codes by email, a right password without a code mails one (`email_code_sent`);
        `send_email` asks for one when the account has the app too."""
        account = self.by_username(username)
        if account and account.get("deleted_at"):
            account = None
        if account and self._throttled(account):
            raise AccountError(429, "too_many_attempts", headers={"Retry-After": str(int(LOGIN_WINDOW.total_seconds()))})
        if not self._password_ok(account, (password or "")[: passwords.MAX_LENGTH]) or not account:
            if account:
                self._failed(account)
            raise AccountError(401, "bad_credentials")
        if account["suspended"]:
            raise AccountError(403, "account_suspended")
        if self.two_step(account) and not ((code or "").strip() == "" and trusted_device and trusted_device(account)):
            if not (code or "").strip():
                # The password was right: the page asks for the code.
                if account.get("email_codes_at") and (send_email or not account.get("totp_enabled_at")):
                    self.send_login_code(account)
                    raise AccountError(401, "email_code_sent", to=mask_email(account.get("email")))
                raise AccountError(401, "totp_required", email=bool(account.get("email_codes_at") and self.mailer))
            if not self.second_factor_ok(account, code):
                self._failed(account)
                raise AccountError(401, "totp_invalid")
        with self.engine.begin() as c:
            c.execute(
                update(accounts).where(accounts.c.id == account["id"]).values(last_login_at=now(), failed_logins=0, failed_since=None)
            )
        return self.get(account["id"])

    def reauthenticate(self, account_id: int, password: str, code: str | None = None) -> dict:
        """For something drastic (delete, leave an app, two-step login off): the password, and the code when it is on."""
        account = self.get(account_id)
        if not account or self._throttled(account):
            raise AccountError(429, "too_many_attempts")
        if not self._password_ok(account, (password or "")[: passwords.MAX_LENGTH]):
            self._failed(account)
            raise AccountError(403, "wrong_current_password")
        if self.two_step(account):
            if not (code or "").strip():
                raise AccountError(401, "totp_required", email=bool(account.get("email_codes_at") and self.mailer))
            if not self.second_factor_ok(account, code):
                self._failed(account)
                raise AccountError(401, "totp_invalid")
        return account

    def session_account(self, claims: dict | None) -> dict | None:
        """The account a session belongs to, while it is still valid for it."""
        sub = (claims or {}).get("sub")
        if not (isinstance(sub, str) and sub.startswith("a:") and sub[2:].isdigit()):
            return None
        account = self.get(int(sub[2:]))
        if not account or account["suspended"] or account.get("deleted_at"):
            return None
        if int(claims.get("sv") or 0) != (account["session_version"] or 0):
            return None  # the password, two-step login or an admin ended this session
        return account

    def _bump(self, c, account_id: int) -> None:
        c.execute(update(accounts).where(accounts.c.id == account_id).values(session_version=accounts.c.session_version + 1))

    # --- the account itself ----------------------------------------------------------------------------------------

    def update_profile(self, account_id: int, display_name: str | None = None, locale: str | None = None) -> dict:
        _check_locale(locale)
        values = {}
        if display_name is not None:
            values["display_name"] = _check_name(display_name)
        if locale is not None:
            values["locale"] = locale
        if values:
            with self.engine.begin() as c:
                c.execute(update(accounts).where(accounts.c.id == account_id).values(**values))
        return self.get(account_id)

    def change_password(self, account_id: int, current: str, new: str) -> dict:
        """Every other session ends; the caller gives this browser a new one (the returned account's version)."""
        account = self.get(account_id)
        if not account or not self._password_ok(account, (current or "")[: passwords.MAX_LENGTH]):
            raise AccountError(403, "wrong_current_password")
        check_new_password(new, account["username"])
        with self.engine.begin() as c:
            c.execute(
                update(accounts)
                .where(accounts.c.id == account_id)
                .values(password_hash=hash_password(new), legacy_password_hashes=None, password_changed_at=now())
            )
            self._bump(c, account_id)
        return self.get(account_id)

    # --- two-step login --------------------------------------------------------------------------------------------

    @staticmethod
    def two_step(account: dict) -> bool:
        return bool(account.get("totp_enabled_at") or account.get("email_codes_at"))

    def second_factor_ok(self, account: dict, code: str | None) -> bool:
        """A code from the app (each only once), an unused backup code (used up now) or a code by email."""
        if not code:
            return False
        if account.get("email_codes_at") and self._use_code(account["id"], "login", code):
            return True
        if not account.get("totp_secret") or not account.get("totp_enabled_at"):
            return False
        try:
            secret = crypto.decrypt(account["totp_secret"], self.config.encryption_key)
        except crypto.WrongKey:
            secret = None  # another key: only a backup code (or the admin) helps
        if secret:
            step = totp.verify(secret, code, account.get("totp_last_step"))
            if step is not None:
                last = accounts.c.totp_last_step
                with self.engine.begin() as c:
                    # only if no other request used this step or a later one meanwhile
                    done = c.execute(
                        update(accounts)
                        .where(and_(accounts.c.id == account["id"], (last.is_(None)) | (last < step)))
                        .values(totp_last_step=step)
                    ).rowcount
                return bool(done)
        with self.engine.begin() as c:
            row = c.execute(select(accounts.c.totp_backup).where(accounts.c.id == account["id"]).with_for_update()).first()
            left = totp.use_backup_code(code, (row[0] if row else None) or [])
            if left is None:
                return False
            c.execute(update(accounts).where(accounts.c.id == account["id"]).values(totp_backup=left))
        return True

    # --- codes by email --------------------------------------------------------------------------------------------

    def _code_hash(self, account_id: int, purpose: str, code: str) -> str:
        digits = "".join(ch for ch in code if ch.isdigit())
        return hmac.new(self.config.session_secret.encode(), f"{account_id}:{purpose}:{digits}".encode(), hashlib.sha256).hexdigest()

    def email_verify_required(self, account: dict) -> bool:
        return bool(self.mailer and account.get("email") and not account.get("email_verified_at"))

    def _email_taken(self, email: str, account_id: int | None = None) -> bool:
        with self.engine.connect() as c:
            q = select(accounts.c.id).where(and_(accounts.c.email == email, accounts.c.deleted_at.is_(None)))
            if account_id is not None:
                q = q.where(accounts.c.id != account_id)
            return c.execute(q).first() is not None

    def _send_code(self, account: dict, purpose: str, to: str, welcome: bool = False) -> None:
        """A new code to `to`; earlier ones for the same purpose stop working. At most CODES_PER_WINDOW per account."""
        if not self.mailer:
            raise AccountError(503, "email_unavailable")
        since = now() - LOGIN_WINDOW
        with self.engine.begin() as c:
            sent = c.execute(
                select(func.count())
                .select_from(email_codes)
                .where(and_(email_codes.c.account_id == account["id"], email_codes.c.created_at >= since))
            ).scalar_one()
            if sent >= CODES_PER_WINDOW:
                raise AccountError(429, "too_many_codes", headers={"Retry-After": str(int(LOGIN_WINDOW.total_seconds()))})
            c.execute(delete(email_codes).where(email_codes.c.created_at < now() - timedelta(days=1)))
            c.execute(
                update(email_codes)
                .where(and_(email_codes.c.account_id == account["id"], email_codes.c.purpose == purpose, email_codes.c.used_at.is_(None)))
                .values(used_at=now())
            )
            code = f"{secrets.randbelow(10**6):06d}"
            c.execute(
                insert(email_codes).values(
                    account_id=account["id"],
                    purpose=purpose,
                    email=to,
                    code_hash=self._code_hash(account["id"], purpose, code),
                    attempts=0,
                    created_at=now(),
                    expires_at=now() + timedelta(minutes=CODE_MINUTES),
                )
            )
        if welcome:
            subject, body = mail.welcome_mail(code, account["username"], account.get("locale"), CODE_MINUTES)
        else:
            subject, body = mail.login_code_mail(code, account.get("locale"), CODE_MINUTES, verify=purpose == "verify")
        try:
            self.mailer.send(to, subject, body)
        except Exception as e:  # the mail server said no, or is unreachable
            raise AccountError(503, "email_unavailable") from e

    def _use_code(self, account_id: int, purpose: str, code: str) -> dict | None:
        """The code's row when `code` is the latest one for this purpose, still valid; it is spent now."""
        with self.engine.begin() as c:
            row = (
                c.execute(
                    select(email_codes)
                    .where(and_(email_codes.c.account_id == account_id, email_codes.c.purpose == purpose, email_codes.c.used_at.is_(None)))
                    .order_by(email_codes.c.id.desc())
                    .limit(1)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if not row or row["expires_at"] < now() or row["attempts"] >= CODE_ATTEMPTS:
                return None
            if not hmac.compare_digest(row["code_hash"], self._code_hash(account_id, purpose, code)):
                c.execute(update(email_codes).where(email_codes.c.id == row["id"]).values(attempts=email_codes.c.attempts + 1))
                return None
            c.execute(update(email_codes).where(email_codes.c.id == row["id"]).values(used_at=now()))
            return dict(row)

    def send_login_code(self, account: dict) -> str | None:
        """A login code to the account's address (also for a drastic step: deleting, leaving an app). Returns where to,
        masked."""
        if not account.get("email_codes_at") or not account.get("email"):
            raise AccountError(409, "email_codes_off")
        self._send_code(account, "login", account["email"])
        return mask_email(account["email"])

    def email_start(self, account_id: int, password: str, email: str, code: str | None = None) -> str:
        """Codes by email, step one: the password (and the code, when two-step login is on already) and an address; a
        code goes to that address. Returns the address."""
        email = _check_email(email)
        account = self.reauthenticate(account_id, password, code)
        if self._email_taken(email, account_id):
            raise AccountError(409, "email_taken")
        self._send_code(account, "verify", email)
        return email

    def resend_signup_code(self, account_id: int, email: str | None = None) -> str:
        """The welcome code again, while the address from sign-up is not confirmed; `email` corrects a typo in it."""
        account = self.get(account_id)
        if not account.get("email") or account.get("email_verified_at"):
            raise AccountError(409, "email_already_verified")
        if email:
            email = _check_email(email)
            if self._email_taken(email, account_id):
                raise AccountError(409, "email_taken")
            with self.engine.begin() as c:
                c.execute(update(accounts).where(accounts.c.id == account_id).values(email=email))
            account = self.get(account_id)
        self._send_code(account, "verify", account["email"], welcome=True)
        return account["email"]

    def email_confirm(self, account_id: int, code: str) -> dict:
        """Codes by email, step two: the code from that mail. Codes by email are on; other sessions end."""
        row = self._use_code(account_id, "verify", code or "")
        if not row:
            raise AccountError(422, "totp_invalid")
        with self.engine.begin() as c:
            taken = c.execute(select(accounts.c.id).where(and_(accounts.c.email == row["email"], accounts.c.id != account_id))).first()
            if taken:
                raise AccountError(409, "email_taken")
            c.execute(
                update(accounts)
                .where(accounts.c.id == account_id)
                .values(email=row["email"], email_verified_at=now(), email_codes_at=now())
            )
            self._bump(c, account_id)
        return self.get(account_id)

    def email_disable(self, account_id: int, password: str, code: str) -> dict:
        """Off, with the password and a code (from the app, a backup code or a mail). The address is forgotten."""
        account = self.get(account_id)
        if not account.get("email_codes_at"):
            raise AccountError(409, "email_codes_off")
        if not (code or "").strip():
            raise AccountError(401, "totp_required", email=bool(self.mailer))
        self.reauthenticate(account_id, password, code)
        with self.engine.begin() as c:
            c.execute(update(accounts).where(accounts.c.id == account_id).values(email=None, email_verified_at=None, email_codes_at=None))
            c.execute(delete(email_codes).where(email_codes.c.account_id == account_id))
            self._bump(c, account_id)
        return self.get(account_id)

    def totp_setup(self, account_id: int) -> dict:
        """A new secret for the authenticator app; two-step login is on once `totp_enable` confirms a code from it."""
        account = self.get(account_id)
        if account.get("totp_enabled_at"):
            raise AccountError(409, "totp_already_enabled")
        if not crypto.valid_key(self.config.encryption_key):
            raise AccountError(500, "accounts_key_missing")
        secret = totp.new_secret()
        with self.engine.begin() as c:
            c.execute(
                update(accounts)
                .where(accounts.c.id == account_id)
                .values(totp_secret=crypto.encrypt(secret, self.config.encryption_key), totp_last_step=None, totp_backup=None)
            )
        return {"secret": secret, "otpauth_uri": totp.otpauth_uri(secret, account["username"], self.config.issuer)}

    def totp_enable(self, account_id: int, code: str) -> list[str]:
        """Confirm with a code from the app; returns the backup codes (shown once). Other sessions end."""
        account = self.get(account_id)
        if account.get("totp_enabled_at"):
            raise AccountError(409, "totp_already_enabled")
        if not account.get("totp_secret"):
            raise AccountError(409, "totp_not_set_up")
        try:
            secret = crypto.decrypt(account["totp_secret"], self.config.encryption_key)
        except crypto.WrongKey:
            raise AccountError(409, "totp_not_set_up")
        step = totp.verify(secret, code)
        if step is None:
            raise AccountError(422, "totp_invalid")
        codes, hashes = totp.new_backup_codes()
        with self.engine.begin() as c:
            c.execute(
                update(accounts).where(accounts.c.id == account_id).values(totp_enabled_at=now(), totp_last_step=step, totp_backup=hashes)
            )
            self._bump(c, account_id)
        return codes

    def totp_disable(self, account_id: int, password: str, code: str) -> dict:
        account = self.get(account_id)
        if not account.get("totp_enabled_at"):
            raise AccountError(409, "totp_not_set_up")
        # Also when it is required: that is how someone moves to a new phone. The account then answers
        # `totp_setup_required` until it is set up again (Sessions.ready), so it is never off in use.
        if not (code or "").strip():
            raise AccountError(401, "totp_required")
        self.reauthenticate(account_id, password, code)
        with self.engine.begin() as c:
            c.execute(
                update(accounts)
                .where(accounts.c.id == account_id)
                .values(totp_secret=None, totp_enabled_at=None, totp_last_step=None, totp_backup=None)
            )
            self._bump(c, account_id)
        return self.get(account_id)

    def new_backup_codes(self, account_id: int, code: str) -> list[str]:
        """A fresh set of backup codes (the old ones stop working), confirmed with a code from the app."""
        account = self.get(account_id)
        if not account.get("totp_enabled_at"):
            raise AccountError(409, "totp_not_set_up")
        if not self.second_factor_ok(account, code):
            raise AccountError(422, "totp_invalid")
        codes, hashes = totp.new_backup_codes()
        with self.engine.begin() as c:
            c.execute(update(accounts).where(accounts.c.id == account_id).values(totp_backup=hashes))
        return codes

    # --- apps ------------------------------------------------------------------------------------------------------

    def join_app(self, account_id: int, app: str, consent: bool = False) -> dict:
        """Start using another app: on an open installation anyone may, otherwise the admin gives access."""
        _check_app(app)
        account = self.get(account_id)
        current = self.apps(account_id, with_leaving=True)
        if app in current:
            if current[app]["leaving_at"] is not None:
                raise AccountError(409, "app_leaving")
            if app in CONSENT_APPS and current[app]["consent_at"] is None:
                if not consent:
                    raise AccountError(422, "consent_required")
                self.give_consent(account_id, app)  # given the app by an admin: consents on the first visit
            return self.apps(account_id)[app]
        if self.registration_mode() != "open" and not account["is_admin"]:
            raise AccountError(403, "app_not_available")
        if app in CONSENT_APPS and not consent:
            raise AccountError(422, "consent_required")
        self._add_app(account_id, app, consent_at=now() if app in CONSENT_APPS else None)
        return self.apps(account_id)[app]

    def _add_app(self, account_id: int, app: str, is_admin: bool = False, consent_at: datetime | None = None) -> None:
        with self.engine.begin() as c:
            c.execute(
                insert(account_apps).values(
                    account_id=account_id,
                    app=app,
                    is_admin=is_admin,
                    enabled_at=now(),
                    consent_at=consent_at,
                    privacy_version=PRIVACY_VERSION,
                )
            )

    def leave_app(self, account_id: int, app: str) -> None:
        """Stop using an app: the app deletes this account's data in it (`pending_purges`), then the row goes."""
        _check_app(app)
        with self.engine.begin() as c:
            done = c.execute(
                update(account_apps)
                .where(and_(account_apps.c.account_id == account_id, account_apps.c.app == app, account_apps.c.leaving_at.is_(None)))
                .values(leaving_at=now())
            ).rowcount
        if not done:
            raise AccountError(404, "not_in_app")

    def local_key(self, account_id: int, app: str) -> str | None:
        row = self.apps(account_id).get(app)
        return row["local_key"] if row else None

    def set_local_key(self, account_id: int, app: str, key: str) -> None:
        """The app's own key for this account (its user id or data folder), set when the app first meets it."""
        with self.engine.begin() as c:
            c.execute(
                update(account_apps)
                .where(and_(account_apps.c.account_id == account_id, account_apps.c.app == app))
                .values(local_key=str(key))
            )

    def account_id_for_local_key(self, app: str, key: str) -> int | None:
        """Whatever the account's state (the admin pages map the app's users to accounts with it)."""
        with self.engine.connect() as c:
            row = c.execute(
                select(account_apps.c.account_id).where(and_(account_apps.c.app == app, account_apps.c.local_key == str(key)))
            ).first()
        return row[0] if row else None

    def account_for_local_key(self, app: str, key: str) -> dict | None:
        """The account behind an app's own key (for an agent token, which the app resolves to its own user)."""
        with self.engine.connect() as c:
            row = c.execute(
                select(account_apps.c.account_id).where(
                    and_(account_apps.c.app == app, account_apps.c.local_key == str(key), account_apps.c.leaving_at.is_(None))
                )
            ).first()
        account = self.get(row[0]) if row else None
        if not account or account["suspended"] or account.get("deleted_at"):
            return None
        return account

    def pending_purges(self, app: str) -> list[dict]:
        """Accounts whose data this app still has to delete: [{account_id, local_key}]."""
        with self.engine.connect() as c:
            rows = (
                c.execute(
                    select(account_apps.c.account_id, account_apps.c.local_key).where(
                        and_(account_apps.c.app == app, account_apps.c.leaving_at.is_not(None))
                    )
                )
                .mappings()
                .all()
            )
        return [dict(r) for r in rows]

    def purged(self, account_id: int, app: str) -> None:
        """The app deleted its data for this account. A deleted account goes once no app holds anything of it."""
        with self.engine.begin() as c:
            c.execute(delete(account_apps).where(and_(account_apps.c.account_id == account_id, account_apps.c.app == app)))
            left = c.execute(select(func.count()).select_from(account_apps).where(account_apps.c.account_id == account_id)).scalar_one()
            if not left:
                c.execute(delete(accounts).where(and_(accounts.c.id == account_id, accounts.c.deleted_at.is_not(None))))

    def delete_account(self, account_id: int) -> None:
        """The whole account, in every app (the caller reauthenticated). Logging in stops at once; each app deletes
        its data on its next sweep, and the row goes with the last."""
        account = self.get(account_id)
        if account["is_admin"] and self._other_admins(account_id) == 0 and self.count() > 1:
            raise AccountError(409, "last_admin")
        with self.engine.begin() as c:
            c.execute(update(accounts).where(accounts.c.id == account_id).values(deleted_at=now()))
            c.execute(delete(daily_use).where(daily_use.c.account_id == account_id))
            self._bump(c, account_id)
            c.execute(
                update(account_apps)
                .where(and_(account_apps.c.account_id == account_id, account_apps.c.leaving_at.is_(None)))
                .values(leaving_at=now())
            )
            left = c.execute(select(func.count()).select_from(account_apps).where(account_apps.c.account_id == account_id)).scalar_one()
            if not left:
                c.execute(delete(accounts).where(accounts.c.id == account_id))

    def _other_admins(self, account_id: int) -> int:
        with self.engine.connect() as c:
            return c.execute(
                select(func.count())
                .select_from(accounts)
                .where(and_(accounts.c.is_admin.is_(True), accounts.c.id != account_id, accounts.c.deleted_at.is_(None)))
            ).scalar_one()

    # --- admin -----------------------------------------------------------------------------------------------------

    def _audit(self, actor: dict, action: str, target: str | None = None, detail: str | None = None) -> None:
        with self.engine.begin() as c:
            c.execute(insert(audit).values(at=now(), actor=actor["username"], action=action, target=target, detail=detail))

    def list_audit(self, limit: int = 30) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(audit).order_by(audit.c.id.desc()).limit(limit)).mappings().all()
        return [dict(r) for r in rows]

    # --- usage: page visits per day, app and account (a count, never which pages) ------------------------------------

    VISITS_PER_DAY = 5000  # a loop or a script, not a person: more is not counted

    def record_visit(self, account_id: int, app: str) -> None:
        """One page visit in `app` today (UTC)."""
        if app not in APPS:
            return
        day = now().date()
        key = and_(daily_use.c.day == day, daily_use.c.app == app, daily_use.c.account_id == account_id)
        count = update(daily_use).where(key, daily_use.c.visits < self.VISITS_PER_DAY).values(visits=daily_use.c.visits + 1)
        with self.engine.begin() as c:
            if c.execute(count).rowcount or c.execute(select(daily_use.c.visits).where(key)).first() is not None:
                return
        try:
            with self.engine.begin() as c:
                c.execute(insert(daily_use).values(day=day, app=app, account_id=account_id, visits=1))
        except IntegrityError:  # the same account's other tab got there first
            with self.engine.begin() as c:
                c.execute(count)

    def usage(self, weeks: int = 12) -> dict:
        """For the admin page: per app and ISO week (Monday, oldest first, the current one last) the page visits and the
        number of accounts that visited, the accounts active in the last 7 and 30 days (any app), and each account's
        last day with a visit."""
        today = now().date()
        monday = today - timedelta(days=today.weekday())
        mondays = [monday - timedelta(weeks=n) for n in range(weeks - 1, -1, -1)]
        with self.engine.connect() as c:
            rows = c.execute(select(daily_use).where(daily_use.c.day >= mondays[0])).mappings().all()
            last = c.execute(select(daily_use.c.account_id, func.max(daily_use.c.day)).group_by(daily_use.c.account_id)).all()
        index = {m: i for i, m in enumerate(mondays)}
        visits = {app: [0] * weeks for app in APPS}
        people = {app: [set() for _ in mondays] for app in APPS}
        recent = {7: set(), 30: set()}
        for r in rows:
            day = r["day"] if not isinstance(r["day"], datetime) else r["day"].date()
            i = index.get(day - timedelta(days=day.weekday()))
            if i is None or r["app"] not in visits:
                continue
            visits[r["app"]][i] += r["visits"]
            people[r["app"]][i].add(r["account_id"])
            for days in recent:
                if (today - day).days < days:
                    recent[days].add(r["account_id"])
        return {
            "weeks": [m.isoformat() for m in mondays],
            "apps": {app: {"visits": visits[app], "users": [len(s) for s in people[app]]} for app in APPS},
            "active_7": len(recent[7]),
            "active_30": len(recent[30]),
            "last_seen": {str(aid): day.isoformat() for aid, day in last if day is not None},
        }

    def list_accounts(self) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(accounts).where(accounts.c.deleted_at.is_(None)).order_by(accounts.c.username)).mappings().all()
            apps = c.execute(select(account_apps)).mappings().all()
        by_account: dict[int, dict] = {}
        for a in apps:
            by_account.setdefault(a["account_id"], {})[a["app"]] = dict(a)
        out = []
        for r in rows:
            mine = {k: v for k, v in by_account.get(r["id"], {}).items() if v["leaving_at"] is None}
            out.append(
                {
                    **self.view(dict(r), mine),
                    "suspended": bool(r["suspended"]),
                    "created_at": r["created_at"],
                    "last_login_at": r["last_login_at"],
                    "local_keys": {a: v["local_key"] for a, v in mine.items()},
                }
            )
        return out

    def _target(self, account_id: int) -> dict:
        target = self.get(account_id)
        if not target or target.get("deleted_at"):
            raise AccountError(404, "account_not_found")
        return target

    def set_flags(self, actor: dict, account_id: int, is_admin: bool | None = None, suspended: bool | None = None) -> dict:
        target = self._target(account_id)
        if account_id == actor["id"] and (is_admin is False or suspended):
            raise AccountError(422, "cannot_demote_self")
        values = {}
        if is_admin is not None:
            values["is_admin"] = is_admin
            self._audit(actor, "make_admin" if is_admin else "remove_admin", target["username"])
        if suspended is not None:
            values["suspended"] = suspended
            self._audit(actor, "block" if suspended else "unblock", target["username"])
        if values:
            with self.engine.begin() as c:
                c.execute(update(accounts).where(accounts.c.id == account_id).values(**values))
        return self.get(account_id)

    def set_app(self, actor: dict, account_id: int, app: str, enabled: bool | None = None, is_admin: bool | None = None) -> dict:
        """Give or take an app (taking deletes the account's data in it), or make someone that app's admin."""
        _check_app(app)
        target = self._target(account_id)
        current = self.apps(account_id, with_leaving=True)
        if enabled and app not in current:
            # consent for health data is asked of the person on their first visit (the app checks `consent_at`)
            self._add_app(account_id, app)
            self._audit(actor, "give_app", target["username"], app)
        elif enabled is False and app in current and current[app]["leaving_at"] is None:
            self.leave_app(account_id, app)
            self._audit(actor, "take_app", target["username"], app)
        if is_admin is not None and app in self.apps(account_id):
            with self.engine.begin() as c:
                c.execute(
                    update(account_apps)
                    .where(and_(account_apps.c.account_id == account_id, account_apps.c.app == app))
                    .values(is_admin=is_admin)
                )
            self._audit(actor, "app_admin" if is_admin else "remove_app_admin", target["username"], app)
        return self.apps(account_id)

    def give_consent(self, account_id: int, app: str) -> None:
        with self.engine.begin() as c:
            c.execute(
                update(account_apps)
                .where(and_(account_apps.c.account_id == account_id, account_apps.c.app == app))
                .values(consent_at=now(), privacy_version=PRIVACY_VERSION)
            )

    def can_manage(self, actor: dict, actor_app_admin: str | None, account_id: int) -> bool:
        """Whether `actor` may block, reset or delete this account: an account admin always; an app's admin
        (`actor_app_admin`: the app they administer) only for accounts that use no other app."""
        if actor.get("is_admin"):
            return True
        if not actor_app_admin:
            return False
        apps = set(self.apps(account_id, with_leaving=True))
        target = self.get(account_id)
        return bool(target) and not target.get("is_admin") and apps <= {actor_app_admin}

    def reset_password(self, actor: dict, account_id: int, new_password: str | None = None) -> str | None:
        """A temporary password for someone who forgot theirs (returned), or the one the admin chose; whoever was
        logged in is out."""
        target = self._target(account_id)
        if new_password:
            check_new_password(new_password, target["username"])
        temporary = new_password or secrets.token_urlsafe(12)
        with self.engine.begin() as c:
            c.execute(
                update(accounts)
                .where(accounts.c.id == account_id)
                .values(
                    password_hash=hash_password(temporary),
                    legacy_password_hashes=None,
                    password_changed_at=now(),
                    failed_logins=0,
                    failed_since=None,
                )
            )
            self._bump(c, account_id)
        self._audit(actor, "reset_password", target["username"])
        return None if new_password else temporary

    def reset_totp(self, actor: dict, account_id: int) -> dict:
        """For someone who lost both the phone and the backup codes (or the mailbox): two-step login off, the app and
        email both. Their sessions end; with two-step login required, they set it up again at their next login."""
        target = self._target(account_id)
        with self.engine.begin() as c:
            c.execute(
                update(accounts)
                .where(accounts.c.id == account_id)
                .values(
                    totp_secret=None,
                    totp_enabled_at=None,
                    totp_last_step=None,
                    totp_backup=None,
                    email=None,
                    email_verified_at=None,
                    email_codes_at=None,
                )
            )
            self._bump(c, account_id)
        self._audit(actor, "reset_totp", target["username"])
        return self.get(account_id)

    def admin_delete(self, actor: dict, account_id: int, confirm: str) -> None:
        target = self._target(account_id)
        if account_id == actor["id"]:
            raise AccountError(422, "cannot_delete_self")
        if confirm != target["username"]:
            raise AccountError(422, "confirm_username")
        self.delete_account(account_id)
        self._audit(actor, "delete_account", target["username"])

    def set_registration_mode(self, actor: dict, mode: str) -> None:
        if mode not in REGISTRATION_MODES:
            raise AccountError(422, "invalid_registration_mode", options=list(REGISTRATION_MODES))
        with self.engine.begin() as c:
            if c.execute(update(settings).where(settings.c.key == "registration").values(value=mode)).rowcount == 0:
                c.execute(insert(settings).values(key="registration", value=mode))
        self._audit(actor, "registration", detail=mode)

    def _usable_invite(self, code: str) -> dict | None:
        if not code:
            return None
        with self.engine.connect() as c:
            row = c.execute(select(invites).where(invites.c.code == code)).mappings().first()
        if not row or row["used_by"] is not None:
            return None
        expires = row["expires_at"]
        if expires and expires < now():
            return None
        return dict(row)

    def create_invite(self, actor: dict, days: int | None = 14, apps: list[str] | None = None) -> dict:
        for a in apps or []:
            _check_app(a)
        code = secrets.token_urlsafe(8)
        expires = now() + timedelta(days=days) if days else None
        with self.engine.begin() as c:
            c.execute(insert(invites).values(code=code, created_by=actor["id"], created_at=now(), expires_at=expires, apps=apps or []))
        self._audit(actor, "invite", detail=",".join(apps or []) or None)
        return {"code": code, "expires_at": expires.isoformat() if expires else None, "apps": apps or []}

    def list_invites(self) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(invites).order_by(invites.c.created_at.desc())).mappings().all()
        return [dict(r) for r in rows]

    def delete_invite(self, actor: dict, code: str) -> None:
        with self.engine.begin() as c:
            c.execute(delete(invites).where(invites.c.code == code))
        self._audit(actor, "revoke_invite")
