"""
net_worth.py — investments, bank and debt together.

The portfolio knows what your holdings are worth and moves with the market
every day. Your bank balance you only know on the days you looked. Net worth
is the sum of the two, and the whole difficulty lies in that difference in
pace.

The series runs per calendar day, from the earliest data of any source to the
latest available data. Every source counts every day according to
accounts.value_on: zero before its first data, a straight line between two
manual measurements, flat between balances from an import, and the last
balance after that. On a day without a closing price the portfolio stands at
the previous one.

Per calendar day and not only on measurement days: then the time axis really
is a time axis, and a year of monthly measurements is not squeezed into twelve
points next to a year of daily prices.

Three stacks, as in the old bookkeeping:

    investments   the portfolio from this app, plus accounts of kind
                  `broker`: the cash balance at DeGiro (degiro_cash.py) and a
                  broker that is not tracked per holding here, like Coinbase
    bank          `bank`, `cash` and `manual`
    debt          `debt`, always negative (accounts.set_balance enforces that)

    net = investments + bank + debt

So the portfolio is *in* net worth, not next to it. Every point also carries
it separately (`portfolio` and `investments_external`), so the page can show
that it really is in there and how large it is.

The portfolio value is the *market value* of your holdings, not value plus
dividend. Dividend paid out lands on the cash account at DeGiro and counts
there as "DeGiro cash"; if you withdraw it, it counts on your bank account.
Adding it once more would count every euro of dividend twice.
"""

import sqlite3
from collections import defaultdict
from datetime import date

from domain.i18n import tr
from domain.money import accounts, month_periods

# Which kind of account ends up on which stack.
INVESTMENT_KINDS = ("broker",)
BANK_KINDS = ("bank", "cash", "manual")
DEBT_KINDS = ("debt",)

# Below this monthly income the savings rate is not calculated. Divide by a few
# tenners and out comes a percentage that means nothing — a month in which you
# received 20 euros and spent 100 is not "-400% saved", it is a month in which
# your salary came in elsewhere. Leaving it out is then more honest than a
# number. Taken over from the old dashboard builder.
MINIMUM_INCOME_FOR_QUOTE = 500.0

# Below this starting value no growth percentage, only the amount. A line that
# starts at a few cents otherwise gives a percentage that is true and says
# nothing.
MINIMUM_BASE_FOR_PERCENT = 1000.0

# How many groups get their own colour in the month chart; the rest merges
# under "Overig". Eight is the limit from the old dashboard builder, and for the
# same reason: beyond eight or so colours a person can no longer tell them
# apart, certainly not in a stacked bar. Whoever wants to see the smallest
# groups looks in the transaction list.
MAX_GROUPS = 7
MISC = "Overig"


def _balances_per_account(conn: sqlite3.Connection) -> dict[int, list[dict]]:
    per_account: dict[int, list[dict]] = defaultdict(list)
    for balance in accounts.load_balances(conn):
        per_account[balance["account_id"]].append(balance)
    return per_account


def _money_from_others(conn: sqlite3.Connection, account_ids: set[int]) -> tuple[list[str], list[float]]:
    """(dates, running sum) of the transactions in "Niet meetellen".

    Only on accounts that count in net worth: an account without a balance does
    not take part, and so neither do its transactions.

    The running sum in the database's sign convention (spending positive): someone
    who received 2,000 euros from friends stands at −2,000. series() counts only
    the negative part of it, as debt: see there for why.
    """
    from domain.money import categorization  # here and not at the top: categorization leans on modules that use net_worth

    if not account_ids:
        return [], []
    places = ",".join("?" * len(account_ids))
    rows = conn.execute(
        f"""
        SELECT date, SUM(amount) AS summed FROM bank_transactions_typed
         WHERE category_effective = ? AND account_id IN ({places})
         GROUP BY date ORDER BY date
        """,
        (categorization.EXCLUDE, *sorted(account_ids)),
    ).fetchall()
    dates, running, summed = [], [], 0.0
    for r in rows:
        summed += r["summed"]
        dates.append(r["date"])
        running.append(summed)
    return dates, running


def stack_of(kind: str) -> str | None:
    """Which stack an account of this kind falls on: investments, bank or debt.

    Public because the Accounts page shows the same split; it belongs in one place
    and not once more in the frontend.
    """
    if kind in INVESTMENT_KINDS:
        return "investments"
    if kind in BANK_KINDS:
        return "bank"
    if kind in DEBT_KINDS:
        return "debt"
    return None


