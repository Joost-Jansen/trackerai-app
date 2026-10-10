"""
degiro_cash.py — the money that sits at DeGiro but is not invested.

The portfolio counts what your holdings are worth. The cash on your DeGiro
account — a deposit you have not invested yet, a dividend that was paid out —
it does not count. That is not a rounding matter: after a sale or a deposit it
can be the largest part of your net worth, and it was missing entirely.

The account statement (the same file the Dividend tab already reads) keeps a
running balance itself. This reads the last EUR balance per day from it and
stores that as balances of an account "DeGiro cash" on the investments stack.
From there it is an account like any other: filled forward between two
measurements, and counted in net_worth.py.

The shape of the file, as DeGiro delivers it:

    Datum | Tijd | … | Saldo | (unnamed) | …
                        EUR     1234,56

The currency is in `Saldo`, the amount in the unnamed column after it — the
same layout as the change columns, which dividend_parser.py reads the same
way. English exports call them Date/Time/Balance. The newest row is on top.

Euros only. A USD or DKK balance is a different number in a different
currency; adding them up would count dollars as euros, and converting needs a
rate per day that this file does not have. In practice those balances are
small, but they are missing — and that is written here so nobody thinks they
are included.
"""

import datetime
import sqlite3

import pandas as pd
from domain.imports.degiro_export import read_export

from domain.money import accounts


NAME = "DeGiro cash"
PROVIDER = "degiro"

_DATE = ("Datum", "Date")
_TIME = ("Tijd", "Time")
_BALANCE = ("Saldo", "Balance")


def _column(columns: list[str], names: tuple[str, ...]) -> str | None:
    return next((k for k in columns if k in names), None)


def _amount(value) -> float | None:
    """A number from Excel, or Dutch text ("1.234,56"). None when nothing is there."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if pd.isna(value) else float(value)
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _date(value) -> datetime.date | None:
    if isinstance(value, (datetime.datetime, pd.Timestamp)):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    for form in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, form).date()
        except ValueError:
            continue
    return None


def _time(value) -> str:
    if isinstance(value, datetime.time):
        return value.strftime("%H:%M:%S")
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def read(path: str) -> list[dict]:
    """[{date, balance}] per day: the last EUR balance of that day, ascending.

    "Last" by date and time, and at equal time the row highest in the file —
    DeGiro puts the newest on top, so two bookings in the same minute can still
    be ordered.
    """
    df = read_export(path)
    columns = [str(c).strip() for c in df.columns]
    df.columns = columns

    date_k, time_k, balance_k = _column(columns, _DATE), _column(columns, _TIME), _column(columns, _BALANCE)
    if not date_k or not balance_k:
        return []
    position_balance = columns.index(balance_k)
    if position_balance + 1 >= len(columns):
        return []
    amount_k = columns[position_balance + 1]

    per_day: dict[datetime.date, tuple[tuple, float]] = {}
    for position in range(len(df)):
        row = df.iloc[position]
        if str(row[balance_k]).strip().upper() != "EUR":
            continue
        balance = _amount(row[amount_k])
        day = _date(row[date_k])
        if balance is None or day is None:
            continue
        # Higher in the file is later, hence -position: the top row wins at equal
        # time.
        key = (_time(row[time_k]) if time_k else "", -position)
        if day not in per_day or key > per_day[day][0]:
            per_day[day] = (key, balance)

    return [
        {"date": day.isoformat(), "balance": round(balance, 2)}
        for day, (_key, balance) in sorted(per_day.items())
    ]


def read_entries(path: str) -> list[dict]:
    """[{date, amount, description, key}]: every EUR change in the statement.

    Positive is money that came in. All changes, not only deposits and
    withdrawals: which row is what is only in DeGiro's own descriptions, and
    reading those would mean the app has to know DeGiro's texts. Pairing with a
    bank transaction happens on amount and date (categorization.relabel); a
    purchase has no counterpart at the bank and so stays unpaired by itself.
    """
    df = read_export(path)
    columns = [str(c).strip() for c in df.columns]
    df.columns = columns

    date_k, time_k = _column(columns, _DATE), _column(columns, _TIME)
    entry_k = _column(columns, ("Mutatie", "Change"))
    oms_k = _column(columns, ("Omschrijving", "Description"))
    if not date_k or not entry_k:
        return []
    position = columns.index(entry_k)
    if position + 1 >= len(columns):
        return []
    amount_k = columns[position + 1]

    balance_k = _column(columns, _BALANCE)
    balance_amount_k = (columns[columns.index(balance_k) + 1]
                      if balance_k and columns.index(balance_k) + 1 < len(columns) else None)

    def balance_of(row) -> float | None:
        if not balance_amount_k or str(row[balance_k]).strip().upper() != "EUR":
            return None
        return _amount(row[balance_amount_k])

    def moment(row) -> tuple:
        return (_date(row[date_k]), _time(row[time_k]) if time_k else "")

    def shifted(row, amount: float, following) -> bool:
        """Does the row right after this one restore the balance, without an amount
        of its own?

        Then this was not money going in or out but a shift within the broker:
        DeGiro passes a deposit on to a cash account at another bank (−X) and counts
        it in the balance again in the same minute (+X, without a change). Without
        this check that −X looked like a withdrawal, and got paired with money that
        came in from elsewhere that day. Recognised by the numbers only, not by the
        description.
        """
        if following is None or moment(following) != moment(row) or _amount(following[amount_k]) is not None:
            return False
        now, later = balance_of(row), balance_of(following)
        return now is not None and later is not None and abs((later - now) + amount) < 0.005

    # DeGiro puts the newest row on top; in time order it is the other way round.
    sort_order = list(range(len(df)))[::-1]

    off: list[dict] = []
    seen: dict[tuple, int] = {}
    for k, i in enumerate(sort_order):
        row = df.iloc[i]
        if str(row[entry_k]).strip().upper() != "EUR":
            continue
        amount, day = _amount(row[amount_k]), _date(row[date_k])
        if amount is None or day is None or amount == 0:
            continue
        following = df.iloc[sort_order[k + 1]] if k + 1 < len(sort_order) else None
        if shifted(row, amount, following):
            continue
        description = str(row[oms_k]).strip() if oms_k else ""
        time = _time(row[time_k]) if time_k else ""
        core = (day.isoformat(), time, round(amount, 2), description)
        seen[core] = seen.get(core, 0) + 1
        off.append({
            "date": day.isoformat(),
            "amount": round(amount, 2),
            "description": description,
            "key": "|".join(str(x) for x in core) + f"|{seen[core]}",
        })
    return off


def import_file(conn: sqlite3.Connection, path: str) -> dict:
    """Reads the cash balance from an account statement and stores it.

    Creates the account "DeGiro cash" the first time; after that only balances
    are updated, and a second import of the same file changes nothing
    (set_balance replaces a measurement on the same day). If there is no EUR
    balance in the file, no account is created either: no number is not zero.
    """
    days = read(path)
    if not days:
        return {"account": None, "days": 0}

    account = next(
        (r for r in accounts.load_accounts(conn)
         if r["provider"] == PROVIDER and r["kind"] == "broker"),
        None,
    )
    if account is None:
        account_id = accounts.make_bank_account(conn, kind="broker", provider=PROVIDER, name=NAME)
        account = accounts.load_account(conn, account_id)

    for day in days:
        accounts.set_balance(conn, account["id"], day["date"], day["balance"], source="sync")

    # The movements too, so a withdrawal that arrives at your bank is recognised
    # as a transfer between your own accounts.
    entries = accounts.save_entries(conn, account["id"], read_entries(path))

    return {"account": account, "days": len(days), "entries": entries}
