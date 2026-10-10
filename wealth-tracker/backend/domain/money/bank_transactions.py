"""
bank_transactions.py — storing and reading back bank rows.

What bank_providers/ reads comes in here. One property carries this layer:

    Importing the same export twice adds nothing.

Bank exports simply overlap — you download the last three months in March and
again in April — and without that property every total grows with every
import. `dedup_hash` does that work; see bank_providers/base.py for how it is
made and why two identical coffees on one day still stay two rows.

The database is the archive here, not a cache. A PSD2 connection later only
shows ~90 days, so what is not in here is gone. That is why an unreadable row
is reported but never silently left out.

Three columns for the category, the model from the old spreadsheet:

    category_auto     what the rules concluded
    category_manual   what you decided            -> always wins
    category          the answer: manual if there is one, otherwise auto

Because of that, updating a rule can relabel the whole history without ever
overwriting a judgement of yours.

As in database.py every function takes an explicit `conn` as its first
argument; there is no implicit "current user".
"""

from collections import Counter
import json
import math
import re
import sqlite3
import uuid
from domain import db
from domain.i18n import tr


_COLUMNS = (
    "account_id", "date", "interest_date", "amount", "currency", "name",
    "counterparty_iban", "description", "code", "kind", "dedup_hash", "raw",
)


def _from_row(row: sqlite3.Row) -> dict:
    raw_row = dict(row)
    raw_row["raw"] = json.loads(raw_row["raw"]) if raw_row["raw"] else {}
    # Category and type come from the view bank_transactions_typed
    # (database.init_db), so the rule for both lives in one place and net_worth.py
    # counts exactly what this list shows. The stored column `type` is overwritten
    # here: nobody writes it any more.
    raw_row["category"] = raw_row.pop("category_effective")
    raw_row["type"] = raw_row.pop("type_effective")
    return raw_row


def _known_hashes(cursor, hashes: list[str | None]) -> set[str]:
    hashes = [h for h in hashes if h]
    known: set[str] = set()
    for i in range(0, len(hashes), 500):
        piece = hashes[i:i + 500]
        cursor.execute(f"SELECT dedup_hash FROM bank_transactions WHERE dedup_hash IN ({','.join('?' * len(piece))})",
                       piece)
        known.update(r[0] for r in cursor.fetchall())
    return known


def _existing_bookings(cursor, account_id: int, rows: list[dict]) -> Counter:
    """(date, amount) → count, for the bookings of this account in the period of the
    new rows.
    """
    if not rows:
        return Counter()
    dates = [r["date"] for r in rows]
    cursor.execute(
        "SELECT date, amount FROM bank_transactions WHERE account_id = ? AND date BETWEEN ? AND ?",
        (account_id, min(dates), max(dates)),
    )
    return Counter((d, round(b, 2)) for d, b in cursor.fetchall())


def save(conn: sqlite3.Connection, account_id: int, rows: list[dict]) -> tuple[int, int]:
    """Stores rows that are not there yet. Returns (stored, skipped).

    Skipped is not an error: it is exactly the number of rows you already had,
    and on a second import of the same file that is the whole file.
    """
    cursor = conn.cursor()
    saved = 0
    skipped = 0

    # The same booking from another source. An export and the bank connection
    # describe one debit with a different name and description, so with a
    # different fingerprint; anyone using both for the same account got the
    # overlap twice. So per account this counts too: the same date and the same
    # amount as a booking that is already there and has not been paired with a new
    # row yet. One to one: two coffees of three euros on one day stay two, a third
    # one in a later export is added.
    known = _known_hashes(cursor, [r.get("dedup_hash") for r in rows])
    counter = _existing_bookings(cursor, account_id, rows)
    new = []
    for row in rows:
        key = (row["date"], round(float(row["amount"]), 2))
        if row.get("dedup_hash") in known:
            # Exactly this row was already there; it stands for that booking.
            counter[key] = max(0, counter[key] - 1)
            skipped += 1
        else:
            new.append((row, key))
    for row, key in new:
        if counter[key] > 0:
            counter[key] -= 1
            skipped += 1
            continue
        values = {k: row.get(k) for k in _COLUMNS}
        values["account_id"] = account_id
        values["raw"] = json.dumps(row.get("raw") or {}, ensure_ascii=False)
        try:
            cursor.execute(
                f"""
                INSERT INTO bank_transactions ({", ".join(_COLUMNS)})
                VALUES ({", ".join(":" + k for k in _COLUMNS)})
                """,
                values,
            )
            saved += 1
        except db.IntegrityError:
            # The only UNIQUE is dedup_hash: this row was already there.
            skipped += 1

    conn.commit()
    return saved, skipped


class NotManual(Exception):
    """This transaction comes from an import and cannot be deleted by hand."""