def series(conn: sqlite3.Connection, investment_points: list[dict]) -> dict:
    """The net worth series: one point per calendar day.

    `investment_points` is what dashboard_service.get_value_history returns:
    [{d, invested, value, value_divs}] per calendar day since the first purchase.

    Returns:
        points        [{d, portfolio, investments_external, investments, bank,
                        debt, net, measured}]
        from_date     the first day
        measurements  how many days have a real balance measurement
        now           the last point
        change        {absolute, percent, since} since the first point, or None
    """
    import bisect
    from datetime import timedelta

    all_balances = _balances_per_account(conn)
    active = [r for r in accounts.load_accounts(conn, only_active=True) if stack_of(r["kind"])]
    take_part = [r for r in active if all_balances.get(r["id"])]

    # Accounts with transactions but without a single balance: the shape is fixed,
    # the level is not. Those do not count, and the page must say which they are.
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT account_id FROM bank_transactions")
    with_transactions = {r["account_id"] for r in cursor.fetchall()}
    without_balance = sorted(r["name"] for r in active if r["id"] in with_transactions and not all_balances.get(r["id"]))

    empty = {
        "points": [],
        "from_date": None,
        "measurements": 0,
        "now": None,
        "change": None,
        "without_balance": without_balance,
        "deviating_balances": [],
        "pending_in_last": [],
    }
    balances = {r["id"]: accounts.balances_for_series(conn, r["id"]) for r in take_part}
    deviating_balances, pending_in_last = [], []
    for r in take_part:
        series_balances = balances[r["id"]]
        if not series_balances or series_balances[0]["source"] != "derived":
            continue
        anchor = all_balances[r["id"]][-1]["date"]
        occupied = {m["date"] for m in all_balances[r["id"]]}
        # Only compare where the reconstruction has data.
        measurements = [m for m in all_balances[r["id"]][:-1] if m["date"] >= series_balances[0]["date"]]
        calculated_on = {m["date"]: round(accounts.value_on(series_balances, m["date"]), 2) for m in measurements}
        # A payment that is already in the last balance but not booked yet shifts every
        # earlier balance by the same amount: one report, not one per balance.
        delta = accounts.anchor_difference(
            conn, r["id"], anchor, [(m["date"], round(m["balance"] - calculated_on[m["date"]], 2), m["source"]) for m in measurements]
        )
        if delta:
            pending_in_last.append(
                {
                    "account": r["name"],
                    "account_id": r["id"],
                    "date": anchor,
                    "amount": abs(delta),
                    "direction": "debits" if delta > 0 else "credits",
                }
            )
        for measurement in measurements:
            calculated = round(calculated_on[measurement["date"]] + delta, 2)
            difference = round(measurement["balance"] - calculated, 2)
            # Fetched before some of that day's bookings: simply right.
            if abs(difference) > 0.011 and not (
                measurement["source"] == "sync" and accounts.during_the_day(conn, r["id"], measurement["date"], difference)
            ):
                deviating_balances.append(
                    {
                        "account": r["name"],
                        "account_id": r["id"],
                        "date": measurement["date"],
                        "measured": measurement["balance"],
                        "calculated": calculated,
                        "source": measurement["source"],
                        # The balance from which the app calculates back: the last measurement.
                        "anchor": anchor,
                        "explanation": accounts.explain_deviation(
                            conn, r["id"], series_balances, measurement, calculated, anchor, occupied
                        ),
                    }
                )
    dates = {r["id"]: [m["date"] for m in balances[r["id"]]] for r in take_part}
    # Dots only on your own measurements. A balance from a statement or from your
    # transactions is not a measurement but a continuous series, and hundreds of
    # dots hide the line instead of pointing something out.
    measurement_days = {m["date"] for r in take_part for m in all_balances[r["id"]] if m["source"] == "manual"}
    series_edges = [items[i]["date"] for items in balances.values() for i in (0, -1)]

    price = sorted((p["d"], p["value"]) for p in investment_points)
    trading_days = [d for d, _ in price]
    edges = trading_days[:1] + trading_days[-1:] + series_edges
    if not edges:
        return empty
    day, final = date.fromisoformat(min(edges)), date.fromisoformat(max(edges))

    def portfolio_on(d: str) -> float:
        # A day without a closing price (weekend, holiday, after the last refresh)
        # stands at the previous one; before the first purchase there were no holdings yet.
        i = bisect.bisect_right(trading_days, d)
        return price[i - 1][1] if i else 0.0

    # What went into the holdings (buys minus what sells brought in) and the
    # dividend received so far, per trading day. With these the page measures
    # the market on the portfolio itself: the change in value minus what was put
    # in, plus dividend. Money moved between the bank and the broker then never
    # looks like a gain or a loss, however the bank transfer was labelled.
    put_in = {p["d"]: (p.get("invested") or 0.0, (p.get("value_divs") or p["value"]) - p["value"]) for p in investment_points}

    def put_in_on(d: str) -> tuple[float, float]:
        i = bisect.bisect_right(trading_days, d)
        return put_in[trading_days[i - 1]] if i else (0.0, 0.0)

    # Money of others ("Niet meetellen"): it really was on your account, but it was
    # not yours. As long as you received more than you paid on, that difference is a
    # debt to those others. If you paid more than you received, that difference is
    # not a credit but your own share — your own costs of the holiday — or something
    # that was never from others: a rule that also labels your own transfers like
    # that, for example. A credit would add such a mistake as net worth; so only
    # what you hold counts. See _money_from_others.
    others_dates, others_sum = _money_from_others(conn, {r["id"] for r in take_part})

    def from_others_on(d: str) -> float:
        i = bisect.bisect_right(others_dates, d)
        return others_sum[i - 1] if i else 0.0

    points = []
    while day <= final:
        d = day.isoformat()
        portfolio = portfolio_on(d)
        external = 0.0
        stacks = {"investments": portfolio, "bank": 0.0, "debt": 0.0}
        for r in take_part:
            value = accounts.value_on(balances[r["id"]], d, dates[r["id"]])
            stack = stack_of(r["kind"])
            stacks[stack] += value
            if stack == "investments":
                external += value
        # What you hold for others hangs below the zero line, with the debt.
        held = round(min(0.0, from_others_on(d)), 2)
        stacks["debt"] += held
        invested, dividends = put_in_on(d)
        points.append(
            {
                "d": d,
                "portfolio": round(portfolio, 2),
                # Cumulative: buys minus sells, and dividend received. Only their
                # change over a period means something.
                "portfolio_invested": round(invested, 2),
                "portfolio_dividends": round(dividends, 2),
                "investments_external": round(external, 2),
                "investments": round(stacks["investments"], 2),
                "bank": round(stacks["bank"], 2),
                "debt": round(stacks["debt"], 2),
                "net": round(sum(stacks.values()), 2),
                # How much of the debt is money of others that you still hold (zero or
                # negative). Already included in debt above.
                "held": held,
                # A measured point is harder than a point in between, and the chart must be able
                # to show that difference.
                "measured": d in measurement_days,
            }
        )
        day += timedelta(days=1)

    first, last = points[0], points[-1]
    change = None
    if len(points) > 1:
        absolute = last["net"] - first["net"]
        change = {
            "absolute": round(absolute, 2),
            "percent": (round(absolute / first["net"] * 100, 1) if first["net"] >= MINIMUM_BASE_FOR_PERCENT else None),
            "since": first["d"],
        }
    return {
        "points": points,
        "from_date": first["d"],
        "measurements": sum(1 for p in points if p["measured"]),
        "now": last,
        "change": change,
        "without_balance": without_balance,
        "deviating_balances": deviating_balances,
        "pending_in_last": pending_in_last,
    }


