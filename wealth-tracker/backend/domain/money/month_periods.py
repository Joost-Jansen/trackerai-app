"""
month_periods.py — where a month starts: on the 1st, or when your salary comes in.

For someone paid on the 21st a calendar month is an odd unit: October's rent
goes out on 1 October, but the salary that pays for it came in on
21 September. With your salary as the reference point a month runs from salary
to salary, and everything you pay from one salary falls in the same month.

Recognising, not entering:

  * **The salary days** are the credits in the salary category (by default
    "Salaris"). One counts per calendar month: the one closest to your usual
    salary day. Holiday pay or a refunded expense claim in the same category
    therefore does not move the reference point.
  * **The usual salary day** is the day it came in most often. If that falls
    in a weekend or on a holiday, the app looks in your history whether your
    employer then pays earlier or later. There is no day in the code: someone
    paid on the 25th gets the 25th.
  * **A month without salary** — the current one, or a gap in your history —
    gets a predicted date with that same rule.

A month is named after the calendar month in which it starts: the month that
starts on 21 September is called September. The keys thus stay "YYYY-MM", and
no screen needs to know which layout was chosen to show a month.

As elsewhere every function takes an explicit `conn`.
"""

import bisect
import calendar
import sqlite3
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache

from domain import database
from domain.i18n import tr

MODI = ("calendar", "salary")
DEFAULT_CATEGORY = "Salaris"

_MODE, _DAY, _CATEGORY = "month_periods", "salary_day", "salary_category"

# A credit in the salary category smaller than this share of a usual salary
# payment is not salary but, for example, an expense claim.
MIN_PART_OF_SALARY = 0.25
# Further than this from the usual salary day a payment is not a reference
# point: one salary on the 3rd would otherwise make a month of two weeks and one
# of six.
MAX_DEVIATION_DAYS = 7
# How many months after today there are still boundaries: enough to give the
# current month an end.
MONTHS_AHEAD = 2


def today() -> date:
    return date.today()


# ---------------------------------------------------------------------------
# Working days
# ---------------------------------------------------------------------------

