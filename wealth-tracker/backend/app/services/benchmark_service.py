"""
The two slow inputs behind the Benchmarks tab, cached.

app.py wraps both in @st.cache_data (app.py:57, app.py:147). The backend has no
equivalent, and these are the expensive ones: charts.fetch_benchmark_prices is
two yfinance downloads plus an FX series, and charts.build_portfolio_segments is
three more. Without a cache every chart request re-downloads all of it, and the
tab asks for three charts at once.

database.get_or_fetch stores JSON, so the pandas goes in and out through the
serialisers below — a cache has no business knowing about Series. Each pair is
round-tripped by tests/backend/tests/test_benchmark_service.py against the real
shapes, because a lossy round-trip here would not raise: it would just quietly
draw a different line.

Not wrapped in run_in_threadpool, though the plan called for it: FastAPI already
runs a non-async endpoint in its threadpool, so these are off the event loop by
the time they are reached. Wrapping again would nest a threadpool task inside a
threadpool task for no gain.
"""

import hashlib
import json
from datetime import date, datetime

import pandas as pd

from domain.portfolio import series as charts
from domain import database
from domain.i18n import tr

_PRICES_TTL_SECONDS = 3600   # app.py:57's @st.cache_data(ttl=3600)
_SEGMENTS_TTL_SECONDS = 3600  # app.py:147's


def _dump_series(prices: dict) -> dict:
    """{label: pd.Series} -> {label: {iso date: float}}."""
    return {
        label: {
            (idx.date() if hasattr(idx, "date") else idx).isoformat(): float(value)
            for idx, value in series.items()
        }
        for label, series in prices.items()
    }


def _load_series(raw: dict) -> dict:
    """The inverse. The index must come back as a DatetimeIndex: the charts
    reindex the portfolio series onto it, which silently produces all-NaN
    against plain strings."""
    return {
        label: pd.Series(
            list(points.values()),
            index=pd.DatetimeIndex([datetime.fromisoformat(d) for d in points]),
            dtype="float64",
        )
        for label, points in raw.items()
    }


def _dump_segments(segments: list) -> list:
    """[(dates, values, cfs)] -> [[[iso], [float], [float]]]."""
    return [
        [[d.isoformat() for d in dates], list(values), list(cfs)]
        for dates, values, cfs in segments
    ]


def _load_segments(raw: list) -> list:
    """The inverse. Dates return as datetime.date, which is what
    _build_portfolio_daily_series emits and what the charts compare with str()."""
    return [
        ([date.fromisoformat(d) for d in dates], list(values), list(cfs))
        for dates, values, cfs in raw
    ]