def daily_flows(conn: sqlite3.Connection) -> list[dict]:
    """Per day with bank transactions, the sums the Net worth page splits a
    change with. All in "money in" sign (income positive, spending negative),
    except *to_investments*, which is what went out to a broker.

      saved            income minus spending, the same types as the Spending page
      to_investments   net amount booked in "Naar beleggen" (out minus back)
      others           net flow in "Niet meetellen": money of or for friends
      unlabelled       transactions without a category yet
      bank_flow        every transaction on a bank or savings account that
                       counts in net worth, whatever its category
      bank_tx          transactions in the categories that land in Bank & cash
                       (role "bank"): what the Bank & cash link on the page lists

    The page cuts its own periods (salary months, a dragged stretch), hence per
    day and not per month.
    """
    from domain.money.categorization import EXCLUDE, INVESTMENT_CATEGORY, role_of

    all_balances = _balances_per_account(conn)
    bank_ids = sorted(
        r["id"] for r in accounts.load_accounts(conn, only_active=True) if stack_of(r["kind"]) == "bank" and all_balances.get(r["id"])
    )
    in_bank = f"account_id IN ({','.join('?' * len(bank_ids))})" if bank_ids else "1 = 0"

    cursor = conn.cursor()
    bank_names = [r["name"] for r in cursor.execute("SELECT name, type FROM categories") if role_of(r["name"], r["type"]) == "bank"]
    in_bank_role = f"category_effective IN ({','.join('?' * len(bank_names))})" if bank_names else "1 = 0"
    cursor.execute(
        f"""
        SELECT date,
               -- Spending is positive in the database and income negative.
               -SUM(CASE WHEN type_effective IN ('INCOME', 'EXPENSE') THEN amount ELSE 0 END) AS saved,
               SUM(CASE WHEN category_effective = ? THEN amount ELSE 0 END) AS to_investments,
               -SUM(CASE WHEN category_effective = ? THEN amount ELSE 0 END) AS others,
               -SUM(CASE WHEN category_effective IS NULL THEN amount ELSE 0 END) AS unlabelled,
               -SUM(CASE WHEN {in_bank} THEN amount ELSE 0 END) AS bank_flow,
               -SUM(CASE WHEN {in_bank_role} THEN amount ELSE 0 END) AS bank_tx
        FROM bank_transactions_typed
        GROUP BY date
        ORDER BY date ASC
    """,
        (INVESTMENT_CATEGORY, EXCLUDE, *bank_ids, *bank_names),
    )
    keys = ("saved", "to_investments", "others", "unlabelled", "bank_flow", "bank_tx")
    return [{"d": r["date"], **{k: round(r[k] or 0.0, 2) + 0.0 for k in keys}} for r in cursor.fetchall()]


