"""
The Dividend tab: everything the portfolio's own payment history can answer,
and nothing it cannot.

The dashboard already shows two dividend numbers (this month / this year) and
the next expected payment. That card answers "is something coming". This tab
answers the questions a card has no room for: when does the money arrive over
a year, which holdings actually pay, how much the withholding tax takes, and
what the payments add up to over time.

Two rules carried over from the dashboard's forecast, because breaking them
here would make the same claim twice as loudly:

  * A **estimate** is only ever shown at month precision. The schedule
    arithmetic in dashboard_service.forecast_dividends produces an exact date
    because it must count days; that date is not knowledge. The payload keeps
    `month` + `part` next to it and the UI shows those.
  * A holding without a recognisable rhythm gets **no** forecast at all.
    Omitted, not guessed at.

Everything here is deterministic: it takes the payments, the positions and the
already-merged outlook, and does arithmetic. The one external thing this tab
uses — Yahoo's ex-dividend calendar — is fetched and cached by
dashboard_service.get_ex_dividends, upstream of `build`.
"""

import datetime

from app.services import dashboard_service

#: "Last 12 months" is the window every yield on this tab is measured over.
#: A calendar year is the wrong one for a yield: on 3 January it is built from
#: three days of payments.
_TTM_DAYS = 365

#: How far the forward run-rate looks. A full year on purpose — a quarterly
#: payer would otherwise contribute a different number of payments depending on
#: which month you opened the tab in.
_FORWARD_DAYS = 365

#: Short month names for API clients; the app formats the month number itself.
_MONTH_ABBR = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _clean(dividends: list[dict]) -> list[dict]:
    """Payments with a usable date and net amount, ascending.

    gross/tax can be absent on a row (an old import, a payment DeGiro booked
    without a tax line); they become 0.0 rather than dropping the payment,
    since `net_eur` is the column everything on this tab is really about.
    """
    out = []
    for d in dividends:
        date = (d.get("date") or "")[:10]
        if len(date) != 10 or d.get("net_eur") is None:
            continue
        out.append(
            {
                "date": date,
                "isin": d.get("isin") or "",
                "name": d.get("name") or "",
                "gross_eur": float(d.get("gross_eur") or 0.0),
                "tax_eur": float(d.get("tax_eur") or 0.0),
                "net_eur": float(d["net_eur"]),
                "currency": d.get("currency_original") or "EUR",
            }
        )
    out.sort(key=lambda p: p["date"])
    return out


def _between(payments: list[dict], lo: str, hi: str) -> float:
    """Net EUR over the half-open window (lo, hi] — dates as ISO strings."""
    return sum(p["net_eur"] for p in payments if lo < p["date"] <= hi)


def ttm_on_current_holding(
    payments: list[dict],
    positions: list[dict],
    transactions: list[dict] | None,
    today: datetime.date,
) -> dict[str, float | None]:
    """{isin: the last twelve months of dividend, restated per the shares held now}

    A yield needs the same number of shares above and below the line. `ttm_net`
    is what the fund actually paid, on however many shares were held on each pay
    date; `total_invested` is what the shares still held cost. After a partial
    sale those describe different positions, and dividing one by the other
    printed a fund that yielded 8% as yielding 80% — the more you had sold, the
    more flattering the number, which is exactly backwards.

    So each payment is put back on a per-share footing and scaled to today's
    holding. A position that was never resized is unaffected: the scaling factor
    is 1.

    None for a holding whose share count at a pay date cannot be established
    (a sale with no matching buy in the data). A dash is the honest answer
    there; the unscaled ratio is not.
    """
    if not transactions:
        return {}
    ttm_start = (today - datetime.timedelta(days=_TTM_DAYS)).isoformat()
    traded = {t.get("isin") for t in transactions}
    out: dict[str, float | None] = {}
    for position in positions:
        isin = position["isin"]
        if isin not in traded:
            continue  # no share history to scale by; the raw total is all there is
        shares_now = position.get("shares_held") or 0.0
        if shares_now <= 0:
            continue
        total = 0.0
        for p in payments:
            if p["isin"] != isin or not (ttm_start < p["date"] <= today.isoformat()):
                continue
            day = datetime.date.fromisoformat(p["date"])
            shares_then = dashboard_service._shares_held_at(transactions, isin, day)
            if shares_then <= 0:
                total = None
                break
            total += p["net_eur"] / shares_then * shares_now
        out[isin] = total
    return out