def _easter(year: int) -> date:
    """Easter Sunday, Gregorian (the anonymous algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month, day = divmod(h + l_ - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=None)
def holidays(year: int) -> frozenset[date]:
    """Days on which salary is usually not paid.

    The Dutch public holidays plus the days on which European payments (TARGET2)
    stand still: Good Friday and 1 May. That is an approximation; what actually
    came in always comes first, this is only for the prediction.
    """
    p = _easter(year)
    kings_day = date(year, 4, 27)
    if kings_day.weekday() == 6:
        kings_day = date(year, 4, 26)
    days = {
        date(year, 1, 1), p - timedelta(days=2), p + timedelta(days=1), kings_day, date(year, 5, 1),
        p + timedelta(days=39), p + timedelta(days=50), date(year, 12, 25), date(year, 12, 26),
    }
    if year % 5 == 0:
        days.add(date(year, 5, 5))   # Liberation Day, a day off once every five years
    return frozenset(days)


def workday(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def _nominal(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def predict(year: int, month: int, day: int, shift: str = "earlier") -> date:
    """The salary date in a month: `day`, or the working day before or after it.

    Stays within the month. If the shift would run out of the month, the other way
    round: two reference points in one month do not exist.
    """
    d = _nominal(year, month, day)
    step = -1 if shift == "earlier" else 1
    for direction in (step, -step):
        k = d
        while not workday(k) and k.month == month:
            k += timedelta(days=direction)
        if k.month == month:
            return k
    return d


# ---------------------------------------------------------------------------
# Recognising
# ---------------------------------------------------------------------------

@dataclass
class Recognised:
    day: int
    shift: str
    payments: dict[str, date] = field(default_factory=dict)   # "YYYY-MM" -> salarisdag


def recognise(conn: sqlite3.Connection, category: str, day_hint: int | None = None) -> Recognised | None:
    """The salary days from your transactions, or None if there is no salary."""
    rows = conn.execute(
        """
        SELECT date, -SUM(amount) AS amount FROM bank_transactions_typed
         WHERE category_effective = ?
         GROUP BY date HAVING SUM(amount) < 0
         ORDER BY date
        """,
        (category,),
    ).fetchall()
    if not rows:
        return None

    per_month: dict[str, list[tuple[date, float]]] = defaultdict(list)
    for r in rows:
        d = date.fromisoformat(r["date"])
        per_month[d.strftime("%Y-%m")].append((d, r["amount"]))

    largest = [max(items, key=lambda x: x[1]) for items in per_month.values()]
    threshold = statistics.median(b for _, b in largest) * MIN_PART_OF_SALARY
    typical = day_hint or statistics.median_low(d.day for d, _ in largest)

    chosen: dict[str, date] = {}
    for month, items in per_month.items():
        candidates = [(d, b) for d, b in items if b >= threshold]
        if candidates:
            chosen[month] = min(candidates, key=lambda x: (abs(x[0].day - typical), -x[1]))[0]
    if not chosen:
        return None

    # The salary day and the shift that together explain the most payments. Not
    # simply the day that occurs most often: someone paid on the 21st and on Friday
    # when it is a weekend has the 19th or 20th just as often as the 21st. "The
    # 21st, otherwise the working day before" explains them all.
    dates = list(chosen.values())
    exact = Counter(d.day for d in dates)

    def score(day: int, shift: str) -> tuple:
        explained = sum(predict(d.year, d.month, day, shift) == d for d in dates)
        return explained, exact[day], -abs(day - typical), shift == "earlier"

    days = [day_hint] if day_hint else range(1, 32)
    day, shift = max(((d, v) for d in days for v in ("earlier", "later")), key=lambda x: score(*x))
    return Recognised(day=day, shift=shift, payments=chosen)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def settings(conn: sqlite3.Connection) -> dict:
    mode = database.load_setting(conn, _MODE, "calendar")
    day = database.load_setting(conn, _DAY)
    return {
        "mode": mode if mode in MODI else "calendar",
        "day": int(day) if day else None,
        "category": database.load_setting(conn, _CATEGORY, DEFAULT_CATEGORY),
    }


def put(conn: sqlite3.Connection, **fields) -> None:
    """Updates only the given fields: `mode`, `day` (None = recognise) and
    `category`.
    """
    if "mode" in fields:
        if fields["mode"] not in MODI:
            raise ValueError(tr("Choose from: {0}.", ', '.join(MODI)))
        database.save_setting(conn, _MODE, fields["mode"])
    if "day" in fields:
        day = fields["day"]
        if day in (None, "", 0):
            conn.execute("DELETE FROM settings WHERE key = ?", (_DAY,))
            conn.commit()
        else:
            day = int(day)
            if not 1 <= day <= 31:
                raise ValueError(tr("A salary day is between 1 and 31."))
            database.save_setting(conn, _DAY, str(day))
    if "category" in fields:
        name = (fields["category"] or "").strip() or DEFAULT_CATEGORY
        if not conn.execute("SELECT 1 FROM categories WHERE name = ?", (name,)).fetchone():
            raise ValueError(tr("'{0}' is not an existing category.", name))
        database.save_setting(conn, _CATEGORY, name)


# ---------------------------------------------------------------------------
# The layout
# ---------------------------------------------------------------------------

@dataclass
class Layout:
    """The month boundaries and how to place a date in a month.

    `mode` is what is actually used: "salary" without a single recognised or set
    salary day falls back to "calendar".
    """
    mode: str
    boundaries: list[str]

    def key(self, date: str) -> str:
        """The month in which `date` falls, as "YYYY-MM" of the month in which it starts."""
        if self.mode == "calendar":
            return date[:7]
        i = bisect.bisect_right(self.boundaries, date)
        return self.boundaries[i - 1][:7] if i else date[:7]

    def period(self, key: str) -> tuple[str, str]:
        """(first, last day) of the month with this key."""
        if self.mode == "salary":
            for i, g in enumerate(self.boundaries[:-1]):
                if g[:7] == key:
                    return g, (date.fromisoformat(self.boundaries[i + 1]) - timedelta(days=1)).isoformat()
        year, month = (int(x) for x in key.split("-"))
        return date(year, month, 1).isoformat(), date(year, month, calendar.monthrange(year, month)[1]).isoformat()

    def start_of(self, date: str) -> str:
        return self.period(self.key(date))[0]


def _months(start: date, end: date) -> list[tuple[int, int]]:
    off, j, m = [], start.year, start.month
    while (j, m) <= (end.year, end.month):
        off.append((j, m))
        j, m = (j + 1, 1) if m == 12 else (j, m + 1)
    return off


def _range(conn: sqlite3.Connection, present_day: date) -> tuple[date, date]:
    first = conn.execute(
        "SELECT MIN(d) FROM (SELECT MIN(date) AS d FROM bank_transactions "
        "UNION ALL SELECT MIN(date) FROM account_balances)"
    ).fetchone()[0]
    begin = min(date.fromisoformat(first), present_day) if first else present_day
    begin = (begin.replace(day=1) - timedelta(days=1)).replace(day=1)   # a month of margin before it
    final = present_day
    for _ in range(MONTHS_AHEAD):
        final = (final.replace(day=28) + timedelta(days=4)).replace(day=1)
    return begin, final


def _determine(conn: sqlite3.Connection, present_day: date) -> tuple[dict, Recognised | None, int | None, str]:
    inst = settings(conn)
    recognised = recognise(conn, inst["category"], inst["day"]) if inst["mode"] == "salary" else None
    day = inst["day"] or (recognised.day if recognised else None)
    shift = recognised.shift if recognised else "earlier"
    return inst, recognised, day, shift


def layout(conn: sqlite3.Connection, *, present_day: date | None = None) -> Layout:
    present_day = present_day or today()
    inst, recognised, day, shift = _determine(conn, present_day)
    begin, final = _range(conn, present_day)
    months = _months(begin, final)
    if inst["mode"] != "salary" or day is None:
        return Layout("calendar", [date(j, m, 1).isoformat() for j, m in months])

    boundaries = []
    for j, m in months:
        predicted = predict(j, m, day, shift)
        real = recognised.payments.get(f"{j:04d}-{m:02d}") if recognised else None
        if real and abs((real - predicted).days) <= MAX_DEVIATION_DAYS:
            boundaries.append(real.isoformat())
        else:
            boundaries.append(predicted.isoformat())
    return Layout("salary", boundaries)


def details(conn: sqlite3.Connection, *, present_day: date | None = None) -> dict:
    """What the screens show: the choice, what was recognised and the boundaries themselves."""
    present_day = present_day or today()
    inst, recognised, day, shift = _determine(conn, present_day)
    ind = layout(conn, present_day=present_day)
    begin, final = ind.period(ind.key(present_day.isoformat()))
    return {
        "mode": inst["mode"],
        "active": ind.mode,
        "category": inst["category"],
        "day": day,
        "day_configured": inst["day"],
        "shift": shift,
        "recognised": {
            "day": recognised.day,
            "count": len(recognised.payments),
            "last": max(recognised.payments.values()).isoformat(),
        } if recognised else None,
        "boundaries": ind.boundaries,
        "current": {"start": begin, "end": final},
    }
