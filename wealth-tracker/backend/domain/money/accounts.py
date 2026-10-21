"""
accounts.py — accounts and their balances: all money that is not a security.

The portfolio knows what your holdings are worth. What is on your current
account, on your savings account, or in cash in a drawer, it does not know —
and without that last part "net worth" is just "investments". This is the
side that belongs with it.

Two concepts:

  account    A place where money is. A bank account has an IBAN, cash does
             not. Otherwise they are the same: both something with a balance.
  balance    A measurement on a day. Separate observations, not a continuous
             series: you look at your account now and then, and in between
             you do not know.

That "in between" is the most important rule here; see value_on. In short:

  * Before the first measurement an account counts as zero: that source did
    not exist for you yet.
  * Between two manual measurements runs a straight line. A manual
    measurement is a snapshot; what happened in between we do not know, and
    a straight line claims the least about it. A staircase that stands still
    for a month and then suddenly jumps claims precisely that nothing
    happened for a month.
  * If one of the two comes from an import (a statement), the balance stays
    flat until the next: such a balance only changes through a transaction,
    and that transaction is then in the statement itself.
  * After the last measurement it stays put.

As in database.py every function takes an explicit `conn` as its first
argument. There is no implicit "current user"; see the module docstring of
database.py for why it must stay that way.
"""

import bisect
import re
import sqlite3
from datetime import date, datetime, timedelta

from domain import db
from domain.i18n import tr
from domain.money import debt_schedule

# `debt` belongs here too: a debt is an account with a negative balance, and
# net worth is the sum of everything.
KINDS = ("bank", "cash", "manual", "broker", "debt")
# `degiro` is the cash balance at DeGiro, from the account statement (degiro_cash.py).
PROVIDERS = ("ing", "bunq", "revolut", "enablebanking", "degiro", "manual")
SOURCES = ("sync", "manual")

# Which fields of an existing account may be updated. `id` and `created_at`
# are left out on purpose, and so is `iban`: changing an IBAN turns an account
# into a different account, with all transactions of the previous one still
# attached.
UPDATABLE_FIELDS = ("kind", "provider", "name", "currency", "external_id", "active")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AccountExistsAlready(Exception):
    """There already is an account with this IBAN in this database."""


class AccountUnknown(Exception):
    """Referred to an account id that does not exist."""


# ---------------------------------------------------------------------------
# Normalising and checking
# ---------------------------------------------------------------------------


def normalise_iban(iban: str | None) -> str | None:
    """Spaces out, capitals in — or None when nothing is there.

    Banks write the same IBAN in three ways: with spaces in the export, without
    in the app, and sometimes in lowercase. Comparing unnormalised gives a second
    account for the same bank account, and with it duplicate transactions in
    every total.
    """
    if iban is None:
        return None
    clean = re.sub(r"\s+", "", str(iban)).upper()
    return clean or None


def _verify_date(date: str) -> str:
    """YYYY-MM-DD only.

    The whole codebase compares and sorts dates as text (see
    database.load_transactions' ORDER BY date). That only works as long as every
    date has the same form, so a deviating form must be stopped here and not
    quietly sort at the end.
    """
    if not isinstance(date, str) or not _ISO_DATE.match(date):
        raise ValueError(tr("Date must be YYYY-MM-DD, got: {0}", repr(date)))
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(tr("Not an existing date: {0}", repr(date))) from e
    return date


