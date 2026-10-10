"""
bank_link.py — your bank connected directly, per user.

Every user brings their own Enable Banking application: app ID and private key
(see bank_providers/enablebanking.py for why). This file stores them, handles
the consent at the bank, and fetches transactions and balances in the same
shape as a CSV import — so categories, reversals and net worth notice nothing.

Three agreements:

  * **The key never comes out again.** Stored encrypted (secret_box.py) and
    only used to sign requests; no endpoint returns it.
  * **Nothing twice.** An export and the connection describe the same booking
    with a different name and description. Fetching starts from the last day
    that is already there, and bank_transactions.save recognises a booking
    with the same date and amount as already present — in both directions: an
    export after connecting also only adds what was not there yet.
  * **No addresses in code.** Where the bank redirects back to follows from
    the address the app runs on; the user registers exactly that address at
    Enable Banking.
"""

import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone

from domain.money import bank_transactions
from domain.money import categorization
from domain import secret_box as secret
from domain.money import accounts
from domain.money.bank_providers import base
from domain.money.bank_providers import enablebanking
from domain.i18n import tr

BACK_PATH = "/api/connections/enablebanking/callback"
# Where the bank sent people back before the English rename. Still served, so a
# consent started under the old address (or an Enable Banking app that only
# lists the old redirect URL) completes.
LEGACY_BACK_PATH = "/api/koppelingen/enablebanking/terug"
# How far back for an account of which nothing is in the app yet. Banks often
# give no more; whatever they do give is a gain.
DEFAULT_BACK_DAYS = 730
# What a bank without a stated maximum gets as consent duration: the EU allows
# 180 days.
MAX_CONSENT = timedelta(days=180)
# A consent that waits at the bank this long has been abandoned: nobody comes
# back from their banking app after half an hour.
ABORTED_AFTER = timedelta(minutes=30)


class NotConfigured(Exception):
    """No app ID and private key have been stored yet."""


