"""
What the Accounts page wants to know about an account.

The rules live in domain/money/accounts.py; this only merges what an
overview needs and what you do not want to fetch per account separately:
the account itself plus its last known balance.

That last balance is explicitly the *last measurement*, not today's balance.
There is no difference as long as you keep up, and once you have not looked
for a while "€1,000, measured on 31 January" is a more honest answer than
"€1,000" alone. Hence `balance_date` is always included.

One exception: a debt with interest and repayment (debt_schedule.py). It runs
on by itself, and its last balance is the state at the last reference point,
with source "schedule".

`since_period_start` is how much the balance changed since the start of the
current month — the 1st, or your last salary (month_periods.py).
"""

import sqlite3
from datetime import date, timedelta

from domain.money import accounts, debt_schedule, month_periods, net_worth


def today() -> str:
    return date.today().isoformat()


def _since(series: list[dict], begin: str) -> float | None:
    """Change from the start (the state at the end of the day before) to today."""
    day_for_it = (date.fromisoformat(begin) - timedelta(days=1)).isoformat()
    if not series or series[0]["date"] > day_for_it:
        return None
    return round(accounts.value_on(series, today()) - accounts.value_on(series, day_for_it), 2)


def _with_balance(conn: sqlite3.Connection, account: dict, period_start: str) -> dict:
    last = accounts.last_balance(conn, account["id"])
    schedule = debt_schedule.load(conn, account["id"]) if account["kind"] == "debt" else None
    series = accounts.balances_for_series(conn, account["id"]) if last else []
    # If the balance runs on by itself after the last measurement — with interest
    # and repayment, or with transfers from your other accounts — that is the state.
    if series and (schedule or (series[-1]["source"] == "transfer" and series[-1]["date"] > last["date"])):
        last = series[-1]
    return {
        **account,
        "balance": last["balance"] if last else None,
        "balance_date": last["date"] if last else None,
        "balance_source": last["source"] if last else None,
        "stack": net_worth.stack_of(account["kind"]),
        "schedule": schedule,
        "period_start": period_start,
        "since_period_start": _since(series, period_start),
    }


def _period_start(conn: sqlite3.Connection) -> str:
    return month_periods.layout(conn).start_of(today())


def overview(conn: sqlite3.Connection, *, only_active: bool = False) -> list[dict]:
    """All accounts, each with its last known balance."""
    begin = _period_start(conn)
    return [_with_balance(conn, r, begin) for r in accounts.load_accounts(conn, only_active=only_active)]


def one(conn: sqlite3.Connection, account_id: int) -> dict | None:
    account = accounts.load_account(conn, account_id)
    return _with_balance(conn, account, _period_start(conn)) if account else None
