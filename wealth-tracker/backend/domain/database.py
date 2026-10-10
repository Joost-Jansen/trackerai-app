"""
database.py — Stores and retrieves all portfolio data using SQLite

Every function that touches the database takes an explicit, already-open
`conn: sqlite3.Connection` as its first argument — there is no ambient
"current user" state. This is deliberate: the previous design bound the
current user to `threading.local()`, which was safe under Streamlit's
one-thread-per-session model but is NOT safe under an async server (FastAPI/
uvicorn) where OS threads are pooled and reused across different users'
requests. Requiring an explicit connection means a call site that forgets to
scope itself to a user fails immediately with a TypeError, instead of
silently leaking one user's data into another user's response.

Callers open a connection for "the current request's user" via `connect()`
(or the `user_db()` context manager below), typically once per request/
script-run, and pass it down through whatever functions need it.
"""

import json
import math
import os
import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from domain import db, legacy_names


# The repo root: ./data next to the code by default, as the Pi's docker-compose
# bind-mounts it (backend/domain/database.py -> three levels up).
_HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _safe_user(user: str) -> str:
    """Validate a username so it is safe to use as a folder name (no traversal)."""
    if not isinstance(user, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", user):
        raise ValueError(f"Invalid username for storage: {user!r}")
    return user


def data_root() -> str:
    """The folder holding every user's data plus app-level files (audit log).

    DATA_DIR points it elsewhere. On a host without a bind mount (Railway) that
    is the volume; without the variable it stays ./data next to the code, as on
    the Pi and locally.
    """
    return os.environ.get("DATA_DIR") or os.path.join(_HERE, "data")


def user_data_dir(username: str) -> str:
    """The root folder for one user's private data (DB + uploads)."""
    return os.path.join(data_root(), "users", _safe_user(username))


def db_path_for_user(username: str) -> str:
    return os.path.join(user_data_dir(username), "portfolio.db")


def user_upload_dir(username: str) -> str:
    """The given user's private uploads folder (created on demand)."""
    d = os.path.join(user_data_dir(username), "uploads")
    os.makedirs(d, exist_ok=True)
    return d


def has_data(username: str) -> bool:
    """Does this user have a database at all: the SQLite file, or with WEALTH_DATABASE_URL their schema."""
    path = db_path_for_user(username)  # validates the username
    if db.on_postgres():
        conn = db.open_existing(username)
        if conn is None:
            return False
        conn.close()
        return True
    return os.path.exists(path)


def db_size_bytes(username: str) -> int:
    """The size on disk of one user's database (0 without one), what the admin panels show as their footprint."""
    path = db_path_for_user(username)  # validates the username
    if db.on_postgres():
        return db.schema_bytes(username)
    return os.path.getsize(path) if os.path.exists(path) else 0


def user_stats(username: str) -> dict:
    """Cheap, read-only summary of one user's data for the admin panel.

    Opens the DB read-only (`mode=ro`) so counting never creates a database for
    a user who has uploaded nothing, and never mutates one that exists.
    """
    path = db_path_for_user(username)  # validates the username
    if db.on_postgres():
        conn = db.open_existing(username)
        if conn is None:
            return {"transaction_count": 0, "db_size_bytes": 0, "has_data": False}
    elif not os.path.exists(path):
        return {"transaction_count": 0, "db_size_bytes": 0, "has_data": False}
    else:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    except (sqlite3.Error, *db.OperationalError):
        count = 0  # brand-new DB before init_db(), or an older schema
    finally:
        conn.close()
    return {"transaction_count": count, "db_size_bytes": db_size_bytes(username), "has_data": True}


def bank_activity(username: str, since: str) -> dict | None:
    """Read-only, for the trackerai.nl admin page: one user's bank transactions in total, the newest booking date,
    and the count per booking date from `since` (ISO date) on. None when the user has no database or no
    bank_transactions table yet; like user_stats, never creates or changes a database."""
    path = db_path_for_user(username)  # validates the username
    if db.on_postgres():
        conn = db.open_existing(username)
        if conn is None:
            return None
    elif not os.path.exists(path):
        return None
    else:
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        except sqlite3.Error:
            return None
    try:
        count, last = conn.execute("SELECT COUNT(*), MAX(date) FROM bank_transactions").fetchone()
        per_day = dict(conn.execute(
            "SELECT substr(date, 1, 10), COUNT(*) FROM bank_transactions WHERE date >= ? GROUP BY substr(date, 1, 10)",
            (since,),
        ).fetchall())
    except (sqlite3.Error, *db.OperationalError):
        return None  # no bank_transactions table (nothing imported yet, an older schema)
    finally:
        conn.close()
    return {"count": count, "last": last[:10] if last else None, "per_day": per_day}


def delete_user_data(username: str) -> None:
    """Delete a user's entire private folder (DB + uploads). Irreversible.

    Used when an admin removes an account so no orphaned data lingers on disk.
    `user_data_dir` validates the username, so this can never escape data/users/.
    """
    if db.on_postgres():
        db.drop_schema(username)
    root = user_data_dir(username)
    if os.path.isdir(root):
        shutil.rmtree(root)


# How long a write waits for another writer before "database is locked" (see connect).
BUSY_TIMEOUT_MS = 30_000


def connect(username: str, *, same_thread_only: bool = True) -> sqlite3.Connection:
    """Opens a connection to one user's database, creating its folder if needed.

    The caller owns the connection's lifecycle (close it when done, or use
    the `user_db()` context manager below).

    `same_thread_only=False` lifts sqlite3's check that a connection is only
    ever touched by the thread that created it. Pass it only when the caller
    guarantees the connection is still used by one thread *at a time* — it
    disables a real safety net, it does not make a connection concurrency-safe.

    Both current callers need it, for the same underlying reason: a connection
    outlives the thread that opened it.
      - backend/app/deps.py — FastAPI runs a sync dependency's setup and its
        post-yield teardown as separate threadpool tasks.
      - app.py — Streamlit runs every rerun on a new thread, but the connection
        is cached in st.session_state across them.
    Neither ever has two threads on one connection at once: FastAPI gives each
    request its own, and Streamlit runs one script at a time per session.

    The default stays True so that a *new* caller has to think about this rather
    than inherit an exemption it may not be entitled to.
    """
    root = user_data_dir(username)
    os.makedirs(root, exist_ok=True)
    os.makedirs(os.path.join(root, "uploads"), exist_ok=True)
    # With WEALTH_DATABASE_URL the tables live in Postgres, in the user's own schema (domain/db.py); uploads stay
    # in the folder above.
    if db.on_postgres():
        return db.connect_postgres(username)
    conn = sqlite3.connect(db_path_for_user(username), check_same_thread=same_thread_only)
    conn.row_factory = sqlite3.Row
    # The price loop and a request sometimes write to the same database at once.
    # With WAL reading no longer blocks writing, and the busy timeout lets a writer
    # wait instead of failing straight away with "database is locked". 30 s, not
    # 5: every request writes on connect (init_db) and the price loop writes once
    # per ISIN, so after a login a dozen requests and the loop queue for the one
    # write lock, and on Railway's volume 5 s was not always enough (pages failed
    # with "database is locked" in production). health-tracker waits 30 s too.
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def user_db(username: str):
    """`with database.user_db(username) as conn:` — opens and always closes."""
    conn = connect(username)
    try:
        yield conn
    finally:
        conn.close()


def _migrate_if_needed(conn: sqlite3.Connection, cursor: sqlite3.Cursor) -> None:
    """
    Rebuilds the transactions table when an older schema is detected.

    Older schemas enforced uniqueness at the database level:
      v1: order_ref TEXT UNIQUE
      v2: UNIQUE(order_ref, quantity, price)
    Both constraints are gone in the current schema: two genuine partial fills
    of one order can be identical in all of those columns, so a database-level
    constraint would silently reject real executions.  Duplicate detection is
    count-based in save_transactions() instead.
    """
    cursor.execute("PRAGMA index_list(transactions)")
    indexes = cursor.fetchall()
    has_unique_constraint = any(idx["origin"] == "u" and idx["unique"] for idx in indexes)
    if not has_unique_constraint:
        return

    cursor.execute("ALTER TABLE transactions RENAME TO transactions_old")
    cursor.execute("""
        CREATE TABLE transactions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            order_ref        TEXT,
            date             TEXT    NOT NULL,
            time             TEXT,
            name             TEXT    NOT NULL,
            isin             TEXT    NOT NULL,
            exchange         TEXT,
            execution_venue  TEXT,
            transaction_type TEXT    NOT NULL,
            quantity         REAL    NOT NULL,
            price            REAL,
            local_value      REAL,
            value_eur        REAL,
            exchange_rate    REAL,
            autofx_cost      REAL,
            transaction_fee  REAL,
            total_eur        REAL
        )
    """)
    cursor.execute("""
        INSERT INTO transactions
            (order_ref, date, time, name, isin, exchange,
             execution_venue, transaction_type, quantity, price,
             local_value, value_eur, exchange_rate, autofx_cost,
             transaction_fee, total_eur)
        SELECT
            order_ref, date, time, name, isin, exchange,
            execution_venue, transaction_type, quantity, price,
            local_value, value_eur, exchange_rate, autofx_cost,
            transaction_fee, total_eur
        FROM transactions_old
    """)
    cursor.execute("DROP TABLE transactions_old")
    conn.commit()


def _migrate_dividends_if_needed(conn: sqlite3.Connection, cursor: sqlite3.Cursor) -> None:
    """Drops the dividends table's UNIQUE constraint, for the reason the
    transactions table lost its own (see _migrate_if_needed).

    UNIQUE(date, isin, amount_original, currency_original) was there to make
    re-uploading overlapping exports a no-op, and it does that — but it cannot
    tell a second upload of one payment from a second payment of the same size
    on the same day. The latter was rejected as a duplicate, and every dividend
    total came out short by exactly that amount while the upload reported it as
    a duplicate skipped, which reads as things having gone right.

    save_dividends() is count-based now, exactly like save_transactions(): a
    file contributes only the copies it has beyond what is already stored, so
    re-uploads stay a no-op and a genuine second payment survives.
    """
    def still_constrained() -> bool:
        cursor.execute("PRAGMA index_list(dividends)")
        return any(idx["origin"] == "u" and idx["unique"] for idx in cursor.fetchall())

    if not still_constrained():
        return

    # One writer at a time. init_db runs on *every* request (deps.get_db), and
    # the dashboard opens four connections at once, so on the first page load
    # after this ships two of them would otherwise reach the rename together —
    # one renaming a table the other had already renamed. BEGIN IMMEDIATE takes
    # the write lock up front and the check is made again inside it.
    conn.commit()   # close any implicit transaction before beginning one
    try:
        cursor.execute("BEGIN IMMEDIATE")
    except db.OperationalError:
        return      # another connection is already doing this; it will finish

    try:
        if not still_constrained():
            conn.rollback()
            return
        cursor.execute("ALTER TABLE dividends RENAME TO dividends_old")
        cursor.execute("""
            CREATE TABLE dividends (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                date              TEXT    NOT NULL,
                isin              TEXT    NOT NULL,
                name              TEXT,
                currency_original TEXT,
                amount_original   REAL,
                gross_eur         REAL,
                tax_eur           REAL,
                net_eur           REAL    NOT NULL
            )
        """)
        cursor.execute("""
            INSERT INTO dividends
                (date, isin, name, currency_original, amount_original,
                 gross_eur, tax_eur, net_eur)
            SELECT
                date, isin, name, currency_original, amount_original,
                gross_eur, tax_eur, net_eur
            FROM dividends_old
        """)
        cursor.execute("DROP TABLE dividends_old")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db(conn: sqlite3.Connection) -> None:
    legacy_names.migrate(conn)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            order_ref        TEXT,
            date             TEXT    NOT NULL,
            time             TEXT,
            name             TEXT    NOT NULL,
            isin             TEXT    NOT NULL,
            exchange         TEXT,
            execution_venue  TEXT,
            transaction_type TEXT    NOT NULL,
            quantity         REAL    NOT NULL,
            price            REAL,
            local_value      REAL,
            value_eur        REAL,
            exchange_rate    REAL,
            autofx_cost      REAL,
            transaction_fee  REAL,
            total_eur        REAL
        )
    """)

    _migrate_if_needed(conn, cursor)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            isin           TEXT PRIMARY KEY,
            name           TEXT,
            ticker         TEXT,
            price          REAL,
            currency       TEXT,
            fetched_at     TEXT,
            previous_close REAL
        )
    """)

    # Migration: add previous_close if the table predates it (additive, so the
    # live Streamlit app reading the same file is unaffected — it selects by
    # name and never sees the extra column).
    cursor.execute("PRAGMA table_info(prices)")
    price_cols = [row["name"] for row in cursor.fetchall()]
    if "previous_close" not in price_cols:
        cursor.execute("ALTER TABLE prices ADD COLUMN previous_close REAL")
    # The currency the *ticker* quotes in, which is not always `currency`: a
    # listing outside the euro area (TSM, MCD) is stored converted, so `price`
    # and `currency` say EUR while the ticker's own history is in dollars. The
    # charts download that history and need to know. NULL on rows from before
    # this column — read as `currency`, and the next price refresh fills it.
    if "quote_currency" not in price_cols:
        cursor.execute("ALTER TABLE prices ADD COLUMN quote_currency TEXT")
    # EUR per unit of quote_currency, the rate `price` was converted at. What a
    # position's page divides by to print the price in the listing's own
    # currency, beside a chart in that currency. NULL for a EUR listing.
    if "quote_fx_rate" not in price_cols:
        cursor.execute("ALTER TABLE prices ADD COLUMN quote_fx_rate REAL")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dividends (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            date              TEXT    NOT NULL,
            isin              TEXT    NOT NULL,
            name              TEXT,
            currency_original TEXT,
            amount_original   REAL,
            gross_eur         REAL,
            tax_eur           REAL,
            net_eur           REAL    NOT NULL
        )
    """)

    _migrate_dividends_if_needed(conn, cursor)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS asset_categories (
            isin         TEXT PRIMARY KEY,
            category     TEXT NOT NULL DEFAULT 'Unclassified',
            broad_region TEXT NOT NULL DEFAULT 'Unclassified'
        )
    """)

    # Migration: add broad_region column if it doesn't exist yet
    cursor.execute("PRAGMA table_info(asset_categories)")
    cols = [row["name"] for row in cursor.fetchall()]
    if "broad_region" not in cols:
        cursor.execute("ALTER TABLE asset_categories ADD COLUMN broad_region TEXT NOT NULL DEFAULT 'Unclassified'")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # User-supplied ticker corrections: when automatic resolution picks the
    # wrong market listing for an ISIN, the user can pin the right Yahoo
    # ticker here (per their own database, no code change needed).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ticker_overrides (
            isin   TEXT PRIMARY KEY,
            ticker TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS etf_api_cache (
            ticker     TEXT PRIMARY KEY,
            payload    TEXT NOT NULL,      -- the issuer's holdings file, as JSON
            fetched_at TEXT NOT NULL       -- ISO timestamp
        )
    """)

    # Generic sibling of etf_api_cache, for anything else slow and remote —
    # see get_or_fetch(). Separate rather than a rename: etf_api_cache is in
    # every live user's database already, and renaming a table under the
    # running app buys nothing. Folding the two together is a tidy-up for
    # later, not a prerequisite for anything.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_cache (
            key        TEXT PRIMARY KEY,
            payload    TEXT NOT NULL,      -- JSON, whatever fetch_fn returned
            fetched_at TEXT NOT NULL       -- ISO timestamp
        )
    """)

    # One row per dashboard *session*, for the "since your last visit" strip.
    # A session is a run of page loads less than a gap apart (see
    # dashboard_service.record_visit); last_value is the portfolio value the
    # user last saw in it, so the next session can diff against what they
    # actually left with, not what they arrived to.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS visit_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at   TEXT NOT NULL,    -- ISO timestamp
            last_seen_at TEXT NOT NULL,    -- ISO timestamp
            last_value   REAL              -- NULL when prices were unavailable
        )
    """)

    # Publication dates a company has already reported on, kept because the
    # source forgets them. Yahoo's calendar carries exactly one earnings date
    # per ticker — the next one — so the day a company reports, its date starts
    # sliding out of view and the Calendar tab would show an empty past. This
    # table is the memory the feed lacks: every sweep writes down what it saw,
    # and a date stays on the calendar once it has been seen once.
    #
    # `confirmed` is 0 when Yahoo gave a *window* rather than a day (it returns
    # two dates when the company has not pinned the date down yet). Those never
    # get a day cell — see calendar_service — so the distinction has to survive
    # the round trip to storage.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS earnings_dates (
            isin      TEXT NOT NULL,
            date      TEXT NOT NULL,      -- ISO date the company reports
            confirmed INTEGER NOT NULL,   -- 0 = one end of an estimated window
            seen_at   TEXT NOT NULL,      -- ISO timestamp of the sweep that saw it
            PRIMARY KEY (isin, date)
        )
    """)

    # The price of one exchange for one ISIN, for exchanges with a source of
    # their own (Tradegate, via app/services/tradegate_service.py). `prices`
    # stays the one Yahoo quote per ISIN; this is what lets a position on TDG
    # be valued at Tradegate's last trade while the same fund on EAM keeps its
    # Amsterdam price. Additive: a database without rows here prices exactly
    # as before.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS venue_prices (
            isin           TEXT NOT NULL,
            venue          TEXT NOT NULL,   -- DeGiro's beurs code, e.g. "TDG"
            price          REAL NOT NULL,   -- last trade, never bid/ask
            previous_close REAL,
            currency       TEXT NOT NULL,
            source         TEXT NOT NULL,   -- "tradegate"
            fetched_at     TEXT NOT NULL,   -- when it was fetched; not when it traded
            PRIMARY KEY (isin, venue)
        )
    """)

    # The API Ninjas integration is gone (its holdings tier was premium-only,
    # and the issuer files it was meant to supplement turned out to cover
    # everything). Any key a user once saved is dead weight — and it is a
    # secret, so leaving it in the database is worse than untidy.
    cursor.execute("DELETE FROM settings WHERE key = 'api_ninjas_key'")

    # -----------------------------------------------------------------------
    # Geldzaken: money that is not a securities position.
    #
    # Declared here with every other table so there is one place the schema
    # lives, but everything that reads or writes them is in rekeningen.py —
    # this module stays about the portfolio.
    # -----------------------------------------------------------------------

    # A current account, a savings account, cash in a drawer. `iban` is NULL
    # for cash, and SQLite's UNIQUE treats NULLs as distinct, so any number of
    # cash accounts coexist while a real IBAN can only be added once (importing
    # the same bank export twice must not create a second account).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            kind         TEXT    NOT NULL,              -- bank | contant | handmatig | broker
            provider     TEXT    NOT NULL,              -- ing | bunq | revolut | enablebanking | handmatig
            name          TEXT    NOT NULL,
            iban          TEXT,                          -- NULL for cash
            currency        TEXT    NOT NULL DEFAULT 'EUR',
            external_id     TEXT,                          -- the provider's own id, once there is one
            active        INTEGER NOT NULL DEFAULT 1,
            created_at TEXT    NOT NULL,
            UNIQUE(iban)
        )
    """)

    # Balance readings, not a continuous series: one row per day you actually
    # looked. accounts.balance_on carries the last reading forward, because a
    # day without a measurement is a day the balance did not change as far as
    # anyone knows — falling back to zero there would drop the account out of
    # the net-worth curve on every gap.
    #
    # The REFERENCES clause documents the relationship but does not enforce it:
    # connect() leaves PRAGMA foreign_keys at its default (off), so
    # accounts.delete_account deletes the children itself.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS account_balances (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            date       TEXT    NOT NULL,   -- ISO date (YYYY-MM-DD)
            balance       REAL    NOT NULL,
            source        TEXT    NOT NULL,   -- sync | handmatig
            UNIQUE(account_id, date)
        )
    """)

    # One row per bank transaction, from a CSV export (see bank_providers/). The local
    # database is the archive, not a cache: a PSD2 connection only ever shows
    # ~90 days, so anything dropped here is gone for good.
    #
    # `dedup_hash` is what makes re-importing safe — bank exports overlap by
    # design. It is UNIQUE per user database, not globally: two housemates
    # paying the same rent are not duplicates of each other.
    #
    # Three columns for the category, the model from the old spreadsheet:
    # `category_auto` is what the rules concluded, `category_manual` is
    # what you decided, and the second always wins. Re-running the rules
    # therefore relabels history without ever touching a judgement call. Both
    # stay NULL until the rules engine lands.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bank_transactions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id         INTEGER NOT NULL REFERENCES accounts(id),
            date               TEXT    NOT NULL,   -- ISO date, the booking date
            interest_date          TEXT,               -- ISO date; bunq has one, ING does not
            amount              REAL    NOT NULL,   -- spending positive, income negative
            currency              TEXT    NOT NULL DEFAULT 'EUR',
            name                TEXT    NOT NULL,
            counterparty_iban    TEXT,
            description        TEXT    NOT NULL DEFAULT '',
            code                TEXT,               -- the bank's own code (ING: BA, GT, IC, …)
            kind               TEXT,               -- how the bank labels it
            category_auto      TEXT,
            category_manual TEXT,
            type                TEXT,               -- UITGAVE | INKOMSTEN | INTERN
            dedup_hash          TEXT    NOT NULL,
            raw                 TEXT,               -- the original row, as JSON
            source                TEXT    NOT NULL DEFAULT 'import',  -- import | handmatig
            UNIQUE(dedup_hash)
        )
    """)
    # Databases from before manual entry have no `source`. Everything in them came
    # from an import, which is exactly what the default says. A second
    # connection may have added it between the check and the ALTER.
    cursor.execute("PRAGMA table_info(bank_transactions)")
    columns = {column[1] for column in cursor.fetchall()}
    # `category_source`: where category_auto came from — 'rule', 'learned' (from
    # your own labels for the same counterparty) or 'ai' (a suggestion from
    # Claude). So it stays visible what a rule knew and what was a guess.
    for column, definition in (("source", "TEXT NOT NULL DEFAULT 'import'"), ("category_source", "TEXT")):
        if column in columns:
            continue
        try:
            cursor.execute(f"ALTER TABLE bank_transactions ADD COLUMN {column} {definition}")
        except db.OperationalError as e:
            if "duplicate column" not in str(e):
                raise
    # What Claude suggested, per transaction and asked only once. A suggestion is
    # not a label: relabel() only takes it over when the rules did not know and
    # Claude was certain enough. See ai_labelling.py.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_suggestions (
            transaction_id INTEGER PRIMARY KEY REFERENCES bank_transactions(id) ON DELETE CASCADE,
            category     TEXT NOT NULL,
            confidence     REAL NOT NULL,
            model         TEXT,
            created_at    TEXT NOT NULL
        )
    """)
    # "Check everything": what Claude thinks of what the rules already labelled.
    # Never taken over by itself; `decision` is what you made of it (suggestion,
    # original or otherwise), NULL as long as you have not chosen. `current` is the
    # category at the time.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ai_checks (
            transaction_id INTEGER PRIMARY KEY REFERENCES bank_transactions(id) ON DELETE CASCADE,
            category     TEXT NOT NULL,
            confidence     REAL NOT NULL,
            current        TEXT NOT NULL,
            decision       TEXT,
            model         TEXT,
            created_at    TEXT NOT NULL
        )
    """)
    # Claude's short reason for a suggestion ("well-known clothing chain"); added
    # later, so also on existing databases.
    for table in ("ai_suggestions", "ai_checks"):
        cursor.execute(f"PRAGMA table_info({table})")
        if "reason" not in {column[1] for column in cursor.fetchall()}:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN reason TEXT")
            except db.OperationalError as e:
                if "duplicate column" not in str(e):
                    raise
    # Rules Claude suggested for a counterparty (`key`, see
    # categorization.learn_keys). Once per counterparty: `status` is NULL until you
    # choose, then accepted or rejected; 'unusable' when no pattern passed the test.
    # See ai_labelling.py.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rule_suggestions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            key    TEXT NOT NULL UNIQUE,
            pattern    TEXT,
            category  TEXT NOT NULL,
            status     TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_bank_transactions_date
        ON bank_transactions (date)
    """)

    # The taxonomy. `type` is what makes a total mean anything: INTERN is money
    # moved between your own accounts, and it counts in neither spending nor
    # income. Leaving that out makes a transfer to your own savings
    # account count as if it had been spent.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            group_name    TEXT    NOT NULL,
            name     TEXT    NOT NULL,
            type     TEXT    NOT NULL,   -- UITGAVE | INKOMSTEN | INTERN
            sort_order INTEGER NOT NULL DEFAULT 0,
            UNIQUE(name)
        )
    """)

    # Money moving in or out of an account that has no bank transactions of its
    # own — the cash account at a broker, read from its account statement
    # (degiro_cash.py). Not spending, so not in bank_transactions; kept only so a
    # bank transfer can be matched to its other side (categorisatie.herlabel):
    # the same amount leaving the broker and arriving at the bank is one
    # transfer between your own accounts, whatever name the bank prints on it.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS account_entries (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id  INTEGER NOT NULL,
            date        TEXT    NOT NULL,
            amount       REAL    NOT NULL,   -- positive = into this account
            description TEXT,
            key      TEXT    NOT NULL UNIQUE
        )
    """)

    # A direct bank connection (bank_link.py). The user's own Enable Banking
    # app: its id and private key, the key encrypted (secret_box.py) and never
    # returned by any endpoint. Then each consent given at a bank, and which of
    # that bank's accounts is which rekening here.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bank_connections (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            provider     TEXT NOT NULL UNIQUE,   -- enablebanking
            app_id        TEXT NOT NULL,
            key       TEXT NOT NULL,          -- encrypted private key
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bank_consents (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            bank             TEXT NOT NULL,
            country             TEXT NOT NULL,
            state            TEXT UNIQUE,         -- only while waiting for the bank
            redirect_url     TEXT,
            session_id        TEXT,
            valid_until       TEXT,
            status           TEXT NOT NULL,       -- wacht | actief | verlopen | fout
            error             TEXT,
            created_at    TEXT NOT NULL,
            last_fetched TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bank_consent_accounts (
            consent_id INTEGER NOT NULL,
            account_uid    TEXT    NOT NULL,
            account_id    INTEGER NOT NULL,
            PRIMARY KEY (consent_id, account_uid)
        )
    """)

    # What the user means to spend per category group per month, next to what
    # it became (budget.py). Per group, like the old sheet's monthly overview:
    # per category is too fine to plan with. No row means no budget.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            group_name  TEXT PRIMARY KEY,   -- categorieen.groep
            amount REAL NOT NULL       -- per month, positive
        )
    """)

    # Whether a counterparty is a fixed monthly cost, when the user says so
    # (fixed_costs.py). Overrides the pattern both ways; no row means the
    # pattern decides. Keyed on the name without digits, like the pattern.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fixed_cost_choices (
            key TEXT PRIMARY KEY,
            is_fixed    INTEGER NOT NULL      -- 1 = wel vaste last, 0 = niet
        )
    """)

    # Interest and mandatory repayment of a debt, applied at every month
    # boundary after the latest balance (schuldschema.py). Computed, never
    # stored as balances, so a new rate or month boundary applies everywhere.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS debt_schedules (
            account_id INTEGER PRIMARY KEY REFERENCES accounts(id),
            interest       REAL NOT NULL DEFAULT 0,   -- percent per year
            repayment   REAL NOT NULL DEFAULT 0,   -- per month, positive
            from_date       TEXT NOT NULL              -- ISO date
        )
    """)

    # The labelling rules, editable per user. Lowest `prio` wins and the first
    # match stops the search, so the ordering is the logic — INTERN sits at 10
    # precisely so a transfer to savings can never be captured by a spending
    # rule further down. See categorisatie.py for the fields.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rules (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            priority      INTEGER NOT NULL,
            field      TEXT    NOT NULL,          -- N | T | A | P
            pattern   TEXT    NOT NULL,          -- regex
            direction  TEXT    NOT NULL DEFAULT '',  -- '' both | D debit | C credit
            category TEXT    NOT NULL,          -- categorieen.naam
            active    INTEGER NOT NULL DEFAULT 1
        )
    """)

    # A transaction's type — EXPENSE, INCOME or INTERNAL, the thing every total
    # sums on — is *derived* here, never stored. It used to be a column that
    # categorisatie.herlabel filled in from the automatic category, and that
    # made it a cache with three ways to go stale: correcting a category by
    # hand left the old type behind (a "groceries" line re-labelled as a
    # transfer to savings still counted as spending), changing a category's
    # type in the taxonomy moved nothing, and every change to the typing rule
    # itself needed a full relabel to reach existing rows. Computed at read
    # time there is nothing to invalidate.
    #
    # The rule: the type of the category you *see* (manual before automatic).
    # For 'Onbekend' — categorisatie.ONBEKEND — and for a category that no
    # longer exists, the sign decides instead: we don't know what it was, but
    # we know which way the money went (spending positive, income negative).
    # Unlabelled rows have no type and count nowhere.
    #
    # The `type` column on bank_transactions is left in place for databases that
    # already have it, but nothing writes it any more. Dropped and recreated on
    # every init so a changed definition reaches existing databases; created
    # last because it reads `categorieen`.
    cursor.execute("DROP VIEW IF EXISTS bank_transactions_typed")
    cursor.execute("""
        CREATE VIEW bank_transactions_typed AS
        SELECT t.*,
               COALESCE(t.category_manual, t.category_auto) AS category_effective,
               c.group_name                                           AS group_name,
               CASE
                   WHEN COALESCE(t.category_manual, t.category_auto) IS NULL THEN NULL
                   WHEN c.type IS NULL
                     OR COALESCE(t.category_manual, t.category_auto) = 'Onbekend'
                       THEN CASE WHEN t.amount < 0 THEN 'INCOME' ELSE 'EXPENSE' END
                   ELSE c.type
               END                                               AS type_effective
        FROM bank_transactions t
        LEFT JOIN categories c
               ON c.name = COALESCE(t.category_manual, t.category_auto)
    """)

    conn.commit()


