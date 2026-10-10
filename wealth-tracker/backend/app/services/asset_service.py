"""
One asset's own price line — the chart on a position's page.

Every other chart in this app draws the *portfolio*: shares times price, summed.
This is the other question, the one you go to a position to ask — what has this
product's price done, regardless of how much of it you happen to own. So nothing
here touches transactions: it is a ticker, a stretch of days, and the closes in
between.

Two cadences, exactly as on the dashboard and for the same reason: a daily
series has two points for "today", so the 1D range comes from five-minute bars
instead (charts.portfolio_intraday_series' argument, applied to one ticker).

Both go through database.get_or_fetch, and both *raise* on a failed download so
an outage is never cached as an empty chart for the whole TTL. The public
wrappers turn the raise into an empty payload, which the page renders as "geen
koershistorie" rather than as an error — the same degradation rule the dashboard
cards follow.

Prices are Yahoo's unadjusted closes: split-adjusted (its feed already is —
checked, AAPL trades either side of its 2020 four-for-one at ~$124, not ~$500)
but not dividend-adjusted. That is the line a broker draws, and the only one
whose last point is the price printed above the chart. auto_adjust=True, which
the portfolio series use, scales every earlier close down by the dividends paid
since: right for measuring return, wrong for a price chart, and it would leave
the chart ending a few percent under the number next to it.
"""

import datetime
import sqlite3

from domain import database

#: Same hour the other price-history caches use (dashboard value history,
#: benchmark closes) — a daily close does not change within one.
_HISTORY_TTL_SECONDS = 3600

#: The bars are five-minute bars; a shorter TTL buys requests, not freshness.
_INTRADAY_TTL_SECONDS = 300


# ---------------------------------------------------------------------------
# Daily closes — every range but 1D
# ---------------------------------------------------------------------------

def _fetch_daily(ticker: str) -> dict:
    """{"points": [{d, c}]} over the ticker's whole listed history, or raises.

    period="max" rather than a window per range button: the payload is fetched
    once and sliced in the browser, so switching 1M -> All costs no request,
    and "All" then honestly means all of it. A twenty-year stock is ~5.000
    points, which is a few tens of kB over the wire and an SVG path the browser
    draws without noticing.
    """
    import yfinance as yf

    raw = yf.Ticker(ticker).history(period="max", auto_adjust=False)
    if raw is None or raw.empty or "Close" not in raw:
        raise RuntimeError(f"no history for {ticker}")
    close = raw["Close"].dropna()
    if close.empty:
        raise RuntimeError(f"empty close series for {ticker}")
    return {
        "points": [
            {"d": idx.date().isoformat(), "c": round(float(v), 4)}
            for idx, v in close.items()
        ]
    }


def daily_closes(conn: sqlite3.Connection, ticker: str | None) -> dict:
    """The asset's daily closes. Empty points when it has no ticker, or when
    Yahoo has nothing for it — both are "no chart", not an error."""
    if not ticker:
        return {"points": []}
    try:
        return database.get_or_fetch(
            conn,
            f"asset:history:{ticker}",
            _HISTORY_TTL_SECONDS,
            lambda: _fetch_daily(ticker),
        )
    except Exception:
        return {"points": []}


# ---------------------------------------------------------------------------
# Five-minute bars — the 1D range
# ---------------------------------------------------------------------------

def _fetch_intraday(ticker: str) -> dict:
    """Today's bars plus the previous session's close, or raises.

    period="2d" for the same reason the portfolio's version uses it: the
    previous close is what a day is measured against, and over a weekend or
    before the open it is the only thing there is to draw.

    Timestamps stay timezone-*aware*, normalised to UTC. The browser renders
    them in the reader's own zone; dropping the zone here is what once made an
    Amsterdam session appear to open at 07:00.
    """
    import yfinance as yf

    raw = yf.Ticker(ticker).history(period="2d", interval="5m", auto_adjust=False)
    if raw is None or raw.empty or "Close" not in raw:
        raise RuntimeError(f"no intraday data for {ticker}")

    close = raw["Close"].dropna()
    if close.empty:
        raise RuntimeError(f"empty intraday series for {ticker}")
    if getattr(close.index, "tz", None) is not None:
        close.index = close.index.tz_convert("UTC")
    close = close.sort_index()

    sessions = sorted({ts.date() for ts in close.index})
    last_session = sessions[-1]
    prev_close = None
    if len(sessions) > 1:
        earlier = close[[ts.date() < last_session for ts in close.index]]
        if not earlier.empty:
            prev_close = (
                earlier.index[-1].to_pydatetime(),
                round(float(earlier.iloc[-1]), 4),
            )

    today = close[[ts.date() == last_session for ts in close.index]]
    points = [
        {"d": ts.to_pydatetime().isoformat(timespec="minutes"), "c": round(float(v), 4)}
        for ts, v in today.items()
    ]
    # The previous close is the line's first point, not a dashed rule behind it:
    # a day drawn from the opening price leaves the overnight gap outside the
    # line, so selecting the whole chart would answer a different question than
    # the day figure above it.
    if prev_close:
        ts, value = prev_close
        points.insert(0, {"d": ts.isoformat(timespec="minutes"), "c": value})

    return {"points": points, "prev_close": prev_close[1] if prev_close else None}


def intraday_closes(
    conn: sqlite3.Connection,
    ticker: str | None,
    live_price: float | None = None,
    previous_close: float | None = None,
) -> dict:
    """Today's five-minute bars, anchored to the prices the page prints.

    *live_price* and *previous_close* come from the price cache — the same two
    numbers the header's price and day chip are built from. The bars supply the
    day's shape and these supply its endpoints, because the minute feed runs
    about a quarter of an hour behind the live quote and a chart that ends a few
    cents off the figure beside it reads as a bug. Same split as
    dashboard_service.get_intraday, and anchored outside the cache for the same
    reason: the bars are worth five minutes, a live price is not.

    The date is in the cache key so the first request after midnight cannot be
    served yesterday's bars.
    """
    if not ticker:
        return {"points": [], "prev_close": None}
    try:
        data = database.get_or_fetch(
            conn,
            f"asset:intraday:{datetime.date.today().isoformat()}:{ticker}",
            _INTRADAY_TTL_SECONDS,
            lambda: _fetch_intraday(ticker),
        )
    except Exception:
        return {"points": [], "prev_close": None}

    if not data["points"]:
        return data

    points = list(data["points"])
    if live_price is not None:
        points[-1] = {**points[-1], "c": round(float(live_price), 4)}
    # The first point *is* the previous close (see _fetch_intraday), so it moves
    # with the baseline — otherwise the line starts beside the rule drawn
    # through it.
    if previous_close is not None and data["prev_close"] is not None:
        points[0] = {**points[0], "c": round(float(previous_close), 4)}
        return {"points": points, "prev_close": round(float(previous_close), 4)}
    return {"points": points, "prev_close": data["prev_close"]}
