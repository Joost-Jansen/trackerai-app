"""
Sector and region allocation over time: the Allocation tab's look-through,
at every month-end since the first trade, plus today.

What is measured and what is not:

  - **Holdings per date are measured.** The shares held on each date come from
    the stored transactions, the same BUY/SELL walk the value history does.
  - **Values per date are measured where a close exists.** Each position at its
    own EUR close on or before that date (series._eur_daily_closes); without
    history the cached current price stands in, and without that the
    position's average cost — the same fallbacks, in the same order, as the
    value-over-time card, reported through `estimated` the same way.
  - **The look-through per fund is today's.** Issuers publish their holdings
    file as of now; the app keeps no history of it. So a fund's sector and
    country mix is applied to every past date, and the frontend says so in a
    sentence. What does move the lines is what you held and what it was worth.

The pure functions below take plain data so the tests can drive them without a
network; app/services/etf_service.get_allocation_history wires them to the
database, the price download and the cache.
"""

import calendar
import datetime

#: The name every consumer folds the tail into. The issuers' own "no sector"
#: bucket lands under the same name (etf_holdings.position_mix), so both have to
#: end up in *one* row — two rows called "Other" is the bug this guards against.
OTHER = "Other"


def month_end_dates(first: datetime.date, today: datetime.date) -> list[datetime.date]:
    """Every month-end from *first*'s month up to (not including) *today*, then today.

    A month-end on or after today is replaced by today itself: the last point is
    always "now", so the series ends where the current allocation card is.
    """
    out: list[datetime.date] = []
    year, month = first.year, first.month
    while True:
        end = datetime.date(year, month, calendar.monthrange(year, month)[1])
        if end >= today:
            break
        out.append(end)
        month += 1
        if month > 12:
            month, year = 1, year + 1
    out.append(today)
    return out


def holdings_on(transactions: list[dict], dates: list[datetime.date]) -> list[dict[str, tuple[float, float]]]:
    """Per date: {isin: (shares held, average cost per share in EUR)}.

    Average cost is the weighted cost of the buys, as series.portfolio_history_series
    keeps it — the last-resort price for a holding without any quote. A sale
    lowers the shares and leaves the average unchanged. Other transaction types
    (if a broker import adds them) do not move shares.
    """
    ordered = sorted((t for t in transactions if t.get("date") and t.get("isin")), key=lambda t: t["date"])
    shares: dict[str, float] = {}
    cost: dict[str, float] = {}
    out: list[dict[str, tuple[float, float]]] = []
    i = 0
    for day in sorted(dates):
        iso = day.isoformat()
        while i < len(ordered) and ordered[i]["date"][:10] <= iso:
            t = ordered[i]
            isin = t["isin"]
            qty = t.get("quantity") or 0.0
            if t.get("transaction_type") == "BUY":
                total = abs(t["total_eur"]) if t.get("total_eur") is not None else 0.0
                old = shares.get(isin, 0.0)
                new = old + qty
                cost[isin] = (old * cost.get(isin, 0.0) + total) / new if new > 0 else 0.0
                shares[isin] = new
            elif t.get("transaction_type") == "SELL":
                shares[isin] = max(shares.get(isin, 0.0) - qty, 0.0)
            i += 1
        # 0.0001: the same "closed" threshold as positions.calculate_positions.
        out.append({isin: (q, cost.get(isin, 0.0)) for isin, q in shares.items() if q > 0.0001})
    return out


def mix_totals(values: dict[str, float], mixes: dict[str, dict[str, float]]) -> dict[str, float]:
    """{slice: EUR}: each position's value spread over its own mix.

    Renormalised to the positions' total, as get_portfolio_breakdown does:
    yfinance's fund-level sector weights and justetf's country table each sum
    to a hair either side of 1, and without this the slices of a date would not
    add up to that date's value. A position without a mix does not count.
    """
    raw: dict[str, float] = {}
    counted = 0.0
    for isin, value in values.items():
        mix = mixes.get(isin)
        if not mix or value <= 0:
            continue
        counted += value
        for name, frac in mix.items():
            raw[name] = raw.get(name, 0.0) + frac * value
    total = sum(raw.values())
    if total <= 0:
        return {}
    scale = counted / total
    return {name: v * scale for name, v in raw.items()}


def fold(totals_per_date: list[dict[str, float]], top_n: int = 5) -> tuple[list[str], list[list[float]]]:
    """A fixed set of slices for the whole series: the biggest `top_n` plus one "Other".

    Ranked by the *last* date, so the chart's legend has the same order as the
    current allocation card above it. Fixed for every date, because a slice that
    changes name or colour halfway through a stacked chart is unreadable.

    Everything outside the top joins "Other", and so does a slice that is
    *called* "Other" (the issuers' unclassified holdings): one row of that name,
    never two. When the named slices fit in the palette on their own (top_n + 1,
    the slot "Other" would take) they are all kept, as lib/slices.ts topSlices
    does — then "Other" is only there when the data has one.

    Returns (keys, values): values[i][k] is the EUR of keys[k] on date i.
    """
    last = next((t for t in reversed(totals_per_date) if t), {})
    seen: dict[str, float] = {}
    for t in totals_per_date:
        for name in t:
            if name != OTHER:
                seen.setdefault(name, 0.0)
    # Latest share first; a name absent today falls behind, by its peak.
    peak = {name: max(t.get(name, 0.0) for t in totals_per_date) for name in seen}
    named = sorted(seen, key=lambda n: (-last.get(n, 0.0), -peak[n], n))
    has_other = any(t.get(OTHER, 0.0) > 0 for t in totals_per_date)

    if len(named) <= top_n + (0 if has_other else 1):
        top = named
    else:
        top = named[:top_n]
    rest = set(named) - set(top)
    need_other = has_other or any(t.get(n, 0.0) > 0 for t in totals_per_date for n in rest)
    keys = top + ([OTHER] if need_other else [])

    rows: list[list[float]] = []
    for t in totals_per_date:
        row = [t.get(k, 0.0) for k in top]
        if need_other:
            row.append(t.get(OTHER, 0.0) + sum(v for n, v in t.items() if n in rest))
        rows.append(row)
    return keys, rows


def as_payload(keys: list[str], rows: list[list[float]]) -> dict:
    """{keys, pct, value}: per date the share of that date's total and the euros."""
    pct: list[list[float]] = []
    value: list[list[float]] = []
    for row in rows:
        total = sum(row)
        pct.append([round(v / total * 100, 2) if total > 0 else 0.0 for v in row])
        value.append([round(v, 2) for v in row])
    return {"keys": keys, "pct": pct, "value": value}