# ---------------------------------------------------------------------------
# Asset categories (rebalancing)
# ---------------------------------------------------------------------------

def load_asset_categories(conn: sqlite3.Connection) -> dict[str, str]:
    """Returns {isin: category} for all saved categorisations."""
    cursor = conn.cursor()
    cursor.execute("SELECT isin, category FROM asset_categories")
    return {row["isin"]: row["category"] for row in cursor.fetchall()}


def load_broad_regions(conn: sqlite3.Connection) -> dict[str, str]:
    """Returns {isin: broad_region} for all Broad ETF positions."""
    cursor = conn.cursor()
    cursor.execute("SELECT isin, broad_region FROM asset_categories")
    return {row["isin"]: row["broad_region"] for row in cursor.fetchall()}


#: Spellings that mean "this is a bond holding". The Rebalancing tab wrote
#: "Bond" until 5f136d3 (2026-07-16) rebuilt it around "Stocks"/"Bonds", so a
#: database can hold either — and the rows are the user's own classifications,
#: not something to migrate away under them.
BOND_CATEGORIES = frozenset({"Bond", "Bonds"})


def bond_isins(conn: sqlite3.Connection) -> set[str]:
    """The ISINs the user has classified as bonds, whichever spelling they used.

    Exists because reading the categories and comparing to one literal is what
    went wrong: the Benchmarks tab kept matching "Bond" after the Rebalancing
    tab started saving "Bonds", so its "Exclude bond positions" checkbox — on by
    default — silently excluded nothing, and every benchmark line since has
    included bonds it claimed to leave out. One reader, so the two cannot drift
    apart again.
    """
    return {isin for isin, cat in load_asset_categories(conn).items() if cat in BOND_CATEGORIES}