def _verify_choice(name: str, value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ValueError(tr("Unknown {0}: {1}. Choose from: {2}", name, repr(value), ", ".join(allowed)))
    return value


def _exists(conn: sqlite3.Connection, account_id: int) -> bool:
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,))
    return cursor.fetchone() is not None


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def make_bank_account(
    conn: sqlite3.Connection,
    *,
    kind: str,
    provider: str,
    name: str,
    iban: str | None = None,
    currency: str = "EUR",
    external_id: str | None = None,
) -> int:
    """Creates an account and returns the new id."""
    _verify_choice("kind", kind, KINDS)
    _verify_choice("provider", provider, PROVIDERS)

    name = (name or "").strip()
    if not name:
        raise ValueError(tr("An account must have a name."))

    iban = normalise_iban(iban)

    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO accounts
                (kind, provider, name, iban, currency, external_id, active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (kind, provider, name, iban, currency, external_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
    except db.IntegrityError as e:
        # The only UNIQUE on this table is the IBAN.
        raise AccountExistsAlready(tr("There is already an account with IBAN {0}.", iban)) from e
    conn.commit()
    return cursor.lastrowid


def load_accounts(conn: sqlite3.Connection, *, only_active: bool = False) -> list[dict]:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM accounts" + (" WHERE active = 1" if only_active else "") + " ORDER BY name ASC")
    return [dict(row) for row in cursor.fetchall()]


def load_account(conn: sqlite3.Connection, account_id: int) -> dict | None:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def search_on_iban(conn: sqlite3.Connection, iban: str | None) -> dict | None:
    """The account with this IBAN, or None. Normalises first.

    Without normalising, the same bank account with spaces in the export and
    without in the app gives two accounts, and then all amounts count twice.
    """
    normalised = normalise_iban(iban)
    if normalised is None:
        return None
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM accounts WHERE iban = ?", (normalised,))
    row = cursor.fetchone()
    return dict(row) if row else None


def search_on_external_id(conn: sqlite3.Connection, provider: str, external_id: str | None) -> dict | None:
    """The account with this number at this provider, or None.

    For accounts without an IBAN: an ING savings account is called "C57583172",
    and that number comes back in every export of that account.
    """
    if not external_id:
        return None
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM accounts WHERE provider = ? AND external_id = ?", (provider, external_id))
    row = cursor.fetchone()
    return dict(row) if row else None


def update_account(conn: sqlite3.Connection, account_id: int, **fields) -> None:
    """Updates the given fields; leaves the rest alone.

    An unknown field name is an error and not a no-op: a typo in a column name
    would otherwise silently do nothing and look in the UI as if saving had
    worked.
    """
    if not fields:
        return

    unknown = set(fields) - set(UPDATABLE_FIELDS)
    if unknown:
        raise ValueError(tr("Unknown field: {0}. Fields that can be updated: {1}", ", ".join(sorted(unknown)), ", ".join(UPDATABLE_FIELDS)))

    if "kind" in fields:
        _verify_choice("kind", fields["kind"], KINDS)
    if "provider" in fields:
        _verify_choice("provider", fields["provider"], PROVIDERS)
    if "name" in fields:
        fields["name"] = (fields["name"] or "").strip()
        if not fields["name"]:
            raise ValueError(tr("An account must have a name."))

    if not _exists(conn, account_id):
        raise AccountUnknown(tr("Account {0} does not exist.", account_id))

    columns = ", ".join(f"{k} = ?" for k in fields)
    conn.cursor().execute(
        f"UPDATE accounts SET {columns} WHERE id = ?",
        (*fields.values(), account_id),
    )
    conn.commit()


def delete_account(conn: sqlite3.Connection, account_id: int) -> None:
    """Deletes the account and everything attached to it.

    The balances and the transactions are removed here by hand: connect() leaves
    PRAGMA foreign_keys at the default (off), so the REFERENCES clauses in the
    schema clean up nothing. Rows left behind would keep counting in every total
    for an account that no longer exists.

    As separate SQL and not through bank_transactions.py, so the cleanup sits in
    one spot and this module needs to know nothing about that layer.
    """
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bank_transactions WHERE account_id = ?", (account_id,))
    cursor.execute("DELETE FROM account_balances WHERE account_id = ?", (account_id,))
    cursor.execute("DELETE FROM debt_schedules WHERE account_id = ?", (account_id,))
    cursor.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.commit()


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


def set_balance(
    conn: sqlite3.Connection,
    account_id: int,
    date: str,
    balance: float,
    source: str = "manual",
) -> None:
    """Records the balance on a day; a second time on the same day replaces it.

    Replace and not stack, because a second measurement on the same day is in
    practice a correction — you typed your balance over wrong and enter it again.
    """
    _verify_date(date)
    _verify_choice("source", source, SOURCES)
    account = load_account(conn, account_id)
    if account is None:
        raise AccountUnknown(tr("Account {0} does not exist.", account_id))

    # A debt is always negative, however it was entered. Someone entering their
    # student debt types "25000" and not "-25000", and without this rule that
    # counted as 25,000 euros of assets: net worth then shot 50,000 euros the wrong
    # way, without an error, because a positive number is a valid balance. Here and
    # not in net_worth.py, so *every* total — also that of the Accounts page — sees
    # the same number.
    if account["kind"] == "debt":
        balance = -abs(float(balance))

    conn.cursor().execute(
        """
        INSERT INTO account_balances (account_id, date, balance, source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(account_id, date) DO UPDATE SET
            balance = excluded.balance,
            source  = excluded.source
        """,
        (account_id, date, float(balance), source),
    )
    conn.commit()


def set_balances(
    conn: sqlite3.Connection,
    account_id: int,
    balances: list[tuple[str, float]],
    source: str = "sync",
) -> int:
    """set_balance for a whole series at once, in one transaction.

    A balance overview of six years is thousands of days; one commit per day
    turns an upload into a waiting room. Same rules as set_balance: the same day
    replaces, and a debt is negative.
    """
    _verify_choice("source", source, SOURCES)
    account = load_account(conn, account_id)
    if account is None:
        raise AccountUnknown(tr("Account {0} does not exist.", account_id))
    debt = account["kind"] == "debt"
    rows = [(account_id, _verify_date(date), -abs(float(balance)) if debt else float(balance), source) for date, balance in balances]
    conn.cursor().executemany(
        """
        INSERT INTO account_balances (account_id, date, balance, source)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(account_id, date) DO UPDATE SET
            balance = excluded.balance,
            source  = excluded.source
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def save_entries(conn: sqlite3.Connection, account_id: int, entries: list[dict]) -> int:
    """Stores money movements of an account without bank transactions of its own.

    `entries`: [{date, amount (positive = in), description, key}]. The key makes
    a second upload of the same overview harmless. Returns the number of new ones.
    """
    if not _exists(conn, account_id):
        raise AccountUnknown(tr("Account {0} does not exist.", account_id))
    cursor = conn.cursor()
    before = conn.total_changes
    cursor.executemany(
        """
        INSERT OR IGNORE INTO account_entries (account_id, date, amount, description, key)
        VALUES (?, ?, ?, ?, ?)
        """,
        [(account_id, _verify_date(m["date"]), float(m["amount"]), m.get("description"), f"{account_id}|{m['key']}") for m in entries],
    )
    conn.commit()
    return conn.total_changes - before


def load_entries(conn: sqlite3.Connection) -> list[dict]:
    """All stored money movements, with the kind of their account."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.id, m.account_id, m.date, m.amount, m.description, r.kind
          FROM account_entries m JOIN accounts r ON r.id = m.account_id
         ORDER BY m.date, m.id
    """)
    return [dict(row) for row in cursor.fetchall()]


def delete_balance(conn: sqlite3.Connection, account_id: int, date: str) -> bool:
    """Removes one measurement. False if there was none on that date.

    Correcting does not need this: a new measurement on the same date already
    replaces the old one. This is for a measurement that should never have been
    there.
    """
    _verify_date(date)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM account_balances WHERE account_id = ? AND date = ?", (account_id, date))
    conn.commit()
    return cursor.rowcount > 0


def move_balance(conn: sqlite3.Connection, account_id: int, start: str, dest: str) -> bool:
    """Moves a measurement to another day. False if there was none on `start`.

    If there already is a measurement on `end`, that one stays and this one
    goes: two measurements on one day is not possible, and the existing one is
    usually what you entered yourself.
    """
    _verify_date(start)
    _verify_date(dest)
    row = conn.execute("SELECT balance, source FROM account_balances WHERE account_id = ? AND date = ?", (account_id, start)).fetchone()
    if row is None:
        return False
    if start != dest:
        conn.execute(
            "INSERT OR IGNORE INTO account_balances (account_id, date, balance, source) VALUES (?, ?, ?, ?)",
            (account_id, dest, row[0], row[1]),
        )
        conn.execute("DELETE FROM account_balances WHERE account_id = ? AND date = ?", (account_id, start))
    conn.commit()
    return True


def load_balances(conn: sqlite3.Connection, account_id: int | None = None) -> list[dict]:
    """All measurements, ascending by date. Without account_id: of all accounts."""
    cursor = conn.cursor()
    if account_id is None:
        cursor.execute("SELECT * FROM account_balances ORDER BY date ASC, account_id ASC")
    else:
        cursor.execute(
            "SELECT * FROM account_balances WHERE account_id = ? ORDER BY date ASC",
            (account_id,),
        )
    return [dict(row) for row in cursor.fetchall()]


def last_balance(conn: sqlite3.Connection, account_id: int) -> dict | None:
    """The most recent measurement of this account, or None if there is none yet.

    Separate from balance_on because an overview wants not only the amount but
    also when it was measured: "€1,000, on 31 January" says something different
    from "€1,000", certainly if you have not looked for half a year.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM account_balances WHERE account_id = ? ORDER BY date DESC LIMIT 1",
        (account_id,),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def value_on(balances: list[dict], date: str, dates: list[str] | None = None) -> float:
    """The balance on *date*, from the measurements of one account (ascending by date).

      before the first measurement       0 — the source did not exist for you yet
      on a measurement day               that measurement
      between two manual measurements    a straight line between them
      between measurements, one import   the previous one, until the next
      after the last measurement         the last one

    `dates` may be passed in when the same list is searched many times; the net
    worth series asks this for every day.
    """
    if not balances:
        return 0.0
    dates = dates if dates is not None else [m["date"] for m in balances]
    i = bisect.bisect_right(dates, date)
    if i == 0:
        return 0.0
    previous = balances[i - 1]
    if previous["date"] == date or i == len(balances):
        return previous["balance"]
    following = balances[i]
    if previous.get("source") != "manual" or following.get("source") != "manual":
        return previous["balance"]
    d0 = datetime.strptime(previous["date"], "%Y-%m-%d").date()
    d1 = datetime.strptime(following["date"], "%Y-%m-%d").date()
    d = datetime.strptime(date, "%Y-%m-%d").date()
    fraction = (d - d0).days / (d1 - d0).days
    return previous["balance"] + (following["balance"] - previous["balance"]) * fraction


def balances_for_series(conn: sqlite3.Connection, account_id: int) -> list[dict]:
    """The balances with which an account counts over time.

    If an account has transactions (from an export or by hand) *and* at least one
    balance, we reconstruct the balance assuming all transactions are present.
    Missing transactions make the reconstruction incomplete. One known balance
    fixes the level; the rest follows, for every day the transactions say
    something about. The anchor is the last measurement — usually what you just
    saw in your banking app. Earlier measurements then no longer count: if they
    were right they give the same, and if they were wrong every measurement
    would make the line jump.

    A transfer to another own account then stands on the same day on both sides,
    instead of being lost for a month between two measurements.

    Without transactions or without a balance: just the measurements. An account
    with transactions but without a balance has no level; it does not count, and
    the net worth page says which one it is.

    Derived points carry source "derived": they only change through a
    transaction, so between two transaction days the balance stays flat.
    """
    measurements = load_balances(conn, account_id)
    if not measurements:
        return measurements
    # A debt with interest and repayment runs on by itself from the last
    # measurement; see debt_schedule.py.
    if debt_schedule.load(conn, account_id):
        return debt_schedule.points(conn, account_id, measurements)
    return _with_transfers_from_elsewhere(conn, account_id, _from_own_transactions(conn, account_id, measurements))


# Kinds whose balance, after their own data, runs on with what your other
# accounts did with them. Not a broker: money that comes in there becomes
# shares, and those are in the portfolio.
WALK_THROUGH_VIA_TRANSFERS = ("bank",)
# Shorter than this, an account number is too common to search for in a description.
MIN_NUMBER_LENGTH = 6
# Which share of an account's own transactions must be internal (between your
# own accounts) for it to move along with transfers from elsewhere. A savings
# account books only to and from your current account, plus some interest; a
# current account books mostly with shops and employers.
MIN_SHARE_INTERNAL = 0.5


def _moves_along_with_transfers(conn: sqlite3.Connection, account_id: int) -> bool:
    """Is this an account that only moves money with your own accounts?

    Only then is what your other accounts did with it the whole story. A current
    account whose export stops in February would otherwise move along with the
    deposits your savings account shows until August — without the salary and
    the groceries of those months. That is half a picture, and half a picture is
    worse than an old one.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n, SUM(CASE WHEN type_effective = 'INTERNAL' THEN 1 ELSE 0 END) AS internal "
        "FROM bank_transactions_typed WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    return not row["n"] or (row["internal"] or 0) / row["n"] >= MIN_SHARE_INTERNAL


def transfers_from_elsewhere(conn: sqlite3.Connection, account: dict) -> list[tuple[str, float]]:
    """(date, change of the balance) of `account`, from bookings on your other accounts that name it.

    A savings account you cannot connect still visibly moves: every euro that
    goes to it or comes off it is also on your current account. Recognised by
    its IBAN as counterparty account, or by its account number (ING: "To Oranje
    spaarrekening H12345678") in the counterparty account, the name or the
    description. Nothing per bank: what the account itself has in numbers is
    what is searched for.

    A debit elsewhere (positive in the database) is a credit here.
    """
    iban = normalise_iban(account.get("iban"))
    number = re.sub(r"\s+", "", account.get("external_id") or "").upper()
    if len(number) < MIN_NUMBER_LENGTH:
        number = ""
    if not iban and not number:
        return []

    terms, params = [], []
    if iban:
        terms.append("UPPER(REPLACE(COALESCE(counterparty_iban, ''), ' ', '')) = ?")
        params.append(iban)
    if number:
        terms.append("UPPER(COALESCE(counterparty_iban, '') || ' ' || COALESCE(name, '') || ' ' || COALESCE(description, '')) LIKE ?")
        params.append(f"%{number}%")
    rows = conn.execute(
        f"SELECT date, amount, name, description, counterparty_iban FROM bank_transactions "
        f"WHERE account_id != ? AND ({' OR '.join(terms)})",
        (account["id"], *params),
    ).fetchall()

    # The number as a whole word: H12345678 not inside XH123456789.
    loose = re.compile(rf"(?<![A-Z0-9]){re.escape(number)}(?![A-Z0-9])") if number else None
    off = []
    for r in rows:
        hit = bool(iban) and normalise_iban(r["counterparty_iban"]) == iban
        if not hit and loose:
            hit = any(loose.search((field or "").upper()) for field in (r["counterparty_iban"], r["name"], r["description"]))
        if hit:
            off.append((r["date"], float(r["amount"])))
    return sorted(off)


def _with_transfers_from_elsewhere(conn: sqlite3.Connection, account_id: int, points: list[dict]) -> list[dict]:
    """Lets the balance run on after the last own data with transfers from elsewhere.

    Only *after* the last point from the account itself (a measurement or an own
    transaction): what happened before that is already in that own data, and
    would otherwise count twice. A new export or an entered balance moves that
    point forward, and takes over again from there. Interest the bank credits
    does not show this way; it comes with the next export.

    These points carry source "transfer".
    """
    account = load_account(conn, account_id)
    if not points or not account or account["kind"] not in WALK_THROUGH_VIA_TRANSFERS or not _moves_along_with_transfers(conn, account_id):
        return points
    final = points[-1]["date"]
    per_day: dict[str, float] = {}
    for day, change in transfers_from_elsewhere(conn, account):
        if day > final:
            per_day[day] = per_day.get(day, 0.0) + change
    if not per_day:
        return points
    balance = points[-1]["balance"]
    added = []
    for day in sorted(per_day):
        balance += per_day[day]
        added.append({"date": day, "balance": round(balance, 2), "source": "transfer"})
    return points + added


def _from_own_transactions(conn: sqlite3.Connection, account_id: int, measurements: list[dict]) -> list[dict]:
    """The balances from the measurements and the own transactions; see balances_for_series."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT date, SUM(amount) AS summed FROM bank_transactions WHERE account_id = ? GROUP BY date ORDER BY date",
        (account_id,),
    )
    # Spending is positive, so an expense lowers the balance.
    per_day = [(r["date"], -r["summed"]) for r in cursor.fetchall()]
    if not per_day:
        return measurements

    anchor = measurements[-1]
    through_anchor = sum(m for d, m in per_day if d <= anchor["date"])
    # A transaction also gives the balance right before that booking. This is a
    # derived opening balance, not proof of a longer earlier history.
    first_day = datetime.strptime(per_day[0][0], "%Y-%m-%d").date()
    points: dict[str, float] = {}
    if first_day > datetime.min.date():
        opening = (first_day - timedelta(days=1)).isoformat()
        points[opening] = anchor["balance"] - through_anchor
    running = 0.0
    for d, m in per_day:
        running += m
        points[d] = anchor["balance"] + running - through_anchor
    points.setdefault(anchor["date"], anchor["balance"])
    return [{"date": d, "balance": round(v, 2), "source": "derived"} for d, v in sorted(points.items())]


def balance_on(conn: sqlite3.Connection, account_id: int, date: str) -> float:
    """The balance of one account on a day. See value_on for the rules."""
    _verify_date(date)
    return value_on(balances_for_series(conn, account_id), date)


def total_balance_on(conn: sqlite3.Connection, date: str) -> float:
    """All active accounts together on one day."""
    _verify_date(date)
    return sum(balance_on(conn, r["id"], date) for r in load_accounts(conn, only_active=True))


# ---------------------------------------------------------------------------
# A balance that does not match the transactions: why, and correcting it.
#
# The series calculates back from the last measurement (balances_for_series).
# An earlier measurement should land exactly on it; if it does not,
# net_worth.series says so, and explain_deviation explains what is probably
# going on. `difference` is measured − calculated everywhere.

# How long a payment can still be pending after a balance: a card payment on
# Saturday evening is sometimes only booked on Monday.
PENDING_DAYS = 3
# How many bookings at most are searched for a subset that explains the
# difference exactly; above that the search gets too expensive and too
# coincidental.
_MAX_LOOKUP = 16


def pending_at_measurement(conn: sqlite3.Connection, account_id: int, date: str, difference: float) -> dict | None:
    """Bookings shortly *after* `date` that explain the difference exactly.

    Your bank takes a card payment off your balance straight away (ING only gives
    that "expected" balance through the connection), but the transaction only
    comes in on the day it is booked. A balance from then is exactly those
    payments lower than the booked balance of that day.

    First whole days — everything of the day after, or of the two days after —:
    the common case, and certain enough to correct automatically (`whole`). Then
    a subset of the bookings, for when new payments came in after the balance as
    well; that is a hint, not proof.

    Returns {"end", "count", "sum", "whole"} or None.
    """
    from itertools import combinations

    target = round(-difference * 100)  # in cents; an expense is positive
    if target == 0:
        return None
    final = (datetime.strptime(date, "%Y-%m-%d").date() + timedelta(days=PENDING_DAYS)).isoformat()
    rows = conn.execute(
        "SELECT date, amount FROM bank_transactions WHERE account_id = ? AND date > ? AND date <= ? ORDER BY date, id",
        (account_id, date, final),
    ).fetchall()
    bookings = [(r[0], round(float(r[1]) * 100)) for r in rows]
    summed = 0
    for i, (day, cents) in enumerate(bookings):
        summed += cents
        end_of_the_day = i + 1 == len(bookings) or bookings[i + 1][0] != day
        if end_of_the_day and summed == target:
            return {"end": day, "count": i + 1, "summed": round(target / 100, 2), "whole": True}
    if len(bookings) <= _MAX_LOOKUP:
        for n in range(1, len(bookings) + 1):
            for part in combinations(bookings, n):
                if sum(c for _, c in part) == target:
                    return {"end": max(d for d, _ in part), "count": n, "summed": round(target / 100, 2), "whole": False}
    return None


def during_the_day(conn: sqlite3.Connection, account_id: int, date: str, difference: float) -> dict | None:
    """Bookings of that same day that were not in yet when it was fetched.

    A fetched balance is a snapshot: at eight in the morning that afternoon's
    Tikkie is not in it yet, but the series calculates with the balance at the
    end of the day. If a subset of that day's bookings explains the difference
    exactly, the balance was simply right — it was just early.

    Returns {"count", "sum"} or None. `difference` is measured − end of day: an
    expense that came later makes the measured balance higher.
    """
    from itertools import combinations

    target = round(difference * 100)
    if target == 0:
        return None
    bookings = [
        round(float(r[0]) * 100)
        for r in conn.execute("SELECT amount FROM bank_transactions WHERE account_id = ? AND date = ?", (account_id, date))
    ]
    if not bookings or len(bookings) > _MAX_LOOKUP:
        return None
    for n in range(1, len(bookings) + 1):
        for part in combinations(bookings, n):
            if sum(part) == target:
                return {"count": n, "summed": round(abs(target) / 100, 2)}
    return None


def _explained(conn: sqlite3.Connection, account_id: int, date: str, difference: float, source: str) -> bool:
    # During the day only for a fetched balance: what you entered yourself has no
    # time, and there "shifted by a day" (fits_on_day) is the better explanation.
    return (
        abs(difference) <= 0.011
        or (source == "sync" and during_the_day(conn, account_id, date, difference) is not None)
        or pending_at_measurement(conn, account_id, date, difference) is not None
    )


def anchor_difference(
    conn: sqlite3.Connection, account_id: int, anchor: str, differences: list[tuple[str, float, str]], *, present_day: date | None = None
) -> float:
    """What is in the last balance and not yet in the transactions.

    The series calculates back from the last balance. If the bank had already
    taken off a payment that is not booked yet, *every* earlier balance deviates
    by exactly that amount — nine reports for one payment that is pending. This
    looks for the one amount that, subtracted from all differences, explains the
    most balances. 0.0 if there is no such amount.

    Only when the last balance is recent (PENDING_DAYS): a payment is booked
    after a few days. If the difference stays, something really is missing, and
    then each balance should simply get its own report.

    `differences` is [(date, measured − calculated, source)] of the earlier
    balances.
    """
    from collections import Counter

    present_day = present_day or date.today()
    if date.fromisoformat(anchor) < present_day - timedelta(days=PENDING_DAYS):
        return 0.0
    open_ = [(d, v, b) for d, v, b in differences if not _explained(conn, account_id, d, v, b)]
    if len(open_) < 2:
        return 0.0
    candidates = Counter(round(v, 2) for _, v, _ in open_)
    best, best_n = 0.0, 0
    for delta, _ in candidates.most_common(5):
        n = sum(1 for d, v, b in open_ if _explained(conn, account_id, d, round(v - delta, 2), b))
        if n > best_n:
            best, best_n = delta, n
    # At least two balances, and most of what was open: otherwise it is chance.
    return best if best_n >= 2 and best_n * 2 > len(open_) else 0.0


def fits_on_day(series: list[dict], date: str, balance: float, end: str) -> str | None:
    """The nearest day (within PENDING_DAYS, not after `end`) on which the balance
    calculated from the transactions is exactly `balance`. A balance you looked
    at on Sunday and entered on Monday, for example.
    """
    dates = [p["date"] for p in series]
    d0 = datetime.strptime(date, "%Y-%m-%d").date()
    for step in range(1, PENDING_DAYS + 1):
        for direction in (1, -1):
            day = (d0 + timedelta(days=direction * step)).isoformat()
            if dates[0] <= day <= end and abs(value_on(series, day, dates) - balance) <= 0.011:
                return day
    return None


def _duplicate_between(conn: sqlite3.Connection, account_id: int, start: str, end: str, difference: float) -> dict | None:
    """A transaction that appears more than once and explains the difference exactly."""
    target = round(-difference * 100)
    for r in conn.execute(
        "SELECT date, amount, name, COUNT(*) AS n FROM bank_transactions "
        "WHERE account_id = ? AND date > ? AND date <= ? "
        "GROUP BY date, amount, name HAVING COUNT(*) > 1 ORDER BY date",
        (account_id, start, end),
    ).fetchall():
        if round(float(r[1]) * 100) * (r[3] - 1) == target:
            return {"kind": "duplicate", "date": r[0], "name": r[2], "amount": abs(float(r[1])), "count": r[3]}
    return None


def explain_deviation(
    conn: sqlite3.Connection, account_id: int, series: list[dict], measurement: dict, calculated: float, anchor: str, occupied: set[str]
) -> dict:
    """The most likely reason a balance does not match, from certain to vague.

    pending      bookings shortly after explain it exactly: they were already in
                 the balance, but not yet in the transactions
    other_day    the amount fits exactly with a nearby day; `occupied` when
                 there already is a measurement there
    duplicate    a transaction that appears more than once explains it exactly
    missing      none of the three: between this balance and the last one some
                 credits or debits are missing, or this balance is not right
    """
    difference = round(measurement["balance"] - calculated, 2)
    pending = pending_at_measurement(conn, account_id, measurement["date"], difference)
    if pending:
        return {"kind": "pending", **pending}
    day = fits_on_day(series, measurement["date"], measurement["balance"], anchor)
    if day:
        return {"kind": "other_day", "day": day, "occupied": day in occupied}
    duplicate = _duplicate_between(conn, account_id, measurement["date"], anchor, difference)
    if duplicate:
        return duplicate
    # Measured lower than calculated: more came in in between than the
    # transactions show (or there is one debit too many).
    return {"kind": "missing", "direction": "credits" if difference < 0 else "debits", "amount": abs(difference)}


def restore_pending(conn: sqlite3.Connection, account_id: int) -> int:
    """Corrects fetched balances that counted payments that were still pending
    then, or that were fetched halfway through the day (during_the_day).

    Only source "sync" — never what you entered yourself — and only when whole
    days of bookings after it explain the difference to the cent
    (pending_at_measurement, `whole`). The balance then becomes the booked
    balance of that day: what the transactions say. Returns the number of
    corrected balances.
    """
    measurements = load_balances(conn, account_id)
    if len(measurements) < 2 or debt_schedule.load(conn, account_id):
        return 0
    series = balances_for_series(conn, account_id)
    if not series or series[0]["source"] != "derived":
        return 0
    dates = [p["date"] for p in series]
    today = date.today().isoformat()
    prior = [m for m in measurements[:-1] if m["date"] >= dates[0]]
    calculated_on = {m["date"]: round(value_on(series, m["date"], dates), 2) for m in prior}
    # What is already pending in the last balance is not in the transactions yet:
    # without this every corrected balance would miss that payment.
    delta = anchor_difference(
        conn,
        account_id,
        measurements[-1]["date"],
        [(m["date"], round(m["balance"] - calculated_on[m["date"]], 2), m["source"]) for m in prior],
    )
    restored = 0
    for m in prior:
        if m["source"] != "sync":
            continue
        calculated = round(calculated_on[m["date"]] + delta, 2)
        difference = round(m["balance"] - calculated, 2)
        if abs(difference) <= 0.011:
            continue
        explanation = pending_at_measurement(conn, account_id, m["date"], difference)
        # Fetched halfway through the day: once the day is over and all its bookings
        # are in, it becomes the balance at the end of that day.
        early = m["date"] < today and during_the_day(conn, account_id, m["date"], difference)
        if (explanation and explanation["whole"]) or early:
            set_balance(conn, account_id, m["date"], calculated, source="sync")
            restored += 1
    return restored
