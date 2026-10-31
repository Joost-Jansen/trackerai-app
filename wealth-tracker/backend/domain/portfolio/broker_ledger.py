"""
broker_ledger.py — a broker account's cash, from its own movements.

A broker account (kind `broker`, provider a code from brokers.py) holds money
that is not invested: a deposit not yet spent, a dividend, interest. Its
balance is the sum of every movement on it, so this module keeps those
movements in `account_entries` (positive = money in) and writes the running
balance per day to `account_balances` (source "sync"). From there it is an
account like any other: on the investments stack of net worth, filled forward
between days.

Every movement is here once, whatever it was:

    buy          −(value + fee)       also a row in `transactions`
    sell         +(value − fee)       also a row in `transactions`
    dividend     +(gross − tax)       also a row in `dividends`
    deposit      +amount              pairs with the bank transfer (categorization)
    withdrawal   −amount
    interest     +amount
    fee, tax     −amount
    other        as the source says   (an importer's row of a type it has no kind for)

The trades and dividends are what the portfolio counts; the entries are what
the cash counts. Keeping both is what lets a buy lower the cash and raise the
holdings by the same euros, so net worth does not move when money is invested.

Balances: the running sum from the first movement, which is right for an
account whose history is complete here (an account opened in the app, or a
full export). A balance you enter yourself (source "manual") is never
overwritten; on its day it wins.

As everywhere in the domain layer, every function takes an explicit `conn`.
"""

from __future__ import annotations

import math
import re
import sqlite3
import uuid
from datetime import datetime

from domain.i18n import tr
from domain.money import accounts
from domain.portfolio import brokers

#: The kinds of movement a person can enter, and the sign each has on the cash.
KINDS = ("buy", "sell", "deposit", "withdrawal", "interest", "dividend", "fee", "tax")
_CASH_SIGN = {"deposit": 1, "interest": 1, "withdrawal": -1, "fee": -1, "tax": -1}

_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# The account
# ---------------------------------------------------------------------------


def broker_accounts(conn: sqlite3.Connection) -> list[dict]:
    """Every account of kind broker whose provider is a known broker, oldest first."""
    return [a for a in accounts.load_accounts(conn) if a["kind"] == "broker" and a["provider"] in brokers.BROKERS]


def cash_account(conn: sqlite3.Connection, broker: str, *, create: bool = False, name: str | None = None) -> dict | None:
    """The cash account of `broker`: the first one there is, or a new one when `create`."""
    brokers.verify(broker)
    found = next((a for a in broker_accounts(conn) if a["provider"] == broker), None)
    if found is None and create:
        account_id = accounts.make_bank_account(
            conn, kind="broker", provider=broker, name=(name or "").strip() or brokers.CASH_ACCOUNT_NAMES[broker]
        )
        found = accounts.load_account(conn, account_id)
    return found


def broker_account(conn: sqlite3.Connection, account_id: int) -> dict:
    """The account, checked to be a broker account; AccountUnknown or ValueError otherwise."""
    account = accounts.load_account(conn, account_id)
    if account is None:
        raise accounts.AccountUnknown(tr("Account {0} does not exist.", account_id))
    if account["kind"] != "broker" or account["provider"] not in brokers.BROKERS:
        raise ValueError(tr("'{0}' is not a broker account.", account["name"]))
    return account


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


def sync_balances(conn: sqlite3.Connection, account_id: int) -> int:
    """Rewrites the account's "sync" balances as the running sum of its movements.

    One balance per day with a movement. Days with a balance you entered
    yourself keep it. Without any movement nothing is written: no movements
    is not the same as zero, and an earlier sync balance is removed with them.
    Returns the number of days written.
    """
    cursor = conn.cursor()
    rows = cursor.execute(
        "SELECT date, SUM(amount) AS summed FROM account_entries WHERE account_id = ? GROUP BY date ORDER BY date",
        (account_id,),
    ).fetchall()
    manual_days = {
        r["date"] for r in cursor.execute("SELECT date FROM account_balances WHERE account_id = ? AND source = 'manual'", (account_id,))
    }
    cursor.execute("DELETE FROM account_balances WHERE account_id = ? AND source = 'sync'", (account_id,))
    running = 0.0
    points = []
    for r in rows:
        running += r["summed"]
        if r["date"] not in manual_days:
            points.append((account_id, r["date"], round(running, 2), "sync"))
    if points:
        cursor.executemany("INSERT INTO account_balances (account_id, date, balance, source) VALUES (?, ?, ?, ?)", points)
    conn.commit()
    return len(points)