def _pct(part: float, whole: float) -> float | None:
    """Percentage, or None when the denominator says the question is unanswerable.

    Every ratio on this tab goes through here: a yield on a zero cost basis and
    a growth rate off a zero base are both "no answer", and a page that prints
    0,0% for them is lying more quietly than one that prints a dash.
    """
    if whole is None or whole <= 0:
        return None
    return round(part / whole * 100.0, 2)


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------


def by_year(payments: list[dict], expected_rest_of_year: float, today: datetime.date) -> list[dict]:
    """One row per calendar year, ascending, with gross/tax/net.

    The running year also carries `expected` — what the forecast still has
    coming before 31 December — so the year can be drawn as what it is: a bar
    that is not finished yet. Past years have `expected: 0`; only the current
    year's is ever non-zero, because a forecast beyond this December is a
    schedule extrapolated further than its own history justifies.
    """
    buckets: dict[str, dict] = {}
    for p in payments:
        year = p["date"][:4]
        row = buckets.setdefault(
            year,
            {
                "year": year,
                "gross": 0.0,
                "tax": 0.0,
                "net": 0.0,
                "payments": 0,
            },
        )
        row["gross"] += p["gross_eur"]
        row["tax"] += p["tax_eur"]
        row["net"] += p["net_eur"]
        row["payments"] += 1

    this_year = str(today.year)
    if expected_rest_of_year > 0:
        buckets.setdefault(
            this_year,
            {
                "year": this_year,
                "gross": 0.0,
                "tax": 0.0,
                "net": 0.0,
                "payments": 0,
            },
        )

    rows = []
    for year in sorted(buckets):
        row = buckets[year]
        rows.append(
            {
                "year": row["year"],
                "gross": round(row["gross"], 2),
                "tax": round(row["tax"], 2),
                "net": round(row["net"], 2),
                "payments": row["payments"],
                "expected": round(expected_rest_of_year, 2) if row["year"] == this_year else 0.0,
                "partial": row["year"] == this_year,
            }
        )
    return rows


def by_month(payments: list[dict], forecast: list[dict], today: datetime.date, months_back: int = 24) -> list[dict]:
    """A continuous monthly series: received behind, expected ahead.

    Continuous matters. A bar chart built only from the months that *had* a
    payment draws a quarterly payer as four adjacent bars and hides the very
    thing the chart is for — that eight months of the year were empty. Months
    with nothing get a zero row.
    """
    received: dict[str, float] = {}
    for p in payments:
        month = p["date"][:7]
        received[month] = received.get(month, 0.0) + p["net_eur"]

    expected: dict[str, float] = {}
    for e in forecast:
        if e.get("expected_eur") is None:
            continue
        expected[e["month"]] = expected.get(e["month"], 0.0) + e["expected_eur"]

    start = _add_months(f"{today.year:04d}-{today.month:02d}", -(months_back - 1))
    if received:
        start = max(start, min(received))
    last_expected = max(expected) if expected else ""
    end = max(f"{today.year:04d}-{today.month:02d}", last_expected)

    rows = []
    month = start
    while month <= end:
        rows.append(
            {
                "month": month,
                "net": round(received.get(month, 0.0), 2),
                # The running month has both: what already landed, and what the
                # schedule still expects. Stacking them keeps the bar comparable to
                # its neighbours instead of reading as a collapse.
                "expected": round(expected.get(month, 0.0), 2),
                "future": month > f"{today.year:04d}-{today.month:02d}",
            }
        )
        month = _add_months(month, 1)
    return rows


