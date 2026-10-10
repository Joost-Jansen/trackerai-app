"""Bring the existing accounts of both apps into the one accounts database. Run once per installation, first without
--apply to read the plan:

    ACCOUNTS_DATABASE_URL=... ACCOUNTS_ENCRYPTION_KEY=... python -m trackerai_accounts.migrate \\
        --health-db postgresql://...     --health-key <health-tracker's APP_ENCRYPTION_KEY> \\
        --wealth-config auth_config.yaml --wealth-key <wealth-tracker's APP_ENCRYPTION_KEY> \\
        --same joost,tim --admins joost [--rename Tim=tim.w] [--apply]

- health-tracker's users come in first, with their password, two-step login and admin flag. Their health data stays
  where it is: the account links to the health user id.
- Then wealth-tracker's. A name that is free becomes a new account linked to the wealth data folder. A name that
  health-tracker already has is the same person only when listed in --same: then wealth is added to that account
  and the wealth password keeps working next to the health one until the password is changed. Any other clash
  stops the import, unless --rename gives the wealth account another name.
- Two-step login comes along (secrets re-encrypted with the accounts key). When someone had it in both apps, the
  health-tracker secret is kept; their wealth authenticator entry can go.
- Account admins (who manage everyone's account, in every app) are those in --admins, or else those who were
  admin in every app they used. Each app's own admin flag comes along as that app's admin.
- Registration takes the stricter of the two apps' modes. Unused invitation codes do not come along.

Running it again skips what was already imported.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

import yaml
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import MetaData, Table, create_engine, insert, select, update

from trackerai_accounts import crypto
from trackerai_accounts.service import Accounts, now
from trackerai_accounts.store import account_apps, accounts, settings

STRICTNESS = ("closed", "invite", "open")


@dataclass
class Person:
    """One account to be, from one app."""

    app: str
    name: str  # the account name (lower case)
    local_key: str
    password_hash: str
    display_name: str | None = None
    is_admin: bool = False
    suspended: bool = False
    totp_secret: str | None = None  # plain, re-encrypted on write
    totp_enabled_at: datetime | None = None
    totp_backup: list | None = None
    locale: str | None = None
    created_at: datetime | None = None
    last_login_at: datetime | None = None
    consent_at: datetime | None = None
    privacy_version: str | None = None
    notes: list[str] = field(default_factory=list)


def _iso(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# --- reading the apps ----------------------------------------------------------------------------------------------

def read_health(url: str, key: str) -> tuple[list[Person], str | None]:
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    engine = create_engine(url)
    users = Table("users", MetaData(), autoload_with=engine)
    user_settings = Table("settings", MetaData(), autoload_with=engine)
    app_settings = Table("app_settings", MetaData(), autoload_with=engine)
    people = []
    with engine.connect() as c:
        locales = {r.user_id: r.value for r in c.execute(select(user_settings).where(user_settings.c.key == "locale"))}
        mode = c.execute(select(app_settings.c.value).where(app_settings.c.key == "registration")).scalar_one_or_none()
        for u in c.execute(select(users).order_by(users.c.id)).mappings():
            if u["username"].startswith("_"):
                continue  # the shared example account, not a person
            p = Person("health", u["username"].lower(), str(u["id"]), u["password_hash"], u.get("display_name"), bool(u["is_admin"]),
                       bool(u["suspended"]), locale=locales.get(u["id"]), created_at=_iso(u.get("created_at")),
                       last_login_at=_iso(u.get("last_login_at")), consent_at=_iso(u.get("consent_at")),
                       privacy_version=u.get("privacy_version"))
            if u.get("totp_enabled_at") and u.get("totp_secret"):
                try:
                    p.totp_secret = crypto.decrypt(u["totp_secret"], key)
                    p.totp_enabled_at, p.totp_backup = _iso(u["totp_enabled_at"]), list(u.get("totp_backup") or [])
                except crypto.WrongKey:
                    p.notes.append("two-step login could not be read with --health-key: set it up again")
            people.append(p)
    return people, mode if mode in STRICTNESS else "closed"


def read_wealth(path: str, keys: list[str], rename: dict[str, str]) -> tuple[list[Person], str]:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    box = MultiFernet([Fernet(k.encode()) for k in keys]) if keys else None
    admins = set(cfg.get("admins") or [])
    mode = cfg.get("registration_mode")
    if mode not in STRICTNESS:
        mode = "invite" if cfg.get("registration_code") else "closed"
    people = []
    for folder, u in ((cfg.get("credentials") or {}).get("usernames") or {}).items():
        u = u or {}
        p = Person("wealth", rename.get(folder, folder).lower(), folder, u.get("password") or "", u.get("name"), folder in admins,
                   bool(u.get("suspended")), locale=u.get("locale"), created_at=_iso(u.get("created_at")),
                   last_login_at=_iso(u.get("last_login")))
        state = u.get("totp") or {}
        if state.get("enabled") and state.get("secret"):
            try:
                if not box:
                    raise InvalidToken
                p.totp_secret = box.decrypt(state["secret"].encode()).decode()
                p.totp_enabled_at, p.totp_backup = _iso(state.get("enabled_at")) or now(), list(state.get("backup_codes") or [])
            except InvalidToken:
                p.notes.append("two-step login could not be read with --wealth-key: set it up again")
        people.append(p)
    return people, mode


# --- the plan ------------------------------------------------------------------------------------------------------

@dataclass
class Plan:
    new: list[Person] = field(default_factory=list)  # a new account
    joins: list[tuple[Person, Person]] = field(default_factory=list)  # (wealth person, the health account it joins)
    skipped: list[Person] = field(default_factory=list)  # already imported
    clashes: list[str] = field(default_factory=list)
    registration: str = "closed"
    admins: set[str] = field(default_factory=set)

    def report(self) -> str:
        lines = [f"registration: {self.registration}", f"account admins: {', '.join(sorted(self.admins)) or '(none)'}"]
        for p in self.new:
            lines.append(f"new      {p.name:<20} {p.app} ({p.local_key})" + ("  2FA" if p.totp_secret else "") + "".join(f"\n         ! {n}" for n in p.notes))
        for w, h in self.joins:
            note = "  2FA kept from health" if w.totp_secret and h.totp_secret else ("  2FA from wealth" if w.totp_secret else "")
            lines.append(f"join     {h.name:<20} health ({h.local_key}) + wealth ({w.local_key}){note}" + "".join(f"\n         ! {n}" for n in w.notes))
        for p in self.skipped:
            lines.append(f"done     {p.name:<20} {p.app} ({p.local_key}), imported before")
        for c in self.clashes:
            lines.append(f"CLASH    {c}")
        return "\n".join(lines)


def plan(target: Accounts, health: list[Person], wealth: list[Person], same: set[str], admins: set[str] | None,
         modes: list[str]) -> Plan:
    out = Plan(registration=min(modes, key=STRICTNESS.index) if modes else "closed")
    if target.count():
        with target.engine.connect() as c:
            existing = {(r.app, r.local_key) for r in c.execute(select(account_apps.c.app, account_apps.c.local_key))}
    else:
        existing = set()
    by_name: dict[str, Person] = {}
    for p in health:
        if ("health", p.local_key) in existing:
            out.skipped.append(p)
        else:
            out.new.append(p)
        by_name[p.name] = p
    taken = {a["username"] for a in target.list_accounts()} if target.count() else set()
    for w in wealth:
        if ("wealth", w.local_key) in existing:
            out.skipped.append(w)
            continue
        h = by_name.get(w.name)
        if h is not None and (w.name in same or w.local_key in same):
            out.joins.append((w, h))
        elif h is not None or w.name in taken or w.name in {p.name for p in out.new}:
            out.clashes.append(f"wealth-tracker's {w.local_key!r} and health-tracker's {w.name!r}: the same person? "
                               f"--same {w.name}; if not, --rename {w.local_key}=<another name>")
        else:
            out.new.append(w)
    if admins is not None:
        out.admins = set(admins)
    else:
        joined = {h.name: (h, w) for w, h in out.joins}
        for p in out.new:
            pair = joined.get(p.name)
            if (pair[0].is_admin and pair[1].is_admin) if pair else p.is_admin:
                out.admins.add(p.name)
    return out


def apply(target: Accounts, p: Plan) -> None:
    key = target.config.encryption_key
    t = now()

    def enc(secret: str | None) -> str | None:
        return crypto.encrypt(secret, key) if secret else None

    joins = {h.name: w for w, h in p.joins}
    with target.engine.begin() as c:
        for person in p.new:
            w = joins.get(person.name) if person.app == "health" else None
            secret = person.totp_secret or (w.totp_secret if w else None)
            source = person if person.totp_secret else w
            legacy = [w.password_hash] if w and w.password_hash and w.password_hash != person.password_hash else None
            account_id = c.execute(insert(accounts).values(
                username=person.name, display_name=person.display_name or (w.display_name if w else None),
                password_hash=person.password_hash, legacy_password_hashes=legacy, password_changed_at=t, session_version=0,
                totp_secret=enc(secret), totp_enabled_at=source.totp_enabled_at if secret else None,
                totp_backup=source.totp_backup if secret else None, is_admin=person.name in p.admins,
                suspended=person.suspended or bool(w and w.suspended), locale=person.locale or (w.locale if w else None),
                failed_logins=0, created_at=person.created_at or t, last_login_at=person.last_login_at)).inserted_primary_key[0]
            for member in [person] + ([w] if w else []):
                c.execute(insert(account_apps).values(
                    account_id=account_id, app=member.app, local_key=member.local_key, is_admin=member.is_admin, enabled_at=t,
                    consent_at=member.consent_at, privacy_version=member.privacy_version))
        for w, h in p.joins:
            if any(h is x for x in p.new):
                continue  # done above, with its health account
            row = c.execute(select(accounts).where(accounts.c.username == h.name)).mappings().first()
            if not row:
                continue
            c.execute(insert(account_apps).values(account_id=row["id"], app="wealth", local_key=w.local_key, is_admin=w.is_admin, enabled_at=t))
            legacy = list(row["legacy_password_hashes"] or [])
            if w.password_hash and w.password_hash != row["password_hash"] and w.password_hash not in legacy:
                c.execute(update(accounts).where(accounts.c.id == row["id"]).values(legacy_password_hashes=legacy + [w.password_hash]))
        if c.execute(update(settings).where(settings.c.key == "registration").values(value=p.registration)).rowcount == 0:
            c.execute(insert(settings).values(key="registration", value=p.registration))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--health-db")
    ap.add_argument("--health-key", default="")
    ap.add_argument("--wealth-config")
    ap.add_argument("--wealth-key", action="append", default=[], help="repeat for an older key")
    ap.add_argument("--same", default="", help="comma-separated names that are the same person in both apps")
    ap.add_argument("--rename", action="append", default=[], help="wealth name=new account name")
    ap.add_argument("--admins", default=None, help="comma-separated account admins")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    from trackerai_accounts import open_accounts

    target = open_accounts()
    problems = target.config.problems()
    if [x for x in problems if "SESSION_SECRET" not in x]:
        print("\n".join(problems), file=sys.stderr)
        return 2
    health, modes = [], []
    if args.health_db:
        health, mode = read_health(args.health_db, args.health_key)
        modes.append(mode)
    wealth = []
    if args.wealth_config:
        rename = dict(x.split("=", 1) for x in args.rename)
        wealth, mode = read_wealth(args.wealth_config, args.wealth_key, rename)
        modes.append(mode)
    same = {x.strip().lower() for x in args.same.split(",") if x.strip()}
    admins = {x.strip().lower() for x in args.admins.split(",") if x.strip()} if args.admins is not None else None
    p = plan(target, health, wealth, same, admins, modes)
    print(p.report())
    if p.clashes:
        print("\nNothing imported: resolve the clashes first.", file=sys.stderr)
        return 1
    if not args.apply:
        print("\nA plan only; run again with --apply to import.")
        return 0
    apply(target, p)
    print("\nImported.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