def bank_corrections(conn: sqlite3.Connection, start: str, end: str) -> dict:
    """Where the balance corrections in Bank & cash come from, per account.

    The split calls corrections what the bank balances did that the
    transactions on those accounts don't explain: from the balance at the end
    of `start` to the end of `end`, the change of each account minus its own
    transactions. Per account the steps that make it up (`events`):

      start        the account's first data: before it, it counts as zero
      transfer     a savings account running on with transfers your other
                   accounts made to or from it (accounts._with_transfers_from_elsewhere)
      measurement  a balance (entered, imported, synced) the transactions don't reach
      line         the straight line between two entered balances, for the
                   part of it inside the period
      derived      a step in a balance from transactions that the transactions
                   of that day don't explain (normally nothing)

    Only accounts with a correction; they add up to the split's corrections
    (up to rounding per day there).
    """
    _verify = date.fromisoformat
    _verify(start), _verify(end)
    rows = []
    for r in accounts.load_accounts(conn, only_active=True):
        if stack_of(r["kind"]) != "bank" or not accounts.load_balances(conn, r["id"]):
            continue
        series_balances = accounts.balances_for_series(conn, r["id"])
        dates = [m["date"] for m in series_balances]
        # Spending is positive in the database: an expense lowers the balance.
        own = {
            row["date"]: -row["summed"]
            for row in conn.execute(
                "SELECT date, SUM(amount) AS summed FROM bank_transactions WHERE account_id = ? AND date > ? AND date <= ? GROUP BY date",
                (r["id"], start, end),
            )
        }

        def at(d: str) -> float:
            return accounts.value_on(series_balances, d, dates)  # noqa: B023  # used within this iteration only

        def own_between(a: str, b: str) -> float:
            return sum(v for d, v in own.items() if a < d <= b)  # noqa: B023  # used within this iteration only

        events, previous = [], start
        for i, m in enumerate(series_balances):
            if not start < m["date"] <= end:
                continue
            amount = at(m["date"]) - at(previous) - own_between(previous, m["date"])
            kind = (
                "start" if i == 0 else "transfer" if m["source"] == "transfer" else "derived" if m["source"] == "derived" else "measurement"
            )
            if abs(amount) >= 0.005:
                events.append(
                    {"date": m["date"], "kind": kind, "source": m["source"], "balance": round(m["balance"], 2), "amount": round(amount, 2)}
                )
            previous = m["date"]
        tail = at(end) - at(previous) - own_between(previous, end)
        if abs(tail) >= 0.005:
            events.append({"date": end, "kind": "line", "source": "manual", "balance": round(at(end), 2), "amount": round(tail, 2)})
        transactions = sum(own.values())
        correction = at(end) - at(start) - transactions
        if abs(correction) < 0.005:
            continue
        rows.append(
            {
                "account_id": r["id"],
                "account": r["name"],
                "kind": r["kind"],
                "start_balance": round(at(start), 2),
                "end_balance": round(at(end), 2),
                "transactions": round(transactions, 2) + 0.0,
                "correction": round(correction, 2),
                "events": events,
            }
        )
    rows.sort(key=lambda x: -abs(x["correction"]))
    return {"start": start, "end": end, "total": round(sum(x["correction"] for x in rows), 2) + 0.0, "accounts": rows}


