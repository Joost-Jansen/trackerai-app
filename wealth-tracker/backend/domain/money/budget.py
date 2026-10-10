"""
budget.py — what you want to spend per group per month, next to what it became.

The heart of the old spreadsheet was the month overview: per month and per
group the actual amount, the budget, the difference and how much of the
budget is used. This is that overview.

Three choices:

  * **Per group, not per category.** Planning forty categories is work nobody
    keeps up; ten groups is. A budget on "Boodschappen" covers the
    supermarket, the drugstore and the market together.
  * **The median as a suggestion.** Making up a first budget is hard; what you
    spent in a normal month is not. The median and not the mean, so one
    holiday or one new bank does not inflate the suggestion. Only over
    complete months: a half month next to whole ones reads as a frugal month.
  * **No budget is not zero.** A group without a budget has no difference and
    no percentage; otherwise everything you did not plan is in the red.

What counts as spending per group comes from
net_worth.spending_per_month_per_group, the same source as the month chart,
so two screens never give two answers.
"""

import sqlite3
import statistics
from collections import defaultdict
from datetime import date, timedelta

from domain.money import month_periods
from domain.money import fixed_costs
from domain.money import net_worth
from domain.i18n import tr

# Over how many complete months the median runs: a year, so a season (the
# insurance in January, the holiday in summer) is in it once.
MEDIAN_MONTHS = 12


class UnknownGroup(ValueError):
    pass


def spending_groups(conn: sqlite3.Connection) -> list[str]:
    """The groups with at least one spending category, in the order of the taxonomy."""
    rows = conn.execute("""
        SELECT group_name FROM categories
         WHERE type = 'EXPENSE'
         GROUP BY group_name
         ORDER BY MIN(sort_order), group_name
    """).fetchall()
    return [r["group_name"] for r in rows]


def load(conn: sqlite3.Connection) -> dict[str, float]:
    return {r["group_name"]: r["amount"] for r in conn.execute("SELECT group_name, amount FROM budgets")}


def put(conn: sqlite3.Connection, group_name: str, amount: float | None) -> None:
    """Sets the monthly budget of a group. None or 0 removes it."""
    if group_name not in spending_groups(conn):
        raise UnknownGroup(tr("'{0}' is not a group with expense categories.", group_name))
    if amount is None or amount == 0:
        conn.execute("DELETE FROM budgets WHERE group_name = ?", (group_name,))
    elif amount < 0:
        raise ValueError(tr("A budget is an amount you want to spend, so positive."))
    else:
        conn.execute(
            "INSERT INTO budgets (group_name, amount) VALUES (?, ?) "
            "ON CONFLICT(group_name) DO UPDATE SET amount = excluded.amount",
            (group_name, round(float(amount), 2)),
        )
    conn.commit()


def refunded_per_month_per_group(conn: sqlite3.Connection,
                                     layout: "month_periods.Layout") -> dict[str, dict[str, float]]:
    """{month: {group: amount}}: what came in on a spending category.

    A Tikkie for drinks or a return to a web shop is on the category of the
    expense and counts against it there: `actual` is net. This is the part that
    came off, as a positive amount, so a screen can show why a group comes out
    lower — or at zero.
    """
    outcome: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in conn.execute("""
        SELECT date, COALESCE(group_name, ?) AS group_name, SUM(amount) AS summed
        FROM bank_transactions_typed
        WHERE type_effective = 'EXPENSE' AND amount < 0
        GROUP BY 1, 2
    """, (net_worth.MISC,)):
        outcome[layout.key(row["date"])][row["group_name"]] -= row["summed"]
    return outcome