class UnknownConsent(Exception):
    """This return belongs to no consent we started."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


# ---------------------------------------------------------------------------
# The key
# ---------------------------------------------------------------------------

def save_key(conn: sqlite3.Connection, app_id: str, pem: bytes) -> None:
    app_id = (app_id or "").strip()
    if not app_id:
        raise ValueError(tr("Enter your app ID: the name of the .pem file, without .pem."))
    enablebanking.verify_key(pem)
    conn.execute(
        """
        INSERT INTO bank_connections (provider, app_id, key, created_at) VALUES (?, ?, ?, ?)
        ON CONFLICT(provider) DO UPDATE SET app_id = excluded.app_id, key = excluded.key
        """,
        (enablebanking.PROVIDER, app_id, secret.encrypt(pem), _now().isoformat()),
    )
    conn.commit()


def upgrade_secrets(conn: sqlite3.Connection) -> int:
    """Idempotent: encrypt Enable Banking session ids stored in plain text (from
    before they were encrypted), and re-encrypt what is still readable only with
    an older key (see secret_box: taking over the old key file). Returns how many
    values changed."""
    changed = 0
    for row in conn.execute("SELECT id, session_id FROM bank_consents WHERE session_id IS NOT NULL").fetchall():
        value = row["session_id"]
        try:
            if not secret.looks_encrypted(value):
                new = secret.encrypt(value.encode())
            elif secret.needs_rotation(value):
                new = secret.rotate(value)
            else:
                continue
        except secret.Unreadable:
            continue
        conn.execute("UPDATE bank_consents SET session_id = ? WHERE id = ?", (new, row["id"]))
        changed += 1
    for row in conn.execute("SELECT provider, key FROM bank_connections").fetchall():
        try:
            if row["key"] and secret.needs_rotation(row["key"]):
                conn.execute("UPDATE bank_connections SET key = ? WHERE provider = ?",
                             (secret.rotate(row["key"]), row["provider"]))
                changed += 1
        except Exception:
            continue
    if changed:
        conn.commit()
    return changed


def _session_id(value: str | None) -> str | None:
    """The Enable Banking session id, stored encrypted (plain text from before that still works)."""
    if not value:
        return None
    if not secret.looks_encrypted(value):
        return value
    try:
        return secret.decrypt(value).decode()
    except secret.Unreadable:
        return None


def _connection(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM bank_connections WHERE provider = ?",
                       (enablebanking.PROVIDER,)).fetchone()
    return dict(row) if row else None


def client(conn: sqlite3.Connection, http=None) -> enablebanking.Client:
    connection = _connection(conn)
    if not connection:
        raise NotConfigured(tr("First enter your app ID and upload your private key."))
    try:
        pem = secret.decrypt(connection["key"])
    except secret.Unreadable as e:
        raise NotConfigured(tr("Your private key can no longer be read; upload it again.")) from e
    return enablebanking.Client(connection["app_id"], pem, http=http)


def status(conn: sqlite3.Connection) -> dict:
    """What is set up, without the key."""
    upgrade_secrets(conn)
    connection = _connection(conn)
    consents = []
    for t in conn.execute("SELECT * FROM bank_consents ORDER BY lower(bank), id DESC"):
        t = dict(t)
        if t["status"] == "waiting" and _now() - datetime.fromisoformat(t["created_at"]) > ABORTED_AFTER:
            continue    # came back halfway: no connection, only noise
        if t["status"] == "active" and t["valid_until"] and datetime.fromisoformat(t["valid_until"]) <= _now():
            t["status"] = "expired"
        t["accounts"] = [
            {"id": r["id"], "name": r["name"], "iban": r["iban"]}
            for r in conn.execute(
                """SELECT r.id, r.name, r.iban FROM bank_consent_accounts k
                   JOIN accounts r ON r.id = k.account_id WHERE k.consent_id = ? ORDER BY r.name""",
                (t["id"],))
        ]
        for away in ("state", "session_id", "redirect_url"):
            t.pop(away, None)
        consents.append(t)
    return {
        "configured": connection is not None,
        "app_id": connection["app_id"] if connection else None,
        "consents": consents,
    }


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

def _verify_origin(origin: str) -> str:
    origin = (origin or "").strip().rstrip("/")
    local = origin.startswith(("http://localhost", "http://127.0.0.1"))
    if not (origin.startswith("https://") or local) or "/" in origin.split("://", 1)[1]:
        raise ValueError(tr("Unknown address of the app."))
    return origin


def start(conn: sqlite3.Connection, *, bank: str, country: str, origin: str, http=None) -> str:
    """Starts consent at `bank`; returns the address the user has to go to."""
    eb = client(conn, http)
    country = (country or "").strip().upper()
    found = next((b for b in eb.banks(country) if b.get("name") == bank), None)
    if found is None:
        raise ValueError(tr("'{0}' is not in Enable Banking's list for {1}.", bank, country))

    duration = MAX_CONSENT
    if found.get("maximum_consent_validity"):
        duration = min(duration, timedelta(seconds=int(found["maximum_consent_validity"])))
    valid_until = (_now() + duration).isoformat()

    redirect_url = _verify_origin(origin) + BACK_PATH
    state = secrets.token_urlsafe(24)
    answer = eb.start(bank=bank, country=country, redirect_url=redirect_url, state=state, valid_until=valid_until)
    # Trying again: an earlier failed or abandoned attempt at this bank no longer
    # matters. A working consent stays until the new one is there (complete).
    conn.execute("DELETE FROM bank_consents WHERE bank = ? AND country = ? AND status IN ('waiting', 'error')",
                 (bank, country))
    conn.execute(
        """INSERT INTO bank_consents (bank, country, state, redirect_url, valid_until, status, created_at)
           VALUES (?, ?, ?, ?, ?, 'waiting', ?)""",
        (bank, country, state, redirect_url, valid_until, _now().isoformat()),
    )
    conn.commit()
    return answer["url"]


def by_state(conn: sqlite3.Connection, state: str) -> dict | None:
    """The address of the app where this consent started and at which bank, for
    the redirect back.
    """
    row = conn.execute("SELECT bank, redirect_url FROM bank_consents WHERE state = ?", (state,)).fetchone()
    if not row:
        return None
    url = row["redirect_url"] or ""
    for path in (BACK_PATH, LEGACY_BACK_PATH):
        if url.endswith(path):
            url = url[: -len(path)]
            break
    return {"app": url, "bank": row["bank"]}


def failed(conn: sqlite3.Connection, state: str, message: str) -> None:
    conn.execute("UPDATE bank_consents SET status = 'error', error = ?, state = NULL WHERE state = ?",
                 (message[:500], state))
    conn.commit()


def _provider_for(bank: str) -> str:
    name = bank.strip().lower()
    return name if name in accounts.PROVIDERS else enablebanking.PROVIDER


def complete(conn: sqlite3.Connection, *, state: str, code: str, http=None) -> int:
    """The user is back from their bank: create the session and link the accounts."""
    row = conn.execute("SELECT * FROM bank_consents WHERE state = ? AND status = 'waiting'",
                       (state,)).fetchone()
    if not row:
        raise UnknownConsent(tr("This consent is unknown or already completed."))
    consent = dict(row)

    session = client(conn, http).session(code)
    # The bank decides until when; if it says nothing, what we asked for applies.
    conn.execute(
        "UPDATE bank_consents SET session_id = ?, valid_until = COALESCE(?, valid_until), status = 'active', "
        "state = NULL, error = NULL WHERE id = ?",
        # The session id is what reads your accounts at the bank: encrypted like the key.
        (secret.encrypt(str(session["session_id"]).encode()), (session.get("access") or {}).get("valid_until"), consent["id"]),
    )
    for account in session.get("accounts", []):
        iban = base.normalise_iban((account.get("account_id") or {}).get("iban"))
        bank_account = accounts.search_on_iban(conn, iban) if iban else None
        if bank_account is None:
            behind = (iban or account["uid"])[-4:]
            account_id = accounts.make_bank_account(
                conn, kind="bank", provider=_provider_for(consent["bank"]),
                name=f"{consent['bank']} ···{behind}", iban=iban,
                currency=account.get("currency") or base.CURRENCY,
            )
        else:
            account_id = bank_account["id"]
        conn.execute(
            "INSERT OR REPLACE INTO bank_consent_accounts (consent_id, account_uid, account_id) "
            "VALUES (?, ?, ?)",
            (consent["id"], account["uid"], account_id),
        )
    conn.commit()

    # One consent per bank: the new one replaces what was already there at this
    # bank (a renewal, or connecting an earlier time). Otherwise every account
    # would be fetched through two sessions and you no longer see which applies.
    for old in conn.execute("SELECT id FROM bank_consents WHERE bank = ? AND country = ? AND id != ?",
                            (consent["bank"], consent["country"], consent["id"])).fetchall():
        delete_consent(conn, old["id"], http)
    return consent["id"]


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _from(rules: list[dict], last: str | None) -> list[dict]:
    """Only from the last day that is already there. What was already on that day —
    from an export or an earlier fetch — bank_transactions.save recognises by
    date and amount.
    """
    return [r for r in rules if not last or r["date"] >= last]


def fetch(conn: sqlite3.Connection, *, http=None, today: date | None = None,
            only_if_older_than: timedelta | None = None) -> dict:
    """Fetches balances and new transactions for every active consent.

    Fetched when you ask for it, and by itself when you open the app — then with
    `only_if_older_than`, so a tab you open often does not query the bank every
    time. Not in the background: someone who does not use the app has nothing to
    gain from fresh figures, and a bank counts every request.
    """
    today = today or date.today()
    upgrade_secrets(conn)
    eb = client(conn, http)
    report = {"accounts": 0, "added": 0, "balances": 0, "errors": [], "skipped": 0}

    for t in [dict(r) for r in conn.execute("SELECT * FROM bank_consents WHERE status = 'active'")]:
        if (only_if_older_than is not None and t["last_fetched"]
                and _now() - datetime.fromisoformat(t["last_fetched"]) < only_if_older_than):
            report["skipped"] += 1
            continue
        if t["valid_until"] and datetime.fromisoformat(t["valid_until"]) <= _now():
            conn.execute("UPDATE bank_consents SET status = 'expired' WHERE id = ?", (t["id"],))
            report["errors"].append(tr("The consent at {0} has expired; give consent again.", t['bank']))
            continue
        try:
            for link in conn.execute("SELECT * FROM bank_consent_accounts WHERE consent_id = ?",
                                       (t["id"],)).fetchall():
                account = accounts.load_account(conn, link["account_id"])
                if account is None:
                    continue
                last = conn.execute("SELECT MAX(date) FROM bank_transactions WHERE account_id = ?",
                                       (account["id"],)).fetchone()[0]
                from_date = last or (today - timedelta(days=DEFAULT_BACK_DAYS)).isoformat()
                raw = eb.transactions(link["account_uid"], from_date)
                rules = [r for r in (enablebanking.to_rule(tx, account["iban"]) for tx in raw) if r]
                new = base.add_hashes(_from(rules, last))
                saved, _ = bank_transactions.save(conn, account["id"], new)
                report["added"] += saved

                balance = enablebanking.chosen_balance(eb.balances(link["account_uid"]), today.isoformat(), raw)
                if balance:
                    accounts.set_balance(conn, account["id"], balance[0], balance[1], source="sync")
                    report["balances"] += 1
                # A balance fetched earlier that counted payments that were still pending then
                # and are booked now: correct it.
                accounts.restore_pending(conn, account["id"])
                report["accounts"] += 1
            conn.execute("UPDATE bank_consents SET last_fetched = ?, error = NULL WHERE id = ?",
                         (_now().isoformat(), t["id"]))
        except enablebanking.ErrorNote as e:
            conn.execute("UPDATE bank_consents SET error = ? WHERE id = ?", (str(e)[:500], t["id"]))
            report["errors"].append(f"{t['bank']}: {e}")
    conn.commit()

    categorization.seed(conn)
    categorization.relabel(conn)
    return report


# ---------------------------------------------------------------------------
# Cleaning up
# ---------------------------------------------------------------------------

def delete_consent(conn: sqlite3.Connection, consent_id: int, http=None) -> bool:
    """Revokes the consent at the bank and forgets it. Accounts and transactions
    stay: they are yours, not the connection's.
    """
    row = conn.execute("SELECT * FROM bank_consents WHERE id = ?", (consent_id,)).fetchone()
    if not row:
        return False
    session_id = _session_id(row["session_id"])
    if session_id:
        try:
            client(conn, http).stop(session_id)
        except (enablebanking.ErrorNote, NotConfigured):
            pass    # already expired or revoked: local cleanup goes ahead
    conn.execute("DELETE FROM bank_consent_accounts WHERE consent_id = ?", (consent_id,))
    conn.execute("DELETE FROM bank_consents WHERE id = ?", (consent_id,))
    conn.commit()
    return True


def delete_everything(conn: sqlite3.Connection, http=None) -> None:
    for row in conn.execute("SELECT id FROM bank_consents").fetchall():
        delete_consent(conn, row["id"], http)
    conn.execute("DELETE FROM bank_connections WHERE provider = ?", (enablebanking.PROVIDER,))
    conn.commit()