def per_month(conn: sqlite3.Connection) -> list[dict]:
    """Per month: what came in, what went out, and what was left.

    INTERNAL counts nowhere — money between your own accounts is no expense and no
    income. That is exactly the correction for the old spreadsheet, where hundreds
    of savings transfers counted as spending.

    `complete` is only True when *every* active account with transactions covers
    the month from the first to the last day; `missing` names the accounts that
    do not. A half month next to whole months reads as a month in which you
    suddenly spent much less.

    Per account and not over everything together: with an ING export until
    20 February and a bunq export until the end of April, March and April first
    counted as complete, while your salary account was not in it at all. The
    savings rate of those months was then bunq alone.

    An account's coverage runs from its first transaction to its last transaction
    or, if later, its last balance from an import. A savings account books maybe
    once a quarter, but a balance overview until today says nothing was missing;
    without that every month after the last savings transfer became incomplete.

    Before its first data an account misses nothing. A savings account opened in
    2025 first made every month before it incomplete, back to 2020. The downside:
    someone whose export starts later than the account exists sees those earlier
    months as complete. The end does count: an export that stops while the month
    goes on is half a month, and that is what this rule was originally about.
    Closed accounts do not count: otherwise nothing is complete after every
    closure.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT MIN(date) AS start, MAX(date) AS end FROM bank_transactions")
    boundaries = cursor.fetchone()
    if not boundaries or not boundaries["start"]:
        return []
    first_day, last_day = boundaries["start"], boundaries["end"]

    cursor.execute("""
        SELECT r.name AS name, MIN(t.date) AS start,
               MAX(MAX(t.date), COALESCE((SELECT MAX(s.date) FROM account_balances s
                                           WHERE s.account_id = r.id AND s.source = 'sync'), ''))
                                   AS end,
               (SELECT MIN(s.date) FROM account_balances s
                 WHERE s.account_id = r.id AND s.source = 'sync') AS first_balance
        FROM bank_transactions t
        JOIN accounts r ON r.id = t.account_id
        -- Een paar handmatige regels zeggen niets over welke periode een
        -- export dekt; anders maakt één contante uitgave elke maand onvolledig.
        WHERE r.active = 1 AND t.source != 'manual'
        GROUP BY r.id
    """)
    coverage = [dict(r) for r in cursor.fetchall()]
    if not coverage:
        # All accounts closed: then the whole data is the only thing we have.
        coverage = [{"name": tr("all accounts"), "start": first_day, "end": last_day, "first_balance": None}]

    # From the view, so exactly the same type counts here as the Spending list
    # shows — including your manual corrections. See database.init_db. Added up per
    # day and then per month, because where a month starts depends on the month
    # layout (calendar or salary), not on the date text.
    cursor.execute("""
        SELECT date,
               type_effective AS type,
               SUM(amount)    AS summed,
               COUNT(*)       AS count
        FROM bank_transactions_typed
        GROUP BY date, type_effective
        ORDER BY date ASC
    """)
    layout = month_periods.layout(conn)

    per: dict[str, dict] = {}
    for row in cursor.fetchall():
        key = layout.key(row["date"])
        month = per.setdefault(
            key,
            {
                "month": key,
                "spending": 0.0,
                "income": 0.0,
                "internal": 0.0,
                "count": 0,
            },
        )
        month["count"] += row["count"]
        if row["type"] == "EXPENSE":
            month["spending"] += row["summed"]
        elif row["type"] == "INCOME":
            # Income is negative in the database (spending positive).
            month["income"] += -row["summed"]
        elif row["type"] == "INTERNAL":
            month["internal"] += row["summed"]

    groups = _spending_per_group(conn, layout)

    outcome = []
    for month in per.values():
        begin, final = layout.period(month["month"])

        remaining = month["income"] - month["spending"]
        missing = sorted(d["name"] for d in coverage if _is_missing(d, begin, final))
        outcome.append(
            {
                "month": month["month"],
                "spending": round(month["spending"], 2),
                "income": round(month["income"], 2),
                "internal": round(month["internal"], 2),
                "remaining": round(remaining, 2),
                "spaarquote": (round(remaining / month["income"] * 100, 1) if month["income"] >= MINIMUM_INCOME_FOR_QUOTE else None),
                "count": month["count"],
                "complete": not missing,
                "missing": missing,
                "groups": groups.get(month["month"], {}),
            }
        )
    return outcome


def _is_missing(coverage: dict, begin: str, final: str) -> bool:
    """Does this account miss part of the month start..end?

    - Before its first data (a transaction or a balance from an import) it misses
      nothing: then it did not exist yet, as far as the app knows.
    - If its data stops before the month is over, it misses the end.
    - If it starts halfway through the month, it misses the start — unless a
      balance from an import on or before its first transaction says it was
      opened then. A savings account's balance overview starts on the day it was
      opened; an export that starts on the 20th does not say that.
    """
    first_balance = coverage.get("first_balance")
    start = min(coverage["start"], first_balance) if first_balance else coverage["start"]
    if start > final:
        return False
    if coverage["end"] < final:
        return True
    opened = first_balance is not None and first_balance <= coverage["start"]
    return start > begin and not opened


def spending_per_month_per_group(conn: sqlite3.Connection, layout: "month_periods.Layout | None" = None) -> dict[str, dict[str, float]]:
    """{month: {group: amount}} for everything that counts as EXPENSE, each group separately.

    The one place that says what spending per group is: the chart below merges the
    small groups, the budget (budget.py) does not — but they count the same
    transactions, in the same months (month_periods.py). Unrounded; whoever shows
    it rounds.
    """
    layout = layout or month_periods.layout(conn)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT date,
               COALESCE(group_name, ?)   AS group_name,
               SUM(amount)          AS summed
        FROM bank_transactions_typed
        WHERE type_effective = 'EXPENSE'
        GROUP BY 1, 2
    """,
        (MISC,),
    )
    outcome: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in cursor.fetchall():
        outcome[layout.key(row["date"])][row["group_name"]] += row["summed"]
    return {month: dict(groups) for month, groups in outcome.items()}