def add_manually(
    conn: sqlite3.Connection,
    *,
    account_id: int,
    date: str,
    amount: float,
    name: str,
    description: str = "",
) -> int:
    """An expense or income that is in no export: cash, a market, a refund that came
    by nowhere else. Returns the new id.

    `amount` follows the convention of the whole books: spending positive,
    income negative.

    The dedup hash is random here and not derived from the content. In an import
    an identical row is a duplicate; someone who enters three euros for coffee by
    hand twice means two coffees.
    """
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
        raise ValueError(tr("Date must be YYYY-MM-DD, got: {0}", repr(date)))
    name = (name or "").strip()
    if not name:
        raise ValueError(tr("Say what it was spent on."))
    if amount is None or not math.isfinite(amount) or amount == 0:
        raise ValueError(tr("A transaction of zero is not a transaction."))

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO bank_transactions
            (account_id, date, amount, currency, name, description, dedup_hash, raw, source)
        VALUES (?, ?, ?, 'EUR', ?, ?, ?, ?, 'manual')
        """,
        (account_id, date, float(amount), name, (description or "").strip(),
         uuid.uuid4().hex[:16], json.dumps({"source": "manual"})),
    )
    conn.commit()
    return cursor.lastrowid


def delete_manual(conn: sqlite3.Connection, transaction_id: int) -> bool:
    """Removes a manually entered transaction. False if it does not exist.

    Not an imported transaction: that simply comes back with the next import of
    the same export, and then the delete seems to have worked while it has not.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT source FROM bank_transactions WHERE id = ?", (transaction_id,))
    row = cursor.fetchone()
    if row is None:
        return False
    if row["source"] != "manual":
        raise NotManual(tr("Only manually entered transactions can be deleted here."))
    cursor.execute("DELETE FROM bank_transactions WHERE id = ?", (transaction_id,))
    conn.commit()
    return True


def load(
    conn: sqlite3.Connection,
    *,
    account_id: int | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[dict]:
    """Transactions, ascending by date. All filters are optional and inclusive."""
    terms = []
    values: list = []
    if account_id is not None:
        terms.append("account_id = ?")
        values.append(account_id)
    if start:
        terms.append("date >= ?")
        values.append(start)
    if end:
        terms.append("date <= ?")
        values.append(end)

    where = f"WHERE {' AND '.join(terms)}" if terms else ""
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT * FROM bank_transactions_typed {where} ORDER BY date ASC, id ASC",
        values,
    )
    return [_from_row(row) for row in cursor.fetchall()]


def set_category_auto(conn: sqlite3.Connection, transaction_id: int, category: str | None,
                       source: str | None = "rule", *, commit: bool = True) -> None:
    """What the rules concluded. Never touches a manual choice.

    That last part is not in this function but in the derived `category`: manual
    wins, so auto can safely be overwritten by a new rule round without losing a
    judgement. `source` says where it came from: 'rule', 'learned' or 'ai'.
    """
    conn.cursor().execute(
        "UPDATE bank_transactions SET category_auto = ?, category_source = ? WHERE id = ?",
        (category, source, transaction_id),
    )
    # relabel() writes thousands in a row and commits once at the end.
    if commit:
        conn.commit()


def set_category_manual(
    conn: sqlite3.Connection, transaction_id: int, category: str | None
) -> None:
    """Your judgement. None clears it, after which auto takes over again."""
    conn.cursor().execute(
        "UPDATE bank_transactions SET category_manual = ? WHERE id = ?",
        (category, transaction_id),
    )
    conn.commit()


def set_category_manual_for(
    conn: sqlite3.Connection, transaction_ids: list[int], category: str | None
) -> int:
    """set_category_manual for many transactions at once. Returns how many existed."""
    ids = sorted({int(i) for i in transaction_ids})
    if not ids:
        return 0
    cursor = conn.cursor()
    cursor.executemany("UPDATE bank_transactions SET category_manual = ? WHERE id = ?",
                       [(category, i) for i in ids])
    conn.commit()
    return cursor.rowcount if cursor.rowcount >= 0 else len(ids)


def delete_for_account(conn: sqlite3.Connection, account_id: int) -> int:
    """All transactions of one account. Returns how many were removed."""
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bank_transactions WHERE account_id = ?", (account_id,))
    conn.commit()
    return cursor.rowcount


def date_range(conn: sqlite3.Connection, account_id: int | None = None) -> dict:
    """{total, first, last}: how many transactions there are and over which period.

    Independent of any period filter. A list that is empty for the chosen period
    must be able to say whether anything was ever imported — otherwise an empty
    period says "import a bank export" while there are hundreds of transactions,
    just from before that period.
    """
    cursor = conn.cursor()
    if account_id is None:
        cursor.execute("SELECT COUNT(*) AS n, MIN(date) AS start, MAX(date) AS end FROM bank_transactions")
    else:
        cursor.execute(
            "SELECT COUNT(*) AS n, MIN(date) AS start, MAX(date) AS end "
            "FROM bank_transactions WHERE account_id = ?", (account_id,))
    row = cursor.fetchone()
    return {"total": row["n"], "first": row["start"], "last": row["end"]}


def count(conn: sqlite3.Connection, account_id: int | None = None) -> int:
    cursor = conn.cursor()
    if account_id is None:
        cursor.execute("SELECT COUNT(*) AS n FROM bank_transactions")
    else:
        cursor.execute(
            "SELECT COUNT(*) AS n FROM bank_transactions WHERE account_id = ?", (account_id,)
        )
    return cursor.fetchone()["n"]