def save_asset_category(conn: sqlite3.Connection, isin: str, category: str) -> None:
    cursor = conn.cursor()
    # Upsert — must not use INSERT OR REPLACE here: that deletes the existing
    # row and would reset broad_region back to its default.
    cursor.execute(
        """
        INSERT INTO asset_categories (isin, category) VALUES (?, ?)
        ON CONFLICT(isin) DO UPDATE SET category = excluded.category
        """,
        (isin, category),
    )
    conn.commit()


def save_broad_region(conn: sqlite3.Connection, isin: str, region: str) -> None:
    cursor = conn.cursor()
    # Upsert: preserve existing category if row already exists
    cursor.execute(
        """
        INSERT INTO asset_categories (isin, category, broad_region)
        VALUES (?, COALESCE((SELECT category FROM asset_categories WHERE isin = ?), 'Unclassified'), ?)
        ON CONFLICT(isin) DO UPDATE SET broad_region = excluded.broad_region
        """,
        (isin, isin, region),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# User ticker overrides (manual price-listing corrections)
# ---------------------------------------------------------------------------

def load_ticker_overrides(conn: sqlite3.Connection) -> dict[str, str]:
    """Returns {isin: yahoo_ticker} for every manual correction."""
    cursor = conn.cursor()
    cursor.execute("SELECT isin, ticker FROM ticker_overrides")
    return {row["isin"]: row["ticker"] for row in cursor.fetchall()}


def save_ticker_override(conn: sqlite3.Connection, isin: str, ticker: str) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO ticker_overrides (isin, ticker) VALUES (?, ?)
        ON CONFLICT(isin) DO UPDATE SET ticker = excluded.ticker
        """,
        (isin, ticker),
    )
    conn.commit()


def delete_ticker_override(conn: sqlite3.Connection, isin: str) -> None:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ticker_overrides WHERE isin = ?", (isin,))
    conn.commit()


def load_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    return row["value"] if row else default


def save_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# ETF holdings cache
#
# Named etf_api_cache because API Ninjas filled it first; that source is gone
# and issuer_holdings.py is the only writer left. Renaming the table would cost
# a migration for a comment's worth of clarity, so the name stays and this
# sentence carries the history.
# ---------------------------------------------------------------------------

def load_etf_api_cache(conn: sqlite3.Connection, ticker: str, max_age_days: int = 7) -> str | None:
    """Returns the cached JSON payload for a ticker, or None if absent/stale."""
    from datetime import timedelta
    cursor = conn.cursor()
    cursor.execute(
        "SELECT payload, fetched_at FROM etf_api_cache WHERE ticker = ?",
        (ticker,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
    except ValueError:
        return None
    if datetime.now() - fetched > timedelta(days=max_age_days):
        return None
    return row["payload"]


def save_etf_api_cache(conn: sqlite3.Connection, ticker: str, payload: str) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO etf_api_cache (ticker, payload, fetched_at) VALUES (?, ?, ?)",
        (ticker, payload, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


def clear_etf_api_cache(conn: sqlite3.Connection) -> None:
    """Drops all cached ETF API responses (forces fresh fetch on next load)."""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM etf_api_cache")
    conn.commit()


# ---------------------------------------------------------------------------
# Generic remote-call cache
# ---------------------------------------------------------------------------

def get_or_fetch(conn: sqlite3.Connection, key: str, ttl_seconds: int, fetch_fn):
    """Returns the cached value for *key*, or calls *fetch_fn()* and stores it.

    The Streamlit app leans on @st.cache_data for this; the backend has no
    equivalent, and its callers are the slow ones — a benchmark fetch is three
    yfinance downloads plus an FX series. Same shape as the etf_api_cache
    pattern above, generalised: any key, any TTL, any JSON-serialisable value.

    *fetch_fn* must return something json.dumps can take, and gets what
    json.loads gives back — pandas objects are the caller's to serialise, since
    a cache has no business knowing about them.

    A failed fetch is not cached: fetch_fn's exception propagates, and callers
    that return {} on failure (charts.fetch_benchmark_prices does) would
    otherwise pin an empty result for the whole TTL after one bad network
    moment.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT payload, fetched_at FROM api_cache WHERE key = ?", (key,))
    row = cursor.fetchone()
    if row:
        try:
            fetched = datetime.fromisoformat(row["fetched_at"])
        except ValueError:
            fetched = None
        if fetched and (datetime.now() - fetched).total_seconds() <= ttl_seconds:
            try:
                return json.loads(row["payload"])
            except json.JSONDecodeError:
                pass  # corrupt row: fall through and re-fetch over it

    value = fetch_fn()
    cursor.execute(
        "INSERT OR REPLACE INTO api_cache (key, payload, fetched_at) VALUES (?, ?, ?)",
        (key, json.dumps(value), datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return value


# ---------------------------------------------------------------------------
# Earnings dates the calendar has seen
# ---------------------------------------------------------------------------

def record_earnings_dates(conn: sqlite3.Connection, rows: list[dict]) -> None:
    """Remembers [{isin, date, confirmed}] — see the table's comment in init_db.

    An already-known (isin, date) keeps its original `confirmed` unless the
    sweep now says it is confirmed: a date is only ever promoted from window to
    day, never demoted. Yahoo widens back to a range now and then on a date it
    had already pinned, and the calendar should not lose a day cell over that.
    """
    if not rows:
        return
    seen_at = datetime.now().isoformat(timespec="seconds")
    cursor = conn.cursor()
    cursor.executemany(
        """
        INSERT INTO earnings_dates (isin, date, confirmed, seen_at)
        VALUES (:isin, :date, :confirmed, :seen_at)
        ON CONFLICT(isin, date) DO UPDATE SET
            -- the larger of the two, in words SQLite and Postgres both know (two-argument MAX is SQLite only)
            confirmed = CASE WHEN excluded.confirmed > earnings_dates.confirmed
                             THEN excluded.confirmed ELSE earnings_dates.confirmed END,
            seen_at   = excluded.seen_at
        """,
        [
            {
                "isin": r["isin"],
                "date": r["date"][:10],
                "confirmed": 1 if r.get("confirmed") else 0,
                "seen_at": seen_at,
            }
            for r in rows
            if r.get("isin") and r.get("date")
        ],
    )
    conn.commit()


def load_earnings_dates(conn: sqlite3.Connection, since: str | None = None) -> list[dict]:
    """[{isin, date, confirmed}] ascending, optionally from ISO date *since* on."""
    cursor = conn.cursor()
    if since:
        cursor.execute(
            "SELECT isin, date, confirmed FROM earnings_dates WHERE date >= ? ORDER BY date, isin",
            (since[:10],),
        )
    else:
        cursor.execute("SELECT isin, date, confirmed FROM earnings_dates ORDER BY date, isin")
    return [
        {"isin": r["isin"], "date": r["date"], "confirmed": bool(r["confirmed"])}
        for r in cursor.fetchall()
    ]


def clear_api_cache(conn: sqlite3.Connection, key_prefix: str | None = None) -> None:
    """Drops cached entries, all of them or just one prefix's."""
    cursor = conn.cursor()
    if key_prefix is None:
        cursor.execute("DELETE FROM api_cache")
    else:
        cursor.execute("DELETE FROM api_cache WHERE key LIKE ?", (f"{key_prefix}%",))
    conn.commit()


def save_transactions(conn: sqlite3.Connection, transactions: list[dict]) -> tuple[int, int]:
    """
    Inserts transactions with count-based duplicate detection.
    Returns (saved, skipped).

    DeGiro exports cover whole days, so a file that includes a given day
    contains *all* fills of that day.  For each execution key we therefore
    insert only the copies the file has beyond what the database already
    holds: re-uploading overlapping exports is a no-op, while two genuinely
    identical fills (same order, minute, size and price) are both kept —
    a plain UNIQUE constraint would silently reject the second one.

    Rows without a date are unusable downstream and are counted as skipped.
    """
    cursor = conn.cursor()

    saved = 0
    skipped = 0
    db_counts:    dict[tuple, int] = {}   # key → copies already in the DB
    batch_counts: dict[tuple, int] = {}   # key → copies seen in this batch

    for t in transactions:
        if not t.get("date"):
            skipped += 1
            continue

        # quantity is NOT NULL, and sqlite stores a float NaN as NULL — so a
        # single unusable row used to abort the INSERT and roll back the whole
        # file, losing every good row with it. The parser already guards this;
        # checking again here is what keeps any future source of a bad number
        # from turning one row into a failed import.
        qty = t.get("quantity")
        if qty is None or not math.isfinite(qty):
            skipped += 1
            continue

        key = (
            t.get("order_ref"), str(t.get("date")), t.get("time"),
            t.get("isin"), t.get("transaction_type"),
            t.get("quantity"), t.get("price"),
        )
        if key not in db_counts:
            # "IS" instead of "=" so NULL fields (order_ref, time, price)
            # still match their stored NULL counterparts.
            cursor.execute("""
                SELECT COUNT(*) FROM transactions
                WHERE order_ref IS ? AND date IS ? AND time IS ?
                  AND isin IS ? AND transaction_type IS ?
                  AND quantity IS ? AND price IS ?
            """, key)
            db_counts[key] = cursor.fetchone()[0]

        batch_counts[key] = batch_counts.get(key, 0) + 1
        if batch_counts[key] <= db_counts[key]:
            skipped += 1
            continue

        cursor.execute("""
            INSERT INTO transactions (
                order_ref, date, time, name, isin, exchange, execution_venue,
                transaction_type, quantity, price, local_value, value_eur,
                exchange_rate, autofx_cost, transaction_fee, total_eur
            ) VALUES (
                :order_ref, :date, :time, :name, :isin, :exchange, :execution_venue,
                :transaction_type, :quantity, :price, :local_value, :value_eur,
                :exchange_rate, :autofx_cost, :transaction_fee, :total_eur
            )
        """, {
            "order_ref":        t.get("order_ref"),
            "date":             str(t.get("date")),
            "time":             t.get("time"),
            "name":             t.get("name"),
            "isin":             t.get("isin"),
            "exchange":         t.get("exchange"),
            "execution_venue":  t.get("execution_venue"),
            "transaction_type": t.get("transaction_type"),
            "quantity":         t.get("quantity"),
            "price":            t.get("price"),
            "local_value":      t.get("local_value"),
            "value_eur":        t.get("value_eur"),
            "exchange_rate":    t.get("exchange_rate"),
            "autofx_cost":      t.get("autofx_cost"),
            "transaction_fee":  t.get("transaction_fee"),
            "total_eur":        t.get("total_eur"),
        })
        saved += 1

    conn.commit()
    return saved, skipped


def load_transactions(conn: sqlite3.Connection) -> list[dict]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM transactions ORDER BY date ASC, time ASC")
    return [dict(row) for row in cursor.fetchall()]


def load_home_exchanges(conn: sqlite3.Connection) -> dict[str, str]:
    """
    Returns {isin: DeGiro exchange code} — the venue each position is mostly
    traded on (most frequent; ties broken by most recent trade).  Used to pin
    price fetching to the same listing DeGiro displays.

    Only uppercase values count as a venue. An empty cell in a text column
    reaches str() as the literal "None" or "nan", and older imports stored
    those verbatim — where they were not merely useless but actively harmful,
    because the winner here is the *most frequent* value: one real "NSY" was
    outvoted by eight "None" rows, the venue then matched nothing in the venue
    table, and the position lost its authoritative ticker and was priced off
    whatever the name search turned up. Real DeGiro codes are uppercase and
    these artefacts are not, so the shape alone separates them.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT isin, exchange, COUNT(*) AS n, MAX(date) AS last
        FROM transactions
        WHERE exchange IS NOT NULL AND exchange != ''
          AND exchange = UPPER(exchange)
        GROUP BY isin, exchange
    """)
    best: dict[str, tuple] = {}   # isin → ((count, last_date), exchange)
    for row in cursor.fetchall():
        rank = (row["n"], row["last"])
        if row["isin"] not in best or rank > best[row["isin"]][0]:
            best[row["isin"]] = (rank, row["exchange"])
    return {isin: exch for isin, (_rank, exch) in best.items()}


def get_all_isins(conn: sqlite3.Connection) -> list[dict]:
    cursor = conn.cursor()
    # GROUP BY isin: the same fund can appear under two name spellings
    # (old vs new DeGiro export format) — one row per ISIN is enough.
    cursor.execute("""
        SELECT isin, MAX(name) AS name
        FROM transactions
        GROUP BY isin
        ORDER BY name ASC
    """)
    return [dict(row) for row in cursor.fetchall()]


def save_price(conn: sqlite3.Connection, isin: str, name: str, ticker: str, price: float, currency: str,
               previous_close: float | None = None, quote_currency: str | None = None,
               quote_fx_rate: float | None = None) -> None:
    # previous_close is keyword-optional so existing callers (app.py's baked
    # image, tests) keep working; None simply leaves the day change unknowable
    # for that ISIN until a refresh that does supply it. quote_currency is the
    # ticker's own currency (see init_db); omitted, it is `currency`.
    # quote_fx_rate is the rate a converted price was restated at.
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO prices
            (isin, name, ticker, price, currency, fetched_at, previous_close,
             quote_currency, quote_fx_rate)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (isin, name, ticker, price, currency, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
          previous_close, quote_currency or currency, quote_fx_rate))
    conn.commit()


def load_prices(conn: sqlite3.Connection) -> dict[str, dict]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM prices")
    return {row["isin"]: dict(row) for row in cursor.fetchall()}


def save_venue_price(conn: sqlite3.Connection, *, isin: str, venue: str, price: float,
                     previous_close: float | None, currency: str, source: str,
                     fetched_at: str) -> None:
    conn.execute("""
        INSERT OR REPLACE INTO venue_prices
            (isin, venue, price, previous_close, currency, source, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (isin, venue, price, previous_close, currency, source, fetched_at))
    conn.commit()


def load_venue_prices(conn: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    """{(isin, venue): row}. Empty, not an error, on a database init_db has not
    migrated yet — venue prices are an addition, never a requirement."""
    try:
        rows = conn.execute("SELECT * FROM venue_prices").fetchall()
    except db.OperationalError:
        return {}
    return {(row["isin"], row["venue"]): dict(row) for row in rows}


def save_dividends(conn: sqlite3.Connection, dividends: list[dict]) -> tuple[int, int]:
    """Insert new dividend records with count-based duplicate detection.
    Returns (saved, skipped).

    Same rule as save_transactions, and for the same reason: a mutations export
    covers whole days, so for each payment key this inserts only the copies the
    file has beyond what the database already holds. Re-uploading overlapping
    exports stays a no-op, while two genuine payments of the same size on the
    same day are both kept — the UNIQUE constraint that used to be on this table
    silently rejected the second one, leaving every dividend total short.
    """
    cursor = conn.cursor()
    saved = 0
    skipped = 0
    db_counts:    dict[tuple, int] = {}   # key → copies already in the DB
    batch_counts: dict[tuple, int] = {}   # key → copies seen in this batch

    for d in dividends:
        key = (
            d.get("date"), d.get("isin"),
            d.get("amount_original"), d.get("currency_original"),
        )
        if key not in db_counts:
            # "IS" instead of "=" so NULL fields still match their stored
            # NULL counterparts.
            cursor.execute("""
                SELECT COUNT(*) FROM dividends
                WHERE date IS ? AND isin IS ?
                  AND amount_original IS ? AND currency_original IS ?
            """, key)
            db_counts[key] = cursor.fetchone()[0]

        batch_counts[key] = batch_counts.get(key, 0) + 1
        if batch_counts[key] <= db_counts[key]:
            skipped += 1
            continue

        cursor.execute("""
            INSERT INTO dividends
                (date, isin, name, currency_original, amount_original,
                 gross_eur, tax_eur, net_eur)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            d.get("date"), d.get("isin"), d.get("name"),
            d.get("currency_original"), d.get("amount_original"),
            d.get("gross_eur"), d.get("tax_eur"), d.get("net_eur"),
        ))
        saved += 1

    conn.commit()
    return saved, skipped