def _spending_per_group(conn: sqlite3.Connection, layout: "month_periods.Layout | None" = None) -> dict[str, dict[str, float]]:
    """{month: {group: amount}} for everything that counts as EXPENSE.

    The largest MAX_GROUPS get their own name; the rest merges under "Overig".
    Which those are is decided over the whole period and not per month —
    otherwise a group changes colour as soon as it is a month larger or smaller
    than its neighbour, and then a colour means nothing any more.
    """
    rows = [
        {"month": month, "group_name": group_name, "summed": summed}
        for month, groups in spending_per_month_per_group(conn, layout).items()
        for group_name, summed in groups.items()
    ]

    total_per_group: dict[str, float] = defaultdict(float)
    for row in rows:
        total_per_group[row["group_name"]] += row["summed"]

    own_colour = {name for name, _ in sorted(total_per_group.items(), key=lambda kv: -kv[1])[:MAX_GROUPS]}

    per_month_group: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for row in rows:
        name = row["group_name"] if row["group_name"] in own_colour else MISC
        per_month_group[row["month"]][name] += row["summed"]

    return {month: {g: round(v, 2) for g, v in sorted(groups.items(), key=lambda kv: -kv[1])} for month, groups in per_month_group.items()}


# ---------------------------------------------------------------------------
# Splitting a change: saved, market, bank & cash, debt
# ---------------------------------------------------------------------------
#
# The same arithmetic as frontend/lib/net-worth-bridge.ts (`bridge`), for the
# MCP server: keep the two identical. In short:
#
#   change       = saved + market + bank & cash + debt
#   saved        income minus spending, from the bank transactions
#   market       the holdings' change in value minus what went into them, plus
#                dividend; without those fields the investments' change minus
#                the transfers labelled as investing
#   debt         the change in your own debts (money held for friends left out)
#   bank & cash  the remainder, told apart in `detail`: friends, unlabelled,
#                corrections and transfers
#
# With `shared_as_spending` (a shared-costs category in Settings) the friends
# part is your own share and moves to saved as spending.