def _add_months(month: str, delta: int) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    total = year * 12 + (mon - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def seasonality(payments: list[dict]) -> list[dict]:
    """Per calendar month: everything ever received in it, over every year.

    Deliberately a **total**, not an average per year. An average needs a
    denominator, and every honest candidate for it is wrong here: the number of
    years with a payment in that month flatters a month that paid once, and the
    number of years of history punishes one that only started paying last year.
    The total plus the number of years behind it says the same thing without
    inventing a rate.
    """
    totals = [0.0] * 12
    years: list[set[str]] = [set() for _ in range(12)]
    for p in payments:
        idx = int(p["date"][5:7]) - 1
        totals[idx] += p["net_eur"]
        years[idx].add(p["date"][:4])

    grand = sum(totals)
    return [
        {
            "month": i + 1,
            "label": _MONTH_ABBR[i],
            "total": round(totals[i], 2),
            "years": len(years[i]),
            "share_pct": _pct(totals[i], grand) if totals[i] > 0 else None,
        }
        for i in range(12)
    ]


def cumulative(payments: list[dict], today: datetime.date) -> list[dict]:
    """Running total of net dividends, one point per payment date.

    A step line: it only moves on a payday, which is exactly what the money
    did. The final point repeats the total at today's date so the line reaches
    the right edge of the chart rather than stopping months short of it and
    reading as "the payments dried up".
    """
    if not payments:
        return []
    points: list[dict] = []
    running = 0.0
    for p in payments:
        running += p["net_eur"]
        if points and points[-1]["d"] == p["date"]:
            points[-1]["v"] = round(running, 2)
        else:
            points.append({"d": p["date"], "v": round(running, 2)})
    if points[-1]["d"] < today.isoformat():
        points.append({"d": today.isoformat(), "v": points[-1]["v"]})
    return points


def by_stock(
    payments: list[dict],
    positions: list[dict],
    upcoming: list[dict],
    today: datetime.date,
    ttm_scaled: dict[str, float | None] | None = None,
) -> list[dict]:
    """One row per ISIN that has ever paid, biggest all-time payer first.

    Sold holdings stay in the list — €300 of dividend from a position you no
    longer own is still €300 you received, and dropping it would make the rows
    disagree with the totals above them. They are flagged `held: false` so the
    UI can say so and so a yield is not computed for them.
    """
    held = {p["isin"]: p for p in positions}
    ttm_start = (today - datetime.timedelta(days=_TTM_DAYS)).isoformat()
    next_by_isin: dict[str, dict] = {}
    for e in upcoming:
        next_by_isin.setdefault(e["isin"], e)

    rows: dict[str, dict] = {}
    dates_by_isin: dict[str, list[datetime.date]] = {}
    for p in payments:
        row = rows.setdefault(
            p["isin"],
            {
                "isin": p["isin"],
                "name": p["name"],
                "gross": 0.0,
                "tax": 0.0,
                "net": 0.0,
                "ttm_net": 0.0,
                "payments": 0,
                "first": p["date"],
                "last": p["date"],
            },
        )
        row["gross"] += p["gross_eur"]
        row["tax"] += p["tax_eur"]
        row["net"] += p["net_eur"]
        row["payments"] += 1
        row["last"] = p["date"]
        if p["name"]:
            row["name"] = p["name"]
        if p["date"] > ttm_start:
            row["ttm_net"] += p["net_eur"]
        dates_by_isin.setdefault(p["isin"], []).append(datetime.date.fromisoformat(p["date"]))

    grand = sum(r["net"] for r in rows.values())
    ttm_scaled = ttm_scaled if ttm_scaled is not None else {}

    out = []
    for isin, row in rows.items():
        position = held.get(isin)
        invested = position.get("total_invested") if position else None
        # The yield's numerator, on the same number of shares as its
        # denominator — see ttm_on_current_holding. Absent from the map means
        # there was nothing to restate, so the raw twelve-month total already
        # matches the position.
        ttm_for_yield = ttm_scaled.get(isin, row["ttm_net"]) if position else None
        cadence = dashboard_service.detect_cadence(sorted(set(dates_by_isin[isin])))
        nxt = next_by_isin.get(isin)
        out.append(
            {
                "isin": isin,
                "name": row["name"] or (position or {}).get("name") or isin,
                "held": position is not None,
                "gross": round(row["gross"], 2),
                "tax": round(row["tax"], 2),
                "net": round(row["net"], 2),
                "ttm_net": round(row["ttm_net"], 2),
                "payments": row["payments"],
                "first": row["first"],
                "last": row["last"],
                "share_pct": _pct(row["net"], grand),
                # detect_cadence only recognises one rhythm. An interim/final payer
                # (NN Group: ~aug and ~jun) has two, and its median gap matches
                # none of them — the forecast catches it with its own alternating
                # detector, so borrow the label from there rather than leaving the
                # row blank while the agenda above it says "semi-annual".
                "cadence": cadence[2] if cadence else (nxt or {}).get("cadence"),
                # Yield on what this position cost, over the last twelve months.
                # Only for holdings still open: a sold position has no cost basis
                # left to divide by.
                "yield_on_cost_pct": (_pct(ttm_for_yield, invested) if ttm_for_yield is not None else None),
                "invested": round(invested, 2) if invested else None,
                "next": {
                    # `date` is only ever shown for an "official" entry — for a
                    # estimate it is schedule arithmetic and the month + part beside
                    # it are the honest reading. Carried anyway so the UI does not
                    # have to reach back into `upcoming` for the one case that has
                    # a real calendar day.
                    "date": nxt["date"],
                    "month": nxt["month"],
                    "part": nxt["part"],
                    "expected_eur": nxt["expected_eur"],
                    "source": nxt["source"],
                    "cadence": nxt["cadence"],
                }
                if nxt
                else None,
            }
        )

    out.sort(key=lambda r: r["net"], reverse=True)
    return out


def totals(
    payments: list[dict],
    positions: list[dict],
    by_year_rows: list[dict],
    forward: dict,
    expected_rest_of_year: float,
    today: datetime.date,
    ttm_scaled: dict[str, float | None] | None = None,
    summary: dict | None = None,
) -> dict:
    """The figures at the top of the tab.

    Two windows, and they answer different questions:

      * **laatste 12 maanden** — what actually arrived. The only window a yield
        may be built on, and the one that compares to the twelve months before
        it without a calendar boundary distorting either side.
      * **komende 12 maanden** — the forward run rate: every scheduled payment
        the holdings' own rhythms imply, over a full year so the answer does
        not depend on which month you are standing in.
    """
    ttm_start = (today - datetime.timedelta(days=_TTM_DAYS)).isoformat()
    prev_start = (today - datetime.timedelta(days=2 * _TTM_DAYS)).isoformat()

    net = sum(p["net_eur"] for p in payments)
    gross = sum(p["gross_eur"] for p in payments)
    tax = sum(p["tax_eur"] for p in payments)

    ttm = _between(payments, ttm_start, today.isoformat())
    prev_ttm = _between(payments, prev_start, ttm_start)

    this_year = sum(p["net_eur"] for p in payments if p["date"][:4] == str(today.year))
    # Same stretch of last year, so "more than last year" compares January-to-now
    # with January-to-now and not with a whole finished year.
    last_year_ytd = sum(p["net_eur"] for p in payments if p["date"][:4] == str(today.year - 1) and p["date"][5:] <= today.isoformat()[5:])
    last_year_full = sum(p["net_eur"] for p in payments if p["date"][:4] == str(today.year - 1))

    invested = sum(p.get("total_invested") or 0.0 for p in positions)
    # A position with no usable price contributes nothing to `value` but its
    # full cost to `invested`, so any ratio built from both at once divides a
    # whole portfolio by part of one. With two EUR 10.000 positions and one
    # price missing, the yield on value was measured against EUR 12.000 of a
    # portfolio that had EUR 20.000 of cost basis in it — and the same gap
    # turned a portfolio in profit into one this page believed was down, which
    # silently removed the "% of your total gain" line. The dashboard already
    # refuses to break its result down until every price is in; the value-based
    # figures here now follow the same rule and render as a dash instead.
    priced = [p for p in positions if p.get("current_value") is not None]
    prices_complete = len(priced) == len(positions)
    value = sum(p["current_value"] for p in priced) if prices_complete else None
    forward_12m = forward["total"]

    # The yield's numerator restated onto the shares actually held now, for the
    # same reason it is restated per fund (see ttm_on_current_holding). Falls
    # back to the raw window where there is nothing to restate.
    ttm_scaled = ttm_scaled if ttm_scaled is not None else {}
    held_isins = {p["isin"] for p in positions}
    if ttm_scaled:
        parts = [ttm_scaled.get(i, _between([p for p in payments if p["isin"] == i], ttm_start, today.isoformat())) for i in held_isins]
        ttm_for_yield = None if any(v is None for v in parts) else sum(parts)
    else:
        ttm_for_yield = ttm

    best = max(
        ({"month": m, "net": round(v, 2)} for m, v in _month_totals(payments).items()),
        key=lambda r: r["net"],
        default=None,
    )

    # Dividends as a share of what the portfolio has made in total. Only when
    # that total is positive: "82% of a loss came from dividends" is a sentence
    # with no meaning — and only when every position is priced, since a missing
    # one shows up here as a loss the size of its cost basis.
    #
    # "Je totale winst" is the dashboard's Totaalrendement, taken from the same
    # summary that prints it, and not rebuilt here. Rebuilt from the open
    # positions alone it silently dropped what earlier sells locked in: EUR
    # 3.022,50 against the EUR 3.502,10 the dashboard shows — a difference of
    # exactly the "Realised" row sitting three lines below it — so the tab
    # said 9% where the dashboard's own two numbers divide to 8%.
    profit = None
    if summary and summary.get("prices_available") and value is not None:
        profit = summary["total_gain"] + summary["total_dividends"]
    return {
        "net": round(net, 2),
        "gross": round(gross, 2),
        "tax": round(tax, 2),
        "tax_pct": _pct(-tax, gross),
        "payments": len(payments),
        "first_payment": payments[0]["date"] if payments else None,
        "last_payment": payments[-1]["date"] if payments else None,
        "ttm_net": round(ttm, 2),
        "prev_ttm_net": round(prev_ttm, 2),
        "ttm_growth_pct": _pct(ttm - prev_ttm, prev_ttm),
        "this_year_net": round(this_year, 2),
        "last_year_ytd_net": round(last_year_ytd, 2),
        "last_year_net": round(last_year_full, 2),
        "expected_rest_of_year": round(expected_rest_of_year, 2),
        "expected_year_total": round(this_year + expected_rest_of_year, 2),
        "forward_12m_net": round(forward_12m, 2),
        "forward_monthly_avg": round(forward_12m / 12.0, 2),
        "yield_on_cost_pct": _pct(ttm_for_yield, invested) if ttm_for_yield is not None else None,
        "yield_on_value_pct": _pct(ttm_for_yield, value) if (ttm_for_yield is not None and value is not None) else None,
        "forward_yield_on_cost_pct": _pct(forward_12m, invested),
        "share_of_profit_pct": _pct(net, profit) if profit and profit > 0 else None,
        "best_month": best,
        "years": len(by_year_rows),
        "payers": len({p["isin"] for p in payments} & {p["isin"] for p in positions}),
        "positions": len(positions),
    }


def _month_totals(payments: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in payments:
        out[p["date"][:7]] = out.get(p["date"][:7], 0.0) + p["net_eur"]
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build(
    positions: list[dict],
    transactions: list[dict],
    dividends: list[dict],
    outlook: dict,
    today: datetime.date | None = None,
    summary: dict | None = None,
) -> dict:
    """Everything the Dividend tab draws.

    `outlook` is the dashboard's own six-month forecast, already merged with
    any official ex-dividend dates — reused rather than recomputed so the tab
    and the dashboard card can never name a different next payment. The
    twelve-month forward schedule is computed here on top of it, for the run
    rate and for the months beyond the dashboard's horizon; it is pure
    arithmetic over the same history and touches no network.

    `summary` is calculate_portfolio_summary's, for the one figure on this tab
    that belongs to the dashboard rather than to the payment history: the total
    profit "x% van je totale winst" is a share of. Passed in for the same reason
    `outlook` is — a number the user reads on two screens gets computed once.
    Omitted, that line simply does not render.
    """
    today = today or datetime.date.today()
    payments = _clean(dividends)
    upcoming = outlook.get("upcoming", [])
    rest_of_year = outlook.get("rest_of_year_eur", 0.0) or 0.0

    forward_schedule = dashboard_service.forecast_dividends(
        positions,
        dividends,
        transactions,
        today=today,
        horizon_days=_FORWARD_DAYS,
    )["upcoming"]
    forward = {
        "total": sum(e["expected_eur"] or 0.0 for e in forward_schedule),
        "schedule": forward_schedule,
    }

    # One restatement of the trailing year onto today's share counts, shared by
    # the header figures and the per-fund rows so the two cannot disagree about
    # what a yield is measured on.
    ttm_scaled = ttm_on_current_holding(payments, positions, transactions, today)

    year_rows = by_year(payments, rest_of_year, today)
    return {
        "totals": totals(payments, positions, year_rows, forward, rest_of_year, today, ttm_scaled=ttm_scaled, summary=summary),
        "by_year": year_rows,
        "by_month": by_month(payments, forward_schedule, today),
        "seasonality": seasonality(payments),
        "cumulative": cumulative(payments, today),
        "by_stock": by_stock(payments, positions, upcoming, today, ttm_scaled=ttm_scaled),
        "upcoming": upcoming,
        "payments": [
            {**p, "gross_eur": round(p["gross_eur"], 2), "tax_eur": round(p["tax_eur"], 2), "net_eur": round(p["net_eur"], 2)}
            for p in reversed(payments)
        ],
    }
