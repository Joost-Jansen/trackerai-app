"""
fixed_costs.py — what comes back every month.

Rent, subscriptions, insurance, your phone: debits that are roughly the same
every month. Together they are what you spend before you choose anything, and
a new subscription does not stand out among a hundred grocery runs. This finds
them in your transactions, without you having to point anything out.

A counterparty is a fixed cost if it:

  * occurs in at least MIN_MONTHS different months, at most twice per month —
    the supermarket occurs every month, but ten times;
  * debits roughly monthly (the median interval is a month);
  * asks roughly the same amount each time.

Nothing per shop or per bank: the pattern is the proof.
"""

import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from domain.i18n import tr

MIN_MONTHS = 3
# How much the amount may vary: the median deviation, as a share of the usual
# amount. An energy bill that shifts a bit per season may; a web shop that asks
# 12 euros one time and 80 the next may not.
MAX_ALLOCATION = 0.25
# Interval in days that counts as "monthly".
MONTHLY = (20, 40)
LOOK_BACK_DAYS = 400
# No debit for this long: stopped (or cancelled).
STOPPED_AFTER_DAYS = 45
# First seen within this many days: new. Generous, because the app only
# recognises a new fixed cost after MIN_MONTHS times — after about three months.
NEW_WITHIN_DAYS = 120


def _key(name: str | None) -> str:
    """The name without digits and double spaces: a card or invoice number otherwise
    turns the same debit into a different counterparty every month.
    """
    return re.sub(r"\s+", " ", re.sub(r"\d+", "", (name or "").upper())).strip()


def choices(conn: sqlite3.Connection) -> dict[str, bool]:
    """{key: is_fixed}: what you indicated yourself. Always wins over the pattern."""
    return {r["key"]: bool(r["is_fixed"]) for r in conn.execute("SELECT key, is_fixed FROM fixed_cost_choices")}


def set_choice(conn: sqlite3.Connection, name: str, is_fixed: bool | None) -> None:
    """A counterparty as a fixed cost (True) or *not* (False); None leaves it to
    the detection again. On the key of the name, so a card number changes
    nothing about it.
    """
    key = _key(name)
    if not key:
        raise ValueError(tr("No name to recognise by."))
    if is_fixed is None:
        conn.execute("DELETE FROM fixed_cost_choices WHERE key = ?", (key,))
    else:
        conn.execute(
            "INSERT INTO fixed_cost_choices (key, is_fixed) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET is_fixed = excluded.is_fixed",
            (key, int(is_fixed)),
        )
    conn.commit()


def _per_name(conn: sqlite3.Connection, present_day: date,
              account_ids: set[int] | None) -> dict[str, list[dict]]:
    from_date = (present_day - timedelta(days=LOOK_BACK_DAYS)).isoformat()
    per_name: dict[str, list[dict]] = defaultdict(list)
    for r in conn.execute(
        """
        SELECT date, amount, name, category_effective AS category, group_name, account_id
          FROM bank_transactions_typed
         WHERE type_effective = 'EXPENSE' AND amount > 0 AND date >= ?
        """,
        (from_date,),
    ):
        if account_ids and r["account_id"] not in account_ids:
            continue
        key = _key(r["name"])
        if key:
            per_name[key].append(dict(r))
    return per_name


def _according_to_pattern(items: list[dict]) -> bool:
    """Roughly monthly, roughly the same amount, in enough months."""
    per_month = Counter(r["date"][:7] for r in items)
    if len(per_month) < MIN_MONTHS or max(per_month.values()) > 2:
        return False
    amounts = [r["amount"] for r in items]
    plain = statistics.median(amounts)
    if not plain or statistics.median(abs(b - plain) for b in amounts) / plain > MAX_ALLOCATION:
        return False
    dates = sorted(date.fromisoformat(r["date"]) for r in items)
    pozen = [(b - a).days for a, b in zip(dates, dates[1:])]
    return bool(pozen) and MONTHLY[0] <= statistics.median(pozen) <= MONTHLY[1]


