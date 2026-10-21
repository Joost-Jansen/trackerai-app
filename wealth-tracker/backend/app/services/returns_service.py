"""
The Returns tab: the two return measures the dashboard deliberately does not
use, and the arithmetic behind them.

The dashboard answers "what did my money do" — a euro figure with a percentage
that pairs with it. That question has one right answer and it is already there.
This tab answers the two questions that euro figure cannot:

  * **TWR** (time-weighted) — how did the *investments* do, with the timing of
    deposits stripped out. The only measure you may compare to an index, because
    a benchmark has no deposit schedule to be flattered or punished by.
  * **IRR** (money-weighted, annualised) — what did *your money* actually earn
    per year, deposit timing included. Buying more before a rise lifts it;
    buying more before a fall lowers it. TWR is blind to both by design.

They can differ enormously and both be right. On the portfolio this was built
against, TWR since inception reads +112,5% and the money-weighted answer is far
lower, because most of the money arrived late: the early years were small and
went well, the recent years are large and went normally. TWR weights those two
periods equally; the euro in your account does not.

Nothing here fetches. It takes the daily series charts.py already builds and the
segments benchmark_service already caches.
"""

import datetime

from domain.portfolio import series as charts

# An annualised rate over a few weeks is arithmetic, not information: two good
# days become "+400% per year". Below this many days the tab shows a dash and
# says why.
MIN_IRR_DAYS = 180

# Bisection bounds. -99,99% is total loss; 10000% covers anything a real
# portfolio can produce over a window long enough for IRR to be shown at all.
_IRR_LO = -0.9999
_IRR_HI = 100.0
_IRR_STEPS = 200


def _npv(rate: float, flows: list[tuple[datetime.date, float]]) -> float:
    """Net present value of dated cash flows at an annual *rate*, ACT/365."""
    t0 = flows[0][0]
    total = 0.0
    for when, amount in flows:
        years = (when - t0).days / 365.0
        total += amount / ((1.0 + rate) ** years)
    return total


def irr(flows: list[tuple[datetime.date, float]]) -> float | None:
    """Annualised money-weighted return, or None when there is no answer.

    Bisection rather than Newton: Newton is faster but can walk off a curve with
    a near-flat region, and this runs a handful of times per page load. Bisection
    cannot diverge, and "no sign change over the bracket" is a clean way to
    report that the flows admit no rate — which happens for real inputs, such as
    a window whose every flow points the same way.

    Sign convention: money leaving you is negative (the opening value and every
    deposit), money coming back is positive (withdrawals and the closing value).
    """
    if len(flows) < 2:
        return None
    flows = sorted(flows, key=lambda f: f[0])
    if flows[0][0] == flows[-1][0]:
        return None
    if not (any(a > 0 for _, a in flows) and any(a < 0 for _, a in flows)):
        return None

    lo, hi = _IRR_LO, _IRR_HI
    f_lo, f_hi = _npv(lo, flows), _npv(hi, flows)
    if f_lo * f_hi > 0:
        return None

    for _ in range(_IRR_STEPS):
        mid = (lo + hi) / 2.0
        f_mid = _npv(mid, flows)
        if f_mid == 0:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def cash_flows(dates: list, invested: list[float], values: list[float], lo: int, hi: int) -> list[tuple[datetime.date, float]]:
    """The flows for window [lo, hi] of the daily series, IRR's sign convention.

    The opening value is an outflow (you already had that much at work) and the
    closing value an inflow (what liquidating would return). In between,
    `invested` moves only on a deposit or a withdrawal, so its daily difference
    *is* the flow.
    """
    flows = [(dates[lo], -values[lo])]
    for i in range(lo + 1, hi + 1):
        delta = round(invested[i] - invested[i - 1], 2)
        if delta:
            flows.append((dates[i], -delta))
    flows.append((dates[hi], values[hi]))
    return flows


def twr_over(index: list[float], lo: int, hi: int) -> float | None:
    """The time-weighted return between two points of a TWR index, in percent."""
    if index[lo] <= 0:
        return None
    return (index[hi] / index[lo] - 1.0) * 100.0


def build(transactions, prices, dividends, window: tuple[str, str] | None = None) -> dict:
    """Everything the Returns tab draws, from one pass over the daily series.

    `points` is the TWR index rebased to 100 at the very first day, so the
    frontend can slice and rebase it per range without another request — the
    same trick /performance uses.

    `gaps` marks the stretches where the portfolio was empty. TWR chains the
    segments across them (charts._compute_twr_index), which is the right
    convention for an index but a real caveat on a page about your returns: the
    line claims no gain or loss over months in which you held nothing, and the
    tab says so where the gap is.
    """
    dates, invested, values, values_divs = charts.portfolio_history_series(transactions, prices, dividends)
    if len(dates) < 2:
        return {"points": [], "gaps": [], "ranges": []}

    segments = charts.build_portfolio_segments(transactions, prices, dividends)
    series = charts._compute_twr_index(segments)
    by_date = {d.date(): float(v) for d, v in series.items()}
    # The TWR index only covers days inside a segment; the value series covers
    # every calendar day. Carrying the last level forward across a gap keeps the
    # two aligned index-for-index, and draws the gap as the flat stretch it was.
    index: list[float] = []
    level = 100.0
    for d in dates:
        level = by_date.get(d, level)
        index.append(level)

    gaps = []
    if len(segments) > 1:
        for earlier, later in zip(segments, segments[1:]):
            gaps.append({"from": earlier[0][-1].isoformat(), "to": later[0][0].isoformat()})

    # value_divs, not value: a return measure that ignores dividends understates
    # every payer in the portfolio. The dashboard's chart drops the line, not the
    # money.
    total = [round(v, 2) for v in values_divs]

    ranges = [
        _range_stat(label, dates, invested, total, index, lo, len(dates) - 1) for label, lo in _range_starts(dates) if lo < len(dates) - 1
    ]
    if window is not None:
        custom = _custom(dates, invested, total, index, window)
        if custom is not None:
            ranges.append(custom)

    return {
        "points": [{"d": d.isoformat(), "twr": round(v, 4)} for d, v in zip(dates, index)],
        "gaps": gaps,
        "ranges": ranges,
        # What a custom window needs, kept in the cache with the rest so a window
        # dragged out on the chart costs milliseconds instead of the whole history
        # again (custom_range). The router strips it from the answer.
        "_series": {"d": [d.isoformat() for d in dates], "invested": invested, "total": total, "twr": index},
    }