# ---------------------------------------------------------------------------
# Entering by hand
# ---------------------------------------------------------------------------


def _date(value: str | None) -> str:
    text = (value or "").strip()
    if not _ISO_DATE.match(text):
        raise ValueError(tr("Date must be YYYY-MM-DD, got: {0}", repr(value)))
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(tr("Not an existing date: {0}", repr(value))) from e
    return text


def _positive(value, what: str, *, allow_zero: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(tr("{0} must be a number.", what)) from None
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        raise ValueError(tr("{0} must be a positive number.", what))
    return number


def _isin(value: str | None) -> str:
    text = (value or "").strip().upper()
    if not _ISIN.match(text):
        raise ValueError(tr("'{0}' is not an ISIN (two letters, nine characters and a check digit).", value or ""))
    return text


def _known_name(conn: sqlite3.Connection, isin: str) -> str | None:
    row = conn.execute("SELECT MAX(name) AS name FROM transactions WHERE isin = ?", (isin,)).fetchone()
    return row["name"] if row and row["name"] else None


def add_manual(
    conn: sqlite3.Connection,
    account_id: int,
    *,
    kind: str,
    date: str,
    isin: str | None = None,
    name: str | None = None,
    quantity: float | None = None,
    price: float | None = None,
    amount: float | None = None,
    fee: float | None = None,
    tax: float | None = None,
    description: str | None = None,
) -> dict:
    """Records one movement on a broker account by hand, and returns what was stored.

    Amounts come in positive; the kind gives the direction.

    buy, sell   `isin`, `quantity` (fractions welcome: a savings plan buys
                for an amount) and `price`, or `amount` instead of the price
                (the price is then amount / quantity). `fee` on top.
    dividend    `isin` and the gross `amount`; `tax` withheld.
    the rest    `amount`.
    """
    account = broker_account(conn, account_id)
    if kind not in KINDS:
        raise ValueError(tr("Unknown {0}: {1}. Choose from: {2}", "kind", repr(kind), ", ".join(KINDS)))
    day = _date(date)
    fee_eur = _positive(fee or 0, tr("The fee"), allow_zero=True)
    tax_eur = _positive(tax or 0, tr("The tax"), allow_zero=True)
    note = (description or "").strip() or None
    ref = uuid.uuid4().hex
    cursor = conn.cursor()

    if kind in ("buy", "sell"):
        code = _isin(isin)
        units = _positive(quantity, tr("The quantity"))
        if price not in (None, ""):
            unit_price = _positive(price, tr("The price"))
            value = units * unit_price
        else:
            value = _positive(amount, tr("The amount"))
            unit_price = value / units
        product = (name or "").strip() or _known_name(conn, code) or code
        signed_value = -value if kind == "buy" else value
        total = signed_value - fee_eur
        cursor.execute(
            """
            INSERT INTO transactions (
                order_ref, date, time, name, isin, exchange, execution_venue,
                transaction_type, quantity, price, local_value, value_eur,
                exchange_rate, autofx_cost, transaction_fee, total_eur,
                broker, account_id, source
            ) VALUES (?, ?, NULL, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, 'manual')
            """,
            (
                f"manual-{ref}",
                day,
                product,
                code,
                kind.upper(),
                units,
                round(unit_price, 6),
                round(signed_value, 2),
                round(signed_value, 2),
                -round(fee_eur, 2) if fee_eur else None,
                round(total, 2),
                account["provider"],
                account_id,
            ),
        )
        row_id = cursor.lastrowid
        entry = {"amount": round(total, 2), "description": product, "key": f"manual|transaction|{row_id}", "kind": kind}
        stored = {"table": "transactions", "id": row_id}
    elif kind == "dividend":
        code = _isin(isin)
        gross = _positive(amount, tr("The amount"))
        product = (name or "").strip() or _known_name(conn, code) or code
        net = gross - tax_eur - fee_eur
        cursor.execute(
            """
            INSERT INTO dividends
                (date, isin, name, currency_original, amount_original, gross_eur, tax_eur, net_eur, broker, account_id, source)
            VALUES (?, ?, ?, 'EUR', ?, ?, ?, ?, ?, ?, 'manual')
            """,
            (day, code, product, round(gross, 4), round(gross, 4), -round(tax_eur, 4), round(net, 4), account["provider"], account_id),
        )
        row_id = cursor.lastrowid
        entry = {"amount": round(net, 2), "description": product, "key": f"manual|dividend|{row_id}", "kind": kind}
        stored = {"table": "dividends", "id": row_id}
    else:
        value = _positive(amount, tr("The amount"))
        entry = {"amount": round(_CASH_SIGN[kind] * value, 2), "description": note, "key": f"manual|cash|{ref}", "kind": kind}
        stored = {"table": "account_entries", "id": None}
    conn.commit()

    accounts.save_entries(conn, account_id, [{**entry, "date": day}])
    if stored["id"] is None:
        stored["id"] = conn.execute("SELECT id FROM account_entries WHERE key = ?", (f"{account_id}|{entry['key']}",)).fetchone()["id"]
    sync_balances(conn, account_id)
    return {**stored, "kind": kind, "date": day, "cash": entry["amount"]}


def delete_manual(conn: sqlite3.Connection, table: str, row_id: int) -> bool:
    """Removes a movement entered by hand, with its trade or dividend. Imported rows stay:
    they come back with the next import. False when there is no such manual row."""
    cursor = conn.cursor()
    if table in ("transactions", "dividends"):
        row = cursor.execute(f"SELECT account_id FROM {table} WHERE id = ? AND source = 'manual'", (row_id,)).fetchone()
        if row is None:
            return False
        kind = "transaction" if table == "transactions" else "dividend"
        cursor.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
        if row["account_id"] is not None:
            cursor.execute("DELETE FROM account_entries WHERE key = ?", (f"{row['account_id']}|manual|{kind}|{row_id}",))
        account_id = row["account_id"]
    elif table == "account_entries":
        row = cursor.execute("SELECT account_id, key FROM account_entries WHERE id = ?", (row_id,)).fetchone()
        if row is None or "|manual|cash|" not in row["key"]:
            return False
        cursor.execute("DELETE FROM account_entries WHERE id = ?", (row_id,))
        account_id = row["account_id"]
    else:
        return False
    conn.commit()
    if account_id is not None:
        sync_balances(conn, account_id)
    return True


def ledger(conn: sqlite3.Connection, account_id: int) -> list[dict]:
    """The movements of one broker account, newest first, each saying whether and
    how it can be deleted (`ref`: {table, id} for a manual one, else None)."""
    rows = conn.execute(
        "SELECT id, date, amount, description, key, kind FROM account_entries WHERE account_id = ? ORDER BY date DESC, id DESC",
        (account_id,),
    ).fetchall()
    out = []
    for r in rows:
        parts = r["key"].split("|")
        ref = None
        if len(parts) >= 4 and parts[1] == "manual":
            if parts[2] == "transaction":
                ref = {"table": "transactions", "id": int(parts[3])}
            elif parts[2] == "dividend":
                ref = {"table": "dividends", "id": int(parts[3])}
            elif parts[2] == "cash":
                ref = {"table": "account_entries", "id": r["id"]}
        out.append(
            {
                "id": r["id"],
                "date": r["date"],
                "amount": r["amount"],
                "kind": r["kind"],
                "description": r["description"],
                "source": "manual" if ref else "import",
                "ref": ref,
            }
        )
    return out