def _fingerprint(*objs) -> str:
    """A cache key over the actual inputs.

    st.cache_data hashes a function's arguments; get_or_fetch takes a key, so
    the caller has to supply the equivalent. Anything that changes the segments
    — a new transaction, a refreshed price, the bonds toggle removing an ISIN —
    changes this, so a stale line cannot survive the thing that produced it.
    """
    blob = json.dumps(objs, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def get_benchmark_prices(conn, start_date_iso: str) -> dict:
    """Daily total-return benchmark closes in EUR, from *start_date_iso*.

    Keyed on the start date alone: the fetch runs to today either way, and the
    TTL is what makes today's data current.
    """
    raw = database.get_or_fetch(
        conn,
        f"benchmarks:prices:{start_date_iso}",
        _PRICES_TTL_SECONDS,
        lambda: _dump_series(charts.fetch_benchmark_prices(start_date_iso)),
    )
    return _load_series(raw)


def get_portfolio_segments(conn, transactions: list[dict], prices: dict, dividends: list[dict]) -> list:
    """The daily TWR input series all three benchmark charts share.

    app.py:912 builds it once per rerun and hands it to each chart, which
    otherwise re-download the same history three times over. Same here — the
    charts still take `segments=` — with the cache spanning requests instead of
    one script run.
    """
    key = f"benchmarks:segments:{_fingerprint(transactions, prices, dividends)}"
    raw = database.get_or_fetch(
        conn,
        key,
        _SEGMENTS_TTL_SECONDS,
        lambda: _dump_segments(charts.build_portfolio_segments(transactions, prices, dividends)),
    )
    return _load_segments(raw)


# ---------------------------------------------------------------------------
# The three charts as data
#
# These are the derivations that used to live inside charts.py's three
# benchmark_*_chart functions, between computing the TWR index and calling
# go.Scatter. Moving them out is the same move charts.portfolio_history_series
# made for the dashboard's value card: the numbers stay in Python, where the
# rest of the arithmetic and its tests are, and only the drawing moves to the
# browser.
#
# tests/test_benchmark_series_parity.py holds these to the figures the old
# functions produced, trace for trace — a shifted day or a double-counted
# dividend still yields a plausible-looking line, so "it renders" is not a check.
# ---------------------------------------------------------------------------

PORTFOLIO_LABEL = "Portfolio (TWR)"  # shown through tr(): "Portefeuille (TWR)" in Dutch


def _points(series) -> list[dict]:
    """A pandas Series as [{d, v}], skipping the NaNs Plotly would have hidden."""
    out = []
    for ts, value in series.items():
        if value != value:  # NaN
            continue
        out.append({"d": ts.strftime("%Y-%m-%d"), "v": round(float(value), 4)})
    return out


def _chart(portfolio_points: list[dict], benchmark_points: dict[str, list[dict]], baseline: float):
    series = [{"label": tr(PORTFOLIO_LABEL), "kind": "portfolio", "points": portfolio_points}]
    series += [
        {"label": label, "kind": "benchmark", "points": pts}
        for label, pts in benchmark_points.items()
        if pts
    ]
    return {"series": series, "baseline": baseline}


def _rebase(series, start):
    """(base close, the window to draw) for a benchmark measured from *start*.

    The base is the last close **on or before** *start*, not the first one after
    it. The portfolio line carries a value for every calendar day — a Sunday or
    a 1 January holds the previous close forward — so a window opening on a
    non-trading day still has the whole of the next session's move inside it.
    Basing the benchmark on that next session instead put its first day of the
    period outside its own line while it sat inside the portfolio's, and the two
    lines then answered the question over different stretches of time: an index
    that did +4,0% since New Year drew as +0,97% against a portfolio measured in
    full. Only when nothing precedes *start* does the first later close serve as
    the base — there is nothing earlier to measure from, and both lines then
    genuinely begin together.

    Returns (None, None) when the series has nothing in range at all.
    """
    earlier = series[series.index <= start]
    window = series[series.index >= start]
    if window.empty:
        return None, None
    if earlier.empty:
        return float(window.iloc[0]), window
    # The base close itself belongs to the period before this one, so it anchors
    # the line without being drawn as a point of it.
    return float(earlier.iloc[-1]), window


def indexed_series(segments: list, benchmark_prices: dict) -> dict:
    """Portfolio TWR and each benchmark, both indexed to 100 at the start."""
    import pandas as pd

    twr = charts._compute_twr_index(segments)
    start = pd.Timestamp(segments[0][0][0])

    benchmarks: dict[str, list[dict]] = {}
    for label, raw in benchmark_prices.items():
        s = raw.dropna()
        if s.empty:
            continue
        base, window = _rebase(s, start)
        if base is None or not base:
            continue
        benchmarks[label] = _points(window / base * 100.0)

    return _chart(_points(twr), benchmarks, 100.0)


#: charts.benchmark_rolling_return_chart's own default. 91 and not 90: it is the
#: "rolling 3-month return", and three months is a quarter of 365 rounded up.
#: The parity test caught this — at 90 the line looked entirely reasonable and
#: was measuring a different window than the page says it does.
ROLLING_WINDOW_DAYS = 91


def rolling_series(
    segments: list, benchmark_prices: dict, window_days: int = ROLLING_WINDOW_DAYS
) -> dict:
    """Return over a trailing *window_days* window, as a percentage, per day."""
    twr = charts._compute_twr_index(segments)
    portfolio = (twr.asfreq("D", method="ffill").pct_change(periods=window_days) * 100).dropna()

    benchmarks: dict[str, list[dict]] = {}
    for label, raw in benchmark_prices.items():
        s = raw.dropna()
        if s.empty:
            continue
        rolling = (s.asfreq("D", method="ffill").pct_change(periods=window_days) * 100).dropna()
        if not rolling.empty:
            benchmarks[label] = _points(rolling)

    return _chart(_points(portfolio), benchmarks, 0.0)


def ytd_series(segments: list, benchmark_prices: dict, year: int) -> dict:
    """Return since 1 January of *year*, rebased so every line starts at 0%."""
    import pandas as pd

    twr = charts._compute_twr_index(segments)
    jan_1 = pd.Timestamp(year, 1, 1)

    ytd = twr[twr.index >= jan_1]
    portfolio = (ytd / float(ytd.iloc[0]) - 1.0) * 100 if not ytd.empty else ytd

    benchmarks: dict[str, list[dict]] = {}
    for label, raw in benchmark_prices.items():
        s = raw.dropna()
        # 31 December's close, which is what "since 1 January" is measured from
        # — and what the portfolio line is already measured from, since it holds
        # a value for 1 January itself. See _rebase.
        base, window = _rebase(s, jan_1)
        if base is None or not base:
            continue
        benchmarks[label] = _points((window / base - 1.0) * 100)

    return _chart(_points(portfolio), benchmarks, 0.0)