def expected_until_today(conn: sqlite3.Connection, layout: "month_periods.Layout",
                         present_day: date, budgets: dict[str, float]) -> dict[str, float]:
    """{group: amount}: what you expect to have spent in the current month up to and
    including today, for every group with a budget.

    Spread evenly over the month is not right for fixed costs: rent goes in one
    go, on its own day. So per group:

      * the fixed costs (fixed_costs.py) that already went out this month, or
        whose usual day has already passed: their whole amount;
      * the rest of the budget: pro rata to the part of the month that is over.

    That way the rent on day 3 does not show as "faster than planned", and a
    group without fixed costs simply runs at the pace of the calendar.
    """
    today = present_day.isoformat()
    start, end = layout.period(layout.key(today))
    length = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    day = min(length - 1, (present_day - date.fromisoformat(start)).days)   # 0 = first day
    pace = (day + 1) / length
    is_fixed = [v for v in fixed_costs.find(conn, present_day=present_day, layout=layout) if not v["stopped"]]

    off = {}
    for group_name, budget in budgets.items():
        own = [v for v in is_fixed if v["group_name"] == group_name]
        is_fixed_total = sum(v["amount"] for v in own)
        already = sum(v["amount"] for v in own if v["last"] >= start or v["position"] <= day)
        off[group_name] = round(already + max(0.0, budget - is_fixed_total) * pace, 2)
    return off


def overview(conn: sqlite3.Connection, *, months: int = 13, present_day: date | None = None) -> dict:
    """The last `months` months: per group actual, budget and median.

    {
      "months":   ["2025-09", ...],            ascending
      "complete": {"2025-09": true, ...},
      "groups":   [{"group_name", "budget", "median", "actual": {month: amount},
                    "back": {month: amount}}],
      "total":    {"budget", "actual": {month: amount}},
      "current":  "2026-09",                   the current month
    }

    Groups with a budget also get `expected`: what you expect to have spent in
    the current month up to today (see expected_until_today).

    Groups with a budget or with spending in the months shown are included; a
    group that occurs nowhere is not. `budget` is None without a budget, `median`
    None without a complete month to base it on.

    The current month is included even if nothing has been spent in it yet, as
    long as your data runs into the month before: on the first day of a new
    (salary) month that is the month you are looking at, not the previous one.
    """
    layout = month_periods.layout(conn, present_day=present_day)
    per_month = net_worth.spending_per_month_per_group(conn, layout)
    complete = {m["month"]: m["complete"] for m in net_worth.per_month(conn)}
    all_months = sorted(per_month)
    today = (present_day or month_periods.today()).isoformat()
    current = layout.key(today)
    begin = layout.period(current)[0]
    previous = layout.key((date.fromisoformat(begin) - timedelta(days=1)).isoformat())
    if all_months and all_months[-1] == previous:
        all_months.append(current)
    shown = all_months[-months:] if months > 0 else all_months
    back = refunded_per_month_per_group(conn, layout)
    base = [m for m in sorted(per_month) if complete.get(m)][-MEDIAN_MONTHS:]
    budgets = load(conn)
    expected = expected_until_today(conn, layout, present_day or month_periods.today(), budgets) if budgets else {}

    sort_order = spending_groups(conn)
    present = set(budgets) | {g for m in shown for g in per_month.get(m, {})}
    groups = [g for g in sort_order if g in present] + sorted(present - set(sort_order))

    rows = []
    for group_name in groups:
        # A complete month without spending in this group counts as zero: that too is
        # a normal month.
        values = [per_month.get(m, {}).get(group_name, 0.0) for m in base]
        rows.append({
            "group_name": group_name,
            "budget": budgets.get(group_name),
            "median": round(statistics.median(values), 2) if values else None,
            "actual": {m: round(per_month.get(m, {}).get(group_name, 0.0), 2) for m in shown},
            "back": {m: round(back[m][group_name], 2) for m in shown if back.get(m, {}).get(group_name)},
            "expected": expected.get(group_name),
        })

    return {
        "months": shown,
        "complete": {m: bool(complete.get(m)) for m in shown},
        "groups": rows,
        "total": {
            "budget": round(sum(budgets.values()), 2) if budgets else None,
            "actual": {m: round(sum(per_month.get(m, {}).values()), 2) for m in shown},
        },
        "current": current,
    }