def _summary(key: str, items: list[dict], present_day: date, layout) -> dict:
    dates = sorted(date.fromisoformat(r["date"]) for r in items)
    # Added up per month: someone who pays a part twice a month pays the sum per
    # month. With once a month this is simply the amount per time.
    per_month: dict[str, float] = defaultdict(float)
    for r in items:
        per_month[r["date"][:7]] += r["amount"]
    return {
        "key": key,
        "name": Counter(r["name"] for r in items).most_common(1)[0][0],
        "category": Counter(r["category"] for r in items).most_common(1)[0][0],
        "group_name": Counter(r["group_name"] for r in items).most_common(1)[0][0],
        "amount": round(statistics.median(per_month.values()), 2),
        "count": len(items),
        "months": len(per_month),
        "first": dates[0].isoformat(),
        "last": dates[-1].isoformat(),
        "is_new": (present_day - dates[0]).days <= NEW_WITHIN_DAYS,
        "stopped": (present_day - dates[-1]).days > STOPPED_AFTER_DAYS,
        **({"position": int(statistics.median(
            (d - date.fromisoformat(layout.start_of(d.isoformat()))).days for d in dates
        ))} if layout is not None else {}),
    }


def find(conn: sqlite3.Connection, *, present_day: date | None = None,
         account_ids: set[int] | None = None, layout=None) -> list[dict]:
    """The fixed costs of the past year, largest first.

    [{key, name, category, group_name, amount, count, months, first, last,
      is_new, stopped, manual}]
    `amount` is the usual amount per month (the median). `manual` is True if you
    marked it as a fixed cost yourself; what you marked as "not a fixed cost" is
    never in it, however regular it is.

    With a `layout` (month_periods.Layout) also `position`: on which day of the
    month it usually goes out, in days after the first (0 = the first day). With
    salary months that counts from your salary: rent on the 1st with salary on
    the 21st is day 10 or 11.
    """
    present_day = present_day or date.today()
    chosen = choices(conn)
    off = []
    for key, items in _per_name(conn, present_day, account_ids).items():
        choice = chosen.get(key)
        if choice is False or (choice is None and not _according_to_pattern(items)):
            continue
        off.append({**_summary(key, items, present_day, layout), "manual": choice is True})
    return sorted(off, key=lambda v: (v["stopped"], -v["amount"]))


# This often per month on average it is more likely groceries than a fixed
# cost: those are not among the suggestions.
CANDIDATE_MAX_PER_MONTH = 3
CANDIDATES = 25


def admin(conn: sqlite3.Connection, *, present_day: date | None = None) -> dict:
    """What the Fixed costs screen shows.

    {is_fixed: [...find], candidates: [...], excluded: [...]}

    `candidates` come back in at least two months but do not (fully) fit the
    pattern — a varying amount, a varying day — and have not been turned off by
    you. `excluded` is what you marked as "not a fixed cost".
    """
    present_day = present_day or date.today()
    chosen = choices(conn)
    per_name = _per_name(conn, present_day, None)
    is_fixed = find(conn, present_day=present_day)
    already = {v["key"] for v in is_fixed}

    candidates, excluded = [], []
    for key, items in per_name.items():
        if chosen.get(key) is False:
            excluded.append(_summary(key, items, present_day, None))
            continue
        if key in already:
            continue
        s = _summary(key, items, present_day, None)
        if s["months"] >= 2 and s["count"] / s["months"] <= CANDIDATE_MAX_PER_MONTH and not s["stopped"]:
            candidates.append(s)
    candidates.sort(key=lambda v: (-v["months"], -v["amount"]))
    # Turned off without transactions in the window: show it anyway, otherwise you
    # can no longer undo it.
    for key, v in chosen.items():
        if v is False and key not in per_name:
            excluded.append({"key": key, "name": key.title(), "category": None, "group_name": None,
                                "amount": 0.0, "count": 0, "months": 0, "first": None, "last": None,
                                "is_new": False, "stopped": True})
    return {
        "is_fixed": is_fixed,
        "candidates": candidates[:CANDIDATES],
        "excluded": sorted(excluded, key=lambda v: v["name"]),
    }