def _range_stat(label: str, dates: list, invested: list, total: list, index: list, lo: int, hi: int) -> dict:
    """TWR, IRR and the simple return between two indexes of the daily series."""
    days = (dates[hi] - dates[lo]).days
    # A window reaching inception has no earlier point to measure from, so
    # the first purchase counts as inleg rather than as return — the same
    # zero baseline the dashboard's rangeBreakdown uses for "All" (its
    # `base = null`), and what makes both of them agree with the hero's
    # total. Starting at index 0 instead put the first trading day's own
    # market move inside the return: EUR 20,60 on this portfolio, and a
    # denominator that was the first day's *value* where the dashboard uses
    # what was paid for it.
    base_invested = invested[lo] if lo > 0 else 0.0
    base_total = total[lo] if lo > 0 else 0.0
    contrib = round(invested[hi] - base_invested, 2)
    gain = round(total[hi] - base_total - contrib, 2)
    # total, not values: the gain above is measured on the with-dividends
    # series, so the base has to be too. Dividends banked before this window
    # opened are capital that was already at work, and leaving them out of
    # the denominator alone inflated the percentage — on a window opening
    # with EUR 500 of dividends already received, 19,00% printed as 19,95%.
    employed = base_total + max(contrib, 0.0)

    rate = irr(cash_flows(dates, invested, total, lo, hi)) if days >= MIN_IRR_DAYS else None

    return {
        "label": label,
        "from": dates[lo].isoformat(),
        "days": days,
        "twr_pct": _round(twr_over(index, lo, hi)),
        "irr_pct": _round(None if rate is None else rate * 100.0),
        "simple_pct": _round((gain / employed * 100.0) if employed > 0 else None),
        "gain_eur": gain,
        "contrib_eur": contrib,
    }


def _custom(dates: list, invested: list, total: list, index: list, window: tuple[str, str]) -> dict | None:
    """The "Custom" range: from the first day on or after the window's start to
    the last day on or before its end. None when that holds fewer than two days."""
    start, end = datetime.date.fromisoformat(window[0]), datetime.date.fromisoformat(window[1])
    lo = next((i for i, d in enumerate(dates) if d >= start), None)
    hi = next((i for i in range(len(dates) - 1, -1, -1) if dates[i] <= end), None)
    if lo is None or hi is None or hi <= lo:
        return None
    return _range_stat("Custom", dates, invested, total, index, lo, hi)


def custom_range(series: dict, window: tuple[str, str]) -> dict | None:
    """The "Custom" range from the cached `_series` of build()."""
    dates = [datetime.date.fromisoformat(d) for d in series["d"]]
    return _custom(dates, series["invested"], series["total"], series["twr"], window)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _months_before(day: datetime.date, months: int) -> datetime.date:
    """*day* shifted back by whole calendar months, clamped to month length.

    Deliberately identical to frontend/lib/dashboard.ts's addMonths, down to the
    clamping (31 March minus one month is 28 February, not 3 March), because a
    "3M" here and a "3M" there have to be the same three months. They were not:
    this file counted 91 days and the dashboard counted a quarter, so the two
    windows shared a start on 23% of days and the same label showed +8,5% on one
    tab and +6,9% on the other.
    """
    total = day.year * 12 + (day.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    next_month = datetime.date(year + month // 12, month % 12 + 1, 1)
    last_of_month = (next_month - datetime.timedelta(days=1)).day
    return datetime.date(year, month, min(day.day, last_of_month))


def _range_starts(dates: list) -> list[tuple[str, int]]:
    """(label, first index) per range, skipping any older than the portfolio.

    "All" is always index 0. The rest are the first day on or after the cutoff;
    a range that would start before the first trade is dropped rather than shown
    as a duplicate of "All".

    The cutoffs are calendar arithmetic, not day counts — see _months_before.
    This tab keeps two ranges the dashboard does not offer (3Y, 5Y), which is
    fine: a label that exists on both must mean the same window, a label that
    exists on one is its own answer.
    """
    last = dates[-1]
    cutoffs = [
        ("1M", _months_before(last, 1)),
        ("3M", _months_before(last, 3)),
        ("YTD", datetime.date(last.year, 1, 1)),
        ("1Y", _months_before(last, 12)),
        ("3Y", _months_before(last, 36)),
        ("5Y", _months_before(last, 60)),
    ]
    out = []
    for label, cutoff in cutoffs:
        if cutoff <= dates[0]:
            continue
        idx = next((i for i, d in enumerate(dates) if d >= cutoff), None)
        if idx is not None and idx < len(dates) - 1:
            out.append((label, idx))
    out.append(("All", 0))
    return out
