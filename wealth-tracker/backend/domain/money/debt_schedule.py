"""
debt_schedule.py — interest and required repayment that run on by themselves.

A student debt changes the same way every month: interest is added and the
required repayment comes off. Entering that by hand every month is work nobody
keeps up, and a debt that stands still for months makes your net worth look
better than it is.

Per debt account you record how much interest (per year) and how much
repayment (per month) applies, and from when. At every reference point — the
1st, or the day your salary comes in (month_periods.py) — the app calculates
one month on:

    new = old + old × interest / 12 − repayment

A balance you enter yourself stays the truth. It is the new starting point:
someone who repays extra once enters that day's balance, and from the next
reference point the schedule runs on from that amount. The calculated points
are not stored but calculated every time, so a different interest rate or a
different month layout takes effect everywhere at once.
"""

import re
import sqlite3
from datetime import date

from domain.money import month_periods
from domain.i18n import tr

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def today() -> str:
    return date.today().isoformat()


def load(conn: sqlite3.Connection, account_id: int) -> dict | None:
    row = conn.execute("SELECT interest, repayment, from_date FROM debt_schedules WHERE account_id = ?",
                       (account_id,)).fetchone()
    return dict(row) if row else None


def put(conn: sqlite3.Connection, account_id: int, *, interest: float | None, repayment: float | None,
        from_date: str) -> None:
    """Records the schedule. Without interest *and* repayment it is removed."""
    if not interest and not repayment:
        remove(conn, account_id)
        return
    interest, repayment = float(interest or 0), float(repayment or 0)
    if not 0 <= interest <= 100:
        raise ValueError(tr("Interest is a percentage per year, between 0 and 100."))
    if repayment < 0:
        raise ValueError(tr("A repayment is a positive amount per month."))
    if not isinstance(from_date, str) or not _ISO_DATE.match(from_date):
        raise ValueError(tr("From must be a date (YYYY-MM-DD), got: {0}", repr(from_date)))
    date.fromisoformat(from_date)
    conn.execute(
        """
        INSERT INTO debt_schedules (account_id, interest, repayment, from_date) VALUES (?, ?, ?, ?)
        ON CONFLICT(account_id) DO UPDATE SET
            interest = excluded.interest, repayment = excluded.repayment, from_date = excluded.from_date
        """,
        (account_id, interest, round(repayment, 2), from_date),
    )
    conn.commit()


def remove(conn: sqlite3.Connection, account_id: int) -> None:
    conn.execute("DELETE FROM debt_schedules WHERE account_id = ?", (account_id,))
    conn.commit()


def points(conn: sqlite3.Connection, account_id: int, measurements: list[dict], *,
           end: str | None = None) -> list[dict]:
    """The measurements plus a calculated point at every reference point *after* a
    measurement.

    Between two measurements the schedule runs from the first; the second then
    replaces what the schedule made of it. A reference point on the day of a
    measurement does not count: what you entered that day is the state after
    everything of that day.

    Calculated points carry source "schedule", plus that month's interest and
    repayment. A debt that is at zero stays there.
    """
    schedule = load(conn, account_id)
    if not schedule or not measurements:
        return measurements
    end = end or today()
    boundaries = [g for g in month_periods.layout(conn).boundaries if schedule["from_date"] <= g <= end]
    monthly_interest = schedule["interest"] / 100 / 12

    off: list[dict] = []
    for i, measurement in enumerate(measurements):
        off.append(measurement)
        following = measurements[i + 1]["date"] if i + 1 < len(measurements) else None
        stand = abs(measurement["balance"])
        for g in boundaries:
            if g <= measurement["date"] or (following and g >= following):
                continue
            if stand <= 0:
                break
            interest = round(stand * monthly_interest, 2)
            repayment = round(min(schedule["repayment"], stand + interest), 2)
            stand = round(stand + interest - repayment, 2)
            off.append({"date": g, "balance": -stand, "source": "schedule", "interest": interest, "repayment": repayment})
    return off