def _day_before(d: str) -> str:
    from datetime import timedelta

    return (date.fromisoformat(d) - timedelta(days=1)).isoformat()


def split(start: dict, end: dict, flows: list[dict], shared_as_spending: bool = False) -> dict:
    """The change in net worth from point `start` to point `end`, split up.

    `start` and `end` are points of `series`, `flows` is `daily_flows`. Flows
    count when start.d < flow.d <= end.d. Returns {change, saved, market, bank,
    debt, detail, shared}; saved, market, bank, debt and detail are None when
    the bank data does not cover the period."""
    change = end["net"] - start["net"]
    debt = (end["debt"] - (end.get("held") or 0)) - (start["debt"] - (start.get("held") or 0))
    # Before the first bank transaction there is nothing to split with.
    if not flows or start["d"] < _day_before(flows[0]["d"]):
        return {"change": change, "saved": None, "market": None, "bank": None, "debt": None, "detail": None, "shared": 0.0}
    saved = deposited = others = unlabelled = bank_flow = bank_tx = 0.0
    for f in flows:
        if start["d"] < f["d"] <= end["d"]:
            saved += f["saved"]
            deposited += f["to_investments"]
            others += f.get("others") or 0
            unlabelled += f.get("unlabelled") or 0
            bank_flow += f.get("bank_flow") or 0
            bank_tx += f.get("bank_tx") or 0
    on_holdings = all(p.get(k) is not None for p in (start, end) for k in ("portfolio", "portfolio_invested"))
    if on_holdings:
        market = (
            (end["portfolio"] - start["portfolio"])
            - (end["portfolio_invested"] - start["portfolio_invested"])
            + ((end.get("portfolio_dividends") or 0) - (start.get("portfolio_dividends") or 0))
        )
    else:
        market = end["investments"] - start["investments"] - deposited
    friends = (end.get("held") or 0) - (start.get("held") or 0) + others
    shared = friends if shared_as_spending else 0.0
    saved += shared
    if shared_as_spending:
        friends = 0.0
    bank = change - saved - market - debt
    corrections = end["bank"] - start["bank"] - bank_flow
    transfers = bank - friends - unlabelled - corrections
    # What the Bank & cash link on the page lists, and what is left besides the
    # corrections: money whose other half isn't a bank transaction.
    listed = bank_tx + unlabelled + (0.0 if shared_as_spending else others) if "bank_tx" in flows[0] else None
    other_half = None if listed is None else bank - listed - corrections
    return {
        "change": change,
        "saved": saved,
        "market": market,
        "bank": bank,
        "debt": debt,
        "detail": {
            "friends": friends,
            "unlabelled": unlabelled,
            "corrections": corrections,
            "transfers": transfers,
            "listed": listed,
            "other_half": other_half,
        },
        "shared": shared,
    }


def split_per_month(
    points: list[dict], flows: list[dict], key, shared_as_spending: bool = False, *, until: str | None = None
) -> list[dict]:
    """Per month the split of its change, like the month table on the Net worth page.

    `key(d)` gives the month of a date (month_periods.Layout.key). A month runs
    from the last point of the month before to its own last point (up to
    `until`); the first month has no base and gets no split. `partial`: the
    month is cut off by `until` or is still running."""
    if not points:
        return []
    last_of_month: dict[str, str] = {}
    for p in points:
        last_of_month[key(p["d"])] = p["d"]
    final: dict[str, dict] = {}
    for p in points:
        if until is None or p["d"] <= until:
            final[key(p["d"])] = p
    rows, previous = [], None
    for month, p in final.items():
        rows.append(
            {
                "month": month,
                "from": previous["d"] if previous else None,
                "to": p["d"],
                "partial": p["d"] != last_of_month[month] or p["d"] == points[-1]["d"],
                "split": split(previous, p, flows, shared_as_spending) if previous else None,
            }
        )
        previous = p
    return rows