def load_dividends(conn: sqlite3.Connection) -> list[dict]:
    """Return all dividend records ordered by date."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dividends ORDER BY date ASC")
    return [dict(row) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Visit snapshots ("since your last visit")
# ---------------------------------------------------------------------------

def load_recent_visits(conn: sqlite3.Connection, limit: int = 2) -> list[dict]:
    """Newest first. Row 0 is (or was) the current session, row 1 the previous."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM visit_snapshots ORDER BY last_seen_at DESC, id DESC LIMIT ?",
        (limit,),
    )
    return [dict(row) for row in cursor.fetchall()]


def insert_visit(conn: sqlite3.Connection, started_at: str, last_value: float | None) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO visit_snapshots (started_at, last_seen_at, last_value) VALUES (?, ?, ?)",
        (started_at, started_at, last_value),
    )
    # Unbounded growth buys nothing: only the last two sessions are ever read.
    cursor.execute("""
        DELETE FROM visit_snapshots WHERE id NOT IN (
            SELECT id FROM visit_snapshots ORDER BY last_seen_at DESC, id DESC LIMIT 20
        )
    """)
    conn.commit()


def touch_visit(conn: sqlite3.Connection, visit_id: int, last_seen_at: str, last_value: float | None) -> None:
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE visit_snapshots SET last_seen_at = ?, last_value = ? WHERE id = ?",
        (last_seen_at, last_value, visit_id),
    )
    conn.commit()


def load_dividends_by_isin(conn: sqlite3.Connection) -> dict[str, float]:
    """Return a mapping of isin → total net_eur dividends received."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT isin, SUM(net_eur) AS total
        FROM dividends
        GROUP BY isin
    """)
    return {row["isin"]: row["total"] for row in cursor.fetchall()}
