"""
The cockpit dashboard's data, in one place.

Everything deterministic (day-change math, dividend aggregation, the visit
diff, news classification) is a pure function over plain data so
backend/tests/test_dashboard_service.py can drive it without a network.
Everything slow or external (the value series, yfinance news, the dividend
calendar) goes through database.get_or_fetch with a key fingerprinted on the
inputs that change the answer, and degrades to an empty payload rather than an
error — a design requirement: a card with nothing to say hides itself.
"""

import datetime
import hashlib
import json
import sqlite3

from app.core import price_refresh
from app.services import benchmark_service, etf_service, news_service
from domain import database
from domain.portfolio import series as charts

# The dashboard news card mixes in the ETF look-through feed, so it needs the
# same exposure ranking the News tab's etf-top endpoint uses: the top N stocks
# from the Allocation tab's stock_list.
_ETF_TOP_N = 5

_CALENDAR_TTL_SECONDS = 43200

#: A reload within this window is the same sitting, not a new visit.
VISIT_GAP_SECONDS = 1800


def _fingerprint(*objs) -> str:
    blob = json.dumps(objs, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Hero sparkline (Tier 1)
# ---------------------------------------------------------------------------
#
# The dashboard's portfolio-vs-MSCI-World card used to live here too, as a TWR
# index against a benchmark download. It was removed with the card: TWR belongs
# on the Returns tab, where a percentage with no euro counterpart is explained
# rather than placed beside one. The endpoint, its helpers and the frontend's
# PerfChart outlived it as dead code aimed straight back at this screen; see
# git history if a benchmark ever returns to the dashboard.


def sparkline_points(segments: list, days: int = 31, today: datetime.date | None = None) -> list[dict]:
    """The hero's month-of-value line: the tail of the *last* segment only —
    across a full liquidation there is no continuous value to draw."""
    if not segments:
        return []
    today = today or datetime.date.today()
    cutoff = today - datetime.timedelta(days=days)
    seg_dates, seg_values, _ = segments[-1]
    return [
        {"d": d.isoformat() if not isinstance(d, str) else d, "v": round(float(v), 2)}
        for d, v in zip(seg_dates, seg_values)
        if (datetime.date.fromisoformat(d) if isinstance(d, str) else d) >= cutoff
    ]


def get_sparkline(conn: sqlite3.Connection, transactions, prices, dividends) -> list[dict]:
    if not transactions:
        return []
    try:
        segments = benchmark_service.get_portfolio_segments(conn, transactions, prices, dividends)
    except charts.DataUnavailable:
        # No line rather than a straight one. The hero's month-of-value spark is
        # decoration next to the figure beside it, so it hides itself here as it
        # does for a portfolio too young to have a month — but it must not
        # invent the shape, which a cost-basis fallback would draw as flat.
        return []
    return sparkline_points(segments)


# ---------------------------------------------------------------------------
# Portfolio value over time (Tier 1) — the dashboard's own-portfolio-in-EUR
# card. Same three series as the Streamlit "Portfolio value over time" chart
# (charts.portfolio_history_series), delivered as raw daily points so the
# frontend can slice by its period toggles, exactly like /performance.
# ---------------------------------------------------------------------------

_VALUE_HISTORY_TTL_SECONDS = 3600


def _build_value_history(transactions, prices, dividends) -> dict:
    estimated: list[dict] = []
    dates, invested, value, value_divs = charts.portfolio_history_series(transactions, prices, dividends, estimated=estimated)
    return {
        "points": [
            {"d": d.isoformat(), "invested": iv, "value": v, "value_divs": vd} for d, iv, v, vd in zip(dates, invested, value, value_divs)
        ],
        # Holdings whose line is a stand-in rather than a measurement. Usually
        # empty, and usually harmless when it is not (a fund listed last month
        # genuinely has no history from 2019) — but the card has to be able to
        # say so, because a substituted holding draws a flat line that reads
        # exactly like a real one that did not move.
        "estimated": estimated,
    }


def get_value_history(conn: sqlite3.Connection, transactions, prices, dividends) -> dict:
    """Daily invested / value / value+dividends in EUR since the first trade.

    Cached on a fingerprint of the inputs (the series builder runs a yfinance
    history download), so toggling ranges costs nothing and it is only recomputed
    after the TTL or when a transaction/price/dividend actually changes it.

    `unavailable` when the closes could not be fetched. Caught outside
    get_or_fetch on purpose: the raise is what keeps the failure out of the
    cache, so the next request after the network returns builds a real chart
    instead of being served an hour-old apology.
    """
    if not transactions:
        return {"points": [], "estimated": []}
    key = f"dashboard:value-history:{_fingerprint(transactions, prices, dividends)}"
    try:
        return database.get_or_fetch(
            conn,
            key,
            _VALUE_HISTORY_TTL_SECONDS,
            lambda: _build_value_history(transactions, prices, dividends),
        )
    except charts.DataUnavailable:
        return {"points": [], "estimated": [], "unavailable": True}


def pin_to_total(history: dict, positions: list[dict], total_value: float) -> dict:
    """The value history with today's point set to the hero's total value.

    The hero and the card measured the same portfolio with two price sources:
    the hero the price cache (Tradegate's own price for a TDG position, this
    morning's refresh), the card Yahoo's daily closes (XETRA for that position,
    and on 2026-09-24 still the 22nd for every European ticker, because Yahoo
    had not published the 23rd yet). Same inleg, same dividends, and still
    Totaalrendement +34,8% above Waardeontwikkeling +35,3%. The hero is the
    fresher answer, so the card ends on it; the closes keep drawing every
    earlier day, which nothing else can.

    Only when every open position has a price: the hero leaves an unpriced one
    out of its total while the series values it at cost, so pinning then would
    draw a cliff the size of that position on the last day. And only when the
    last point is today — an older one is a different day's value.

    Outside get_value_history's cache on purpose, like the intraday anchors:
    the series is worth an hour, the live total is not.
    """
    points = history.get("points") or []
    if not points or points[-1]["d"] != datetime.date.today().isoformat():
        return history
    if not positions or any(p.get("current_value") is None for p in positions):
        return history
    last = points[-1]
    dividends = last["value_divs"] - last["value"]
    pinned = {
        **last,
        "value": round(total_value, 2),
        "value_divs": round(total_value + dividends, 2),
    }
    return {**history, "points": [*points[:-1], pinned]}


# The 1D range's shape, which the daily series cannot supply: it has two points
# for a day. Five minutes of TTL — the bars themselves are 5-minute bars, so a
# shorter one buys nothing but requests.
_INTRADAY_TTL_SECONDS = 300


def _build_intraday(transactions, prices) -> dict:
    stamps, values, prev_close = charts.portfolio_intraday_series(transactions, prices)
    points = [{"d": ts.isoformat(timespec="minutes"), "value": v} for ts, v in zip(stamps, values)]
    # The previous close is the line's first point, not just a dashed rule behind
    # it. A day measured from the opening price leaves the overnight gap outside
    # the line, so selecting the whole chart answered a different question than
    # the figure above it: +€116,61 from the open against +€79,19 for the day.
    if prev_close:
        ts, value = prev_close
        points.insert(0, {"d": ts.isoformat(timespec="minutes"), "value": value})
    return {"points": points, "prev_close": prev_close[1] if prev_close else None}


def _day_anchors(positions: list[dict], prices: dict[str, dict]) -> tuple[float, float] | None:
    """(value at the previous close, value now) — the hero chip's two endpoints.

    The hero reads the price cache, the intraday bars come from yfinance's
    5-minute feed, and the daily series from yfinance's daily closes. Three
    sources for one question, and they disagreed by a few euros: the card said
    the day was +€74,28 while the chip above it said +€79,19, mostly because the
    minute feed runs about a quarter of an hour behind the live price.

    So the bars supply the *shape* of the day and these two supply its
    *endpoints*. None unless every position is EUR-priced with a previous close
    — a partial sum anchored to a full one would be worse than not anchoring —
    and unless the quotes are from today: bars from this morning pinned to
    yesterday's cache is not one answer, it is two, joined by a cliff at the end
    of the line the size of everything the market did since. Prices refresh
    themselves during market hours now (app/core/price_refresh.py), so a stale
    cache means something is broken, and the honest thing then is to draw no
    anchored day at all.
    """
    if not positions:
        return None
    today = datetime.date.today().isoformat()
    prev_total = 0.0
    live_total = 0.0
    for p in positions:
        info = prices.get(p["isin"])
        if not info or info.get("currency") != "EUR":
            return None
        if (info.get("fetched_at") or "")[:10] != today:
            return None
        prev = info.get("previous_close")
        cur = info.get("price")
        if not prev or prev <= 0 or not cur:
            return None
        prev_total += prev * p["shares_held"]
        live_total += cur * p["shares_held"]
    return round(prev_total, 2), round(live_total, 2)


def get_intraday(conn: sqlite3.Connection, transactions, prices, positions=None) -> dict:
    """Today's portfolio value per 5 minutes, plus the previous session's close.

    Not fingerprinted on `prices`: those are refreshed on their own schedule and
    would evict this on every tick, for a series that does not depend on them
    beyond the ISIN→ticker map. The date is in the key instead, so the first
    request after midnight cannot be served yesterday's bars.

    Empty `points` when there is nothing intraday to show — a holiday, a
    portfolio yfinance has no minute bars for, a failed download. The card falls
    back to the daily series then, rather than showing an empty 1D.

    `anchored` says whether the two endpoints are the chip's (see _day_anchors).
    False means the line is the minute feed's own reading of the day, which is a
    *second* answer to a question that has one — so the card does not draw it,
    and falls back as it does on a holiday. The bars stay in the payload
    regardless: the visit strip reads their timestamps to find the gap between
    two sessions, and those are right whether or not the cache is current.
    """
    if not transactions:
        return {"points": [], "prev_close": None, "anchored": False}
    tickers = sorted(p.get("ticker") for p in prices.values() if p.get("ticker"))
    key = f"dashboard:intraday:{datetime.date.today().isoformat()}:{_fingerprint(transactions, tickers)}"
    data = database.get_or_fetch(
        conn,
        key,
        _INTRADAY_TTL_SECONDS,
        lambda: _build_intraday(transactions, prices),
    )

    # Anchored outside the cache, deliberately: the bars are worth caching for
    # five minutes, the live price is not — baking it in would let the card
    # disagree with the chip above it until the entry expired.
    anchors = _day_anchors(positions or [], prices)
    if anchors and data["points"]:
        prev_close, live = anchors
        points = list(data["points"])
        points[-1] = {**points[-1], "value": live}
        # The first point *is* the previous close (see _build_intraday), so it
        # moves with the baseline — otherwise the line would start a few euros
        # off the rule drawn through it. Without one, only the far end is the
        # chip's and the day would be measured from the open: not anchored.
        if data["prev_close"] is None:
            return {**data, "anchored": False}
        points[0] = {**points[0], "value": prev_close}
        return {"points": points, "prev_close": prev_close, "anchored": True}
    return {**data, "anchored": False}


# ---------------------------------------------------------------------------
# Day change (Tier 2 — previous_close)
# ---------------------------------------------------------------------------


def position_day_changes(positions: list[dict], prices: dict[str, dict]) -> list[dict]:
    """Per open position: today's move, where previous_close is known.

    Only EUR-priced positions take part, for the same reason
    calculate_positions drops non-EUR prices: a EUR delta cannot be built from
    a foreign-currency pair.
    """
    rows = []
    for p in positions:
        info = prices.get(p["isin"])
        if not info or info.get("currency") != "EUR":
            continue
        prev = info.get("previous_close")
        cur = info.get("price")
        if not prev or prev <= 0 or not cur:
            continue
        rows.append(
            {
                "isin": p["isin"],
                "name": p["name"],
                "ticker": p.get("ticker"),
                "day_delta_eur": round((cur - prev) * p["shares_held"], 2),
                "day_pct": round((cur / prev - 1.0) * 100.0, 2),
            }
        )
    return rows


def portfolio_day_change(positions: list[dict], prices: dict[str, dict]) -> dict | None:
    """The hero chip: today's € and % move over the whole portfolio.

    None when nothing has a previous close (pre-migration data, or prices
    never refreshed since) — the chip hides rather than claims 0,00%.

    `as_of` is the *oldest* quote in the sum and `stale` says whether that one
    has missed a close. Both are here because this function used to read price
    against previous_close without ever asking when either was fetched: with a
    four-day-old cache it happily reported "+€75,00 · today", complete and
    unqualified, over a move that happened last week. _day_anchors, ten lines
    up and fed by the same two numbers, refuses to anchor that same cache — so
    the card said "I cannot tell you" while the chip directly above it did.
    Reported rather than hidden: a chip that vanishes raises a question the
    screen cannot answer, while a marked one names its own problem.

    `market_closed` is the other half of that question. Staleness asks whether
    the cache kept up; this asks whether there was anything to keep up *with*.
    On a Saturday the newest quote in existence is Friday's close against
    Thursday's — a perfectly fresh cache, and a move that belongs to Friday. The
    chip used to print it under the word "today". So on any date the exchange
    has not traded, the day's figures are zero, which is what actually happened
    to the portfolio today, and the frontend says why.
    """
    per_position = position_day_changes(positions, prices)
    if not per_position:
        return None
    if not price_refresh.traded_today():
        fetched = [(prices.get(r["isin"]) or {}).get("fetched_at") for r in per_position]
        return {
            "delta_eur": 0.0,
            "pct": 0.0,
            "complete": True,
            "as_of": min((f for f in fetched if f), default=None),
            # Nothing to be behind on: the label the frontend prints is
            # "market closed", and a staleness warning beside it would be a
            # second, contradictory account of the same silence.
            "stale": False,
            "market_closed": True,
        }
    delta = sum(r["day_delta_eur"] for r in per_position)
    base = 0.0
    for p in positions:
        info = prices.get(p["isin"])
        if info and info.get("currency") == "EUR" and info.get("previous_close"):
            base += info["previous_close"] * p["shares_held"]
    priced = [p for p in positions if p.get("current_value") is not None]
    fetched = [(prices.get(r["isin"]) or {}).get("fetched_at") for r in per_position]
    as_of = min((f for f in fetched if f), default=None)
    return {
        "delta_eur": round(delta, 2),
        "pct": round(delta / base * 100.0, 2) if base > 0 else 0.0,
        # False when some positions could not join the sum — the chip still
        # shows, but the frontend can qualify it.
        "complete": len(per_position) == len(priced) and len(priced) == len(positions),
        "as_of": as_of,
        "stale": price_refresh.is_stale(as_of),
        "market_closed": False,
    }


def day_movers(positions: list[dict], prices: dict[str, dict]) -> dict:
    """Biggest riser/faller by today's %; the loser only exists as a
    distinct row (a one-position portfolio has no 'daler').

    Empty on a day the exchange did not trade, for the same reason the chip
    reads zero there (see portfolio_day_change): the biggest riser of a session
    that has not happened is Friday's, and the Attention block would be pointing
    at it under the word "today".
    """
    if not price_refresh.traded_today():
        return {"top": None, "bottom": None}
    rows = position_day_changes(positions, prices)
    if not rows:
        return {"top": None, "bottom": None}
    top = max(rows, key=lambda r: r["day_pct"])
    bottom = min(rows, key=lambda r: r["day_pct"])
    return {"top": top, "bottom": bottom if bottom is not top else None}


# ---------------------------------------------------------------------------
# Dividend aggregation (Tier 1)
# ---------------------------------------------------------------------------


def dividend_stats(dividends: list[dict], today: datetime.date | None = None) -> dict:
    """'This month' and 'this year' as the calendar reads them, net EUR."""
    today = today or datetime.date.today()
    month_prefix = today.isoformat()[:7]
    year_prefix = today.isoformat()[:4]
    this_month = sum(d["net_eur"] for d in dividends if d.get("date", "").startswith(month_prefix) and d.get("net_eur") is not None)
    this_year = sum(d["net_eur"] for d in dividends if d.get("date", "").startswith(year_prefix) and d.get("net_eur") is not None)
    return {"this_month": round(this_month, 2), "this_year": round(this_year, 2)}


def dividends_since(dividends: list[dict], since_iso: str) -> dict:
    """Payments strictly after *since_iso*'s date — the visit strip's
    '1 dividend paid'.
    """
    since_date = since_iso[:10]
    paid = [d for d in dividends if d.get("date") and d["date"][:10] > since_date and d.get("net_eur") is not None]
    return {"count": len(paid), "total_eur": round(sum(d["net_eur"] for d in paid), 2)}


# ---------------------------------------------------------------------------
# Visit snapshots (Tier 2)
# ---------------------------------------------------------------------------


def record_visit(
    conn: sqlite3.Connection,
    total_value: float | None,
    now: datetime.datetime | None = None,
    gap_seconds: int = VISIT_GAP_SECONDS,
) -> dict | None:
    """Registers this page load and returns the previous session to diff
    against, or None when there is nothing meaningful to say.

    A run of loads under *gap_seconds* apart is one session; its row keeps
    absorbing loads (last_seen_at/last_value move forward), so the *previous*
    row always holds what the user saw when they last left.
    """
    now = now or datetime.datetime.now()
    now_iso = now.isoformat(timespec="seconds")
    visits = database.load_recent_visits(conn, 2)
    current = visits[0] if visits else None

    same_session = False
    if current:
        try:
            last_seen = datetime.datetime.fromisoformat(current["last_seen_at"])
            same_session = (now - last_seen).total_seconds() <= gap_seconds
        except ValueError:
            pass

    if same_session:
        previous = visits[1] if len(visits) > 1 else None
        # Never overwrite a known value with None: a temporarily price-less
        # load must not erase what the user actually last saw.
        database.touch_visit(
            conn,
            current["id"],
            now_iso,
            total_value if total_value is not None else current["last_value"],
        )
    else:
        previous = current
        database.insert_visit(conn, now_iso, total_value)

    if previous is None or previous["last_value"] is None or total_value is None:
        return None
    return {
        "last_seen_at": previous["last_seen_at"],
        "value_then": round(previous["last_value"], 2),
        "value_delta": round(total_value - previous["last_value"], 2),
    }


def previous_close_at(intraday: dict) -> datetime.datetime | None:
    """When the previous session closed, from the bar the intraday line starts at.

    Read off the data rather than off a hardcoded 17:30: a portfolio can hold
    Frankfurt and New York at once, and a holiday simply has no bar.
    """
    if not intraday.get("points") or intraday.get("prev_close") is None:
        return None
    try:
        return datetime.datetime.fromisoformat(intraday["points"][0]["d"])
    except (ValueError, KeyError, TypeError):
        return None


def session_start_at(intraday: dict) -> datetime.datetime | None:
    """When the running session opened — the second bar of the line.

    The first point is the previous close, prepended by _build_intraday, so the
    one after it is the first bar of the session the chip is measuring. Read off
    the data for the same reason previous_close_at is: opening times differ per
    venue and a holiday has no bar to read.
    """
    if previous_close_at(intraday) is None or len(intraday.get("points", [])) < 2:
        return None
    try:
        return datetime.datetime.fromisoformat(intraday["points"][1]["d"])
    except (ValueError, KeyError, TypeError):
        return None


def align_visit_with_the_day(diff: dict, prev_close_at, session_start, day: dict | None) -> dict:
    """Reports today's change when a visit sits in the gap between two sessions.

    The snapshot a visit stores is the portfolio as the price cache had it at
    that moment. The day chip measures from `previous_close`. Those are two
    fields of the same feed describing the same session close, and they do not
    quite agree — a visit at 22:57 recorded €13.878,12 where the chip's baseline
    for the same close reads €13.873,22. So the strip said the portfolio moved
    €74,28 since last night under a chip saying €79,19 for today, and there was
    no way to tell which €5 was missing.

    The window is exact rather than clock-based, and it is bounded on both
    sides: *prev_close_at* is the previous session's last bar and *session_start*
    the current session's first, so a visit between them saw a shut market and
    has exactly one session — the running one — behind it. That is precisely
    when the chip is the answer.

    Both bounds matter. Without the lower one every older visit would be handed
    today's move; without the upper one a visit from 11:00 this morning would be
    too, and half a session is not a day. Weekends and holidays need no special
    case: a session that did not happen has no bars, so a Saturday visit lands
    after the last session's start and keeps its own snapshot.

    Calendar dates deliberately play no part. "Yesterday evening" and "at 08:00
    this morning, before the open" are the same position relative to the market,
    and the strip has to answer both the same way — gating on the date instead
    let the morning case slip back to two numbers for one day.
    """
    if not diff or not day or prev_close_at is None:
        return diff
    try:
        seen = datetime.datetime.fromisoformat(diff["last_seen_at"])
    except (ValueError, TypeError):
        return diff
    # The bars are tz-aware UTC, the visit is naive local time. Comparing them
    # needs one of the two converted, and the visit is the one whose zone is
    # known: it was written by this process.
    close_local = prev_close_at.astimezone().replace(tzinfo=None)
    if seen <= close_local:
        return diff
    if session_start is not None and seen > session_start.astimezone().replace(tzinfo=None):
        return diff
    return {
        **diff,
        "value_delta": day["delta_eur"],
        "value_then": round(diff["value_then"] + diff["value_delta"] - day["delta_eur"], 2),
    }


# ---------------------------------------------------------------------------
# News (Tier 3)
# ---------------------------------------------------------------------------
#
# The dashboard's "Laatste nieuws" card is a teaser for the News tab's
# Dashboard news card: holdings + ETF look-through + market news, merged into
# one feed (news_service owns all fetching, provider merging and classification).
# The card falls back through all three so it stays populated for an ETF-only
# portfolio, whose holdings feed is empty on its own. Ranking the ETF-top slice
# needs the exposure data, hence the etf_service call — same as the News tab.


def get_news(conn: sqlite3.Connection, positions: list[dict]) -> list[dict]:
    exposure = etf_service.get_exposure(conn, positions)
    top_stocks = exposure.get("stock_list", [])[:_ETF_TOP_N]
    return news_service.get_combined_news(conn, positions, top_stocks)


# ---------------------------------------------------------------------------
# Ex-dividend calendar (Tier 3)
# ---------------------------------------------------------------------------


def latest_dividend_by_isin(dividends: list[dict]) -> dict[str, float]:
    """{isin: net EUR of the most recent payment date} — the 'verwacht'
    estimate for the next one. Multiple rows on that date sum (one gross/tax
    pair can arrive as several lines)."""
    latest_date: dict[str, str] = {}
    totals: dict[str, float] = {}
    for d in dividends:
        isin, date = d.get("isin"), d.get("date")
        if not isin or not date or d.get("net_eur") is None:
            continue
        if isin not in latest_date or date > latest_date[isin]:
            latest_date[isin] = date
            totals[isin] = d["net_eur"]
        elif date == latest_date[isin]:
            totals[isin] += d["net_eur"]
    return {isin: round(v, 2) for isin, v in totals.items()}


#: Wall-clock budget for one calendar sweep, in seconds. Each yf.Ticker().calendar
#: takes about 30s to give up when the network stalls (yfinance's cookie
#: bootstrap ignores any timeout it is given), and this loop is serial over every
#: position, on the request thread of GET /api/dashboard/dividends. Twenty
#: holdings is ten minutes of a browser tab spinning against a card that is
#: usually empty anyway — the official calendar carries nothing for UCITS ETFs,
#: which is why the forecast below exists. A cut-off sweep is cached as normal:
#: what it did find is true, and `raise` below still covers the total failure.
_CALENDAR_BUDGET_SECONDS = 25.0


def _fetch_calendar(
    tickers_to_meta: dict[str, tuple[str, str]],
    budget_seconds: float = _CALENDAR_BUDGET_SECONDS,
) -> list[dict]:
    """[{isin, ticker, name, ex_date, pay_date, earnings_dates}] for tickers
    whose calendar carries either an ex-dividend date or a reporting date —
    past ones included; the caller filters to upcoming so the cache stays valid
    as days pass.

    One Yahoo call answers both questions, so the Calendar tab's reporting dates
    ride along on the sweep the dividend card was already paying for: no second
    request, no second budget, nothing extra to go wrong on a bad network.

    `Earnings Date` comes back as a *list*. One entry is a date the company has
    confirmed; two are the ends of a window Yahoo is guessing at. Both are kept,
    with the distinction, because the calendar renders them differently — a
    window has no business sitting in a day cell.
    """
    import time

    import yfinance as yf

    def _iso(value) -> str | None:
        if value is None:
            return None
        return value.isoformat()[:10] if hasattr(value, "isoformat") else str(value)[:10]

    entries = []
    errors = 0
    attempted = 0
    started = time.monotonic()
    for ticker, (isin, name) in tickers_to_meta.items():
        if time.monotonic() - started > budget_seconds:
            break
        attempted += 1
        try:
            cal = yf.Ticker(ticker).calendar or {}
        except Exception:
            errors += 1
            continue
        ex = cal.get("Ex-Dividend Date")
        raw_earnings = cal.get("Earnings Date") or []
        if not isinstance(raw_earnings, (list, tuple)):
            raw_earnings = [raw_earnings]
        earnings = [d for d in (_iso(d) for d in raw_earnings) if d]
        if not ex and not earnings:
            continue
        pay = cal.get("Dividend Date")
        entries.append(
            {
                "isin": isin,
                "ticker": ticker,
                "name": name,
                "ex_date": _iso(ex),
                "pay_date": _iso(pay),
                "earnings_dates": earnings,
            }
        )
    # Measured against what was *attempted*, not against the whole dict. With
    # the budget above, a stalled network gets through only the first ticker or
    # two before the sweep is cut off, so `errors == len(tickers_to_meta)` would
    # no longer hold and an empty result would have been cached for twelve
    # hours — the outage outliving itself, which is the thing this raise exists
    # to prevent.
    #
    # `errors > 0` is gone with it, so a sweep that got through nothing at all
    # raises too. Nothing attempted is not the same as nothing found: the first
    # is ignorance and must not be stored, the second is an answer and should
    # be. A fund with no ex-dividend date on file leaves entries empty with
    # errors at zero, which is exactly the case this still lets through.
    if not entries and errors == attempted:
        raise RuntimeError("calendar sweep learned nothing")
    return entries


def upcoming_ex_dividends(entries: list[dict], estimates: dict[str, float], today: datetime.date | None = None) -> list[dict]:
    today = today or datetime.date.today()
    upcoming = [
        {**e, "estimate_eur": estimates.get(e["isin"])} for e in entries if e.get("ex_date") and e["ex_date"][:10] >= today.isoformat()
    ]
    upcoming.sort(key=lambda e: e["ex_date"])
    return upcoming


def get_calendar_entries(conn: sqlite3.Connection, positions: list[dict]) -> list[dict]:
    """The cached Yahoo calendar sweep — ex-dividend *and* reporting dates.

    Two callers share this one sweep and its one cache entry: the dashboard's
    ex-dividend card (via get_ex_dividends below) and the Calendar tab. Opening
    the calendar therefore costs nothing on top of a dashboard the user has
    already loaded, which matters because the sweep is the slow part of both.

    Every reporting date that comes back is written to `earnings_dates` on the
    way through, on a cache hit too: the upsert is a handful of rows against a
    local table, and doing it only on a miss would mean a date could pass out
    of Yahoo's feed during a cached stretch and never be written down at all.
    """
    meta = {p["ticker"]: (p["isin"], p.get("name")) for p in positions if p.get("ticker")}
    if not meta:
        return []
    # `cal` rather than the old `exdiv`: the payload gained earnings_dates, and
    # a key that outlives a shape change serves the old shape until its TTL is
    # up. Renaming it is the cheapest possible migration — the stale rows age
    # out on their own and nothing reads them in the meantime.
    key = f"dashboard:cal:{_fingerprint(sorted(meta))}"
    try:
        entries = database.get_or_fetch(conn, key, _CALENDAR_TTL_SECONDS, lambda: _fetch_calendar(meta))
    except Exception:
        return []
    try:
        database.record_earnings_dates(
            conn,
            [
                {"isin": e["isin"], "date": d, "confirmed": len(e.get("earnings_dates") or []) == 1}
                for e in entries
                for d in (e.get("earnings_dates") or [])
            ],
        )
    except Exception:
        pass  # remembering is a nicety; failing to must not take the tab down
    return entries


def get_ex_dividends(conn: sqlite3.Connection, positions: list[dict], dividends: list[dict]) -> list[dict]:
    entries = get_calendar_entries(conn, positions)
    if not entries:
        return []
    return upcoming_ex_dividends(entries, latest_dividend_by_isin(dividends))


# ---------------------------------------------------------------------------
# Dividend forecast from the user's own payment history
#
# The official calendar above covers almost nothing here: UCITS ETFs have no
# forward data on Yahoo (verified: every fund 404s), so the portfolio's own
# DeGiro payment history is the engine. It is a *estimate* — expected timing at
# month precision and a typical amount — and the payload says so (`source:
# "estimate"`); an official upcoming ex-div, when one exists, overrides the
# estimate for that holding and is labeled "official". Entirely
# deterministic: no network, tested in test_dashboard_service.py.
# ---------------------------------------------------------------------------

#: (key, days, Dutch label, months). A payment rhythm is snapped to the nearest
#: of these; anything further than _CADENCE_TOLERANCE off all of them is "no
#: recognisable rhythm" and the holding is omitted rather than guessed at.
#:
#: `days` measures an observed rhythm — gaps between real payments come in days,
#: and that is what the match is made on. `months` projects one forward, because
#: a schedule stepped in days does not tile a year: twelve 30-day steps are 360
#: days, leaving five days a thirteenth payment could fall into, so a monthly
#: payer's "next 12 months" read EUR 130 where a year holds EUR 120 — and
#: only on some days of the month, so the figure changed on its own between two
#: visits. Stepping in calendar months makes a year exactly twelve payments and
#: keeps the estimate on the day of the month the fund actually pays, instead of
#: creeping five days earlier each year.
_CADENCES = [
    ("monthly", 30, "monthly", 1),
    ("quarterly", 91, "quarterly", 3),
    ("semiannual", 182, "semiannual", 6),
    ("annual", 365, "annual", 12),
]
_CADENCE_TOLERANCE = 0.25  # |median gap - cadence| / cadence

_FORECAST_HORIZON_DAYS = 190  # "coming months": ~6 months of expected payments
_AMOUNT_WINDOW = 4  # typical amount = median of this many recent payments


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def payment_events(dividends: list[dict]) -> dict[str, list[tuple[datetime.date, float]]]:
    """{isin: [(date, net EUR)] ascending}, with same-day rows summed — one
    DeGiro payment can arrive as several lines (gross/tax split)."""
    by_isin: dict[str, dict[datetime.date, float]] = {}
    for d in dividends:
        isin, date_str = d.get("isin"), d.get("date")
        if not isin or not date_str or d.get("net_eur") is None:
            continue
        try:
            day = datetime.date.fromisoformat(date_str[:10])
        except ValueError:
            continue
        by_isin.setdefault(isin, {})
        by_isin[isin][day] = by_isin[isin].get(day, 0.0) + d["net_eur"]
    return {isin: sorted(days.items()) for isin, days in by_isin.items()}


def _add_months(day: datetime.date, months: int) -> datetime.date:
    """*day* shifted by whole calendar months, clamped to the month's length.

    Always applied to the original payment date rather than to the previous
    estimate, so a fund paying on the 31st does not walk back to the 28th via
    February and stay there.
    """
    total = day.year * 12 + (day.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    if month == 12:
        last = 31
    else:
        last = (datetime.date(year + month // 12, month % 12 + 1, 1) - datetime.timedelta(days=1)).day
    return datetime.date(year, month, min(day.day, last))


def detect_cadence(dates: list[datetime.date]) -> tuple[str, int, str, int] | None:
    """The payment rhythm behind *dates* (ascending), or None.

    The median gap decides — robust against one delayed payment — and must
    sit within 25% of a known cadence. A 50-day median matches nothing and
    returns None: an irregular payer gets no forecast at all, per the honesty
    bar (omit rather than guess).
    """
    if len(dates) < 2:
        return None
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    med = _median([float(g) for g in gaps])
    if med <= 0:
        return None
    best = min(_CADENCES, key=lambda c: abs(med - c[1]) / c[1])
    if abs(med - best[1]) / best[1] > _CADENCE_TOLERANCE:
        return None
    return best


def _detect_alternating(events: list[tuple[datetime.date, float]]) -> dict | None:
    """Semi-annual payers with an uneven interim/final split — NN Group pays
    ~aug and ~jun, so its gaps alternate ~76/~275 days and the *median* gap
    matches no single cadence. Requires >= 3 gaps whose adjacent pairs each
    span roughly a year and whose two phases each cluster tightly; returns
    the two gap lengths keyed by parity, where the NEXT gap has parity 0.
    """
    dates = [d for d, _ in events]
    if len(dates) < 4:
        return None
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    n = len(gaps)
    # Gap i gets parity (n - i) % 2, so the upcoming gap (index n) is parity 0.
    by_parity: dict[int, list[int]] = {0: [], 1: []}
    for i, g in enumerate(gaps):
        by_parity[(n - i) % 2].append(g)
    if not by_parity[0] or not by_parity[1]:
        return None
    med0 = _median([float(g) for g in by_parity[0]])
    med1 = _median([float(g) for g in by_parity[1]])
    if abs(med0 - med1) <= 45:
        return None  # that is one rhythm with jitter — detect_cadence territory
    if any(abs(g - med0) > 45 for g in by_parity[0]) or any(abs(g - med1) > 45 for g in by_parity[1]):
        return None
    if any(not (273 <= a + b <= 456) for a, b in zip(gaps, gaps[1:])):
        return None  # interim + final must add up to about a year
    return {"gap_by_parity": {0: int(round(med0)), 1: int(round(med1))}}


def _month_part(day: int) -> str:
    """Month-level honesty: 'early'/'mid'/'late', never an exact day."""
    if day <= 10:
        return "early"
    if day <= 20:
        return "mid"
    return "late"


def _shares_held_at(transactions: list[dict], isin: str, on_date: datetime.date) -> float:
    held = 0.0
    for t in transactions:
        if t.get("isin") != isin or not t.get("date") or t["date"][:10] > on_date.isoformat():
            continue
        qty = t.get("quantity") or 0.0
        if t.get("transaction_type") == "BUY":
            held += qty
        elif t.get("transaction_type") == "SELL":
            held -= qty
    return max(held, 0.0)


def _expected_amount(
    events: list[tuple[datetime.date, float]],
    isin: str,
    current_shares: float | None,
    transactions: list[dict] | None,
) -> float:
    """A robust typical payment: median of the recent ones — scaled per share
    when the position size at those pay dates is known and current holdings
    differ (buying more shares raises the next payment; the raw history alone
    would keep predicting the old, smaller amount)."""
    recent = events[-_AMOUNT_WINDOW:]
    amounts = [amt for _, amt in recent]
    if transactions and current_shares and current_shares > 0:
        per_share = []
        for day, amt in recent:
            shares_then = _shares_held_at(transactions, isin, day)
            if shares_then <= 0:
                per_share = []
                break
            per_share.append(amt / shares_then)
        if per_share:
            return _median(per_share) * current_shares
    return _median(amounts)


def forecast_dividends(
    positions: list[dict],
    dividends: list[dict],
    transactions: list[dict] | None = None,
    today: datetime.date | None = None,
    horizon_days: int = _FORECAST_HORIZON_DAYS,
) -> dict:
    """Expected payments over the coming months, from payment history alone.

    Per still-held ISIN with a recognisable cadence: the schedule continues
    from the last real payment (rolled forward in whole cadence steps until
    >= today), each occurrence carrying the typical recent amount. Holdings
    that are sold, accumulating (no distribution history), single-payment or
    irregular are omitted — no noise. Also returns the remainder-of-year
    total the same schedule implies.
    """
    today = today or datetime.date.today()
    held = {p["isin"]: p for p in positions}
    year_end = datetime.date(today.year, 12, 31)
    horizon_end = today + datetime.timedelta(days=horizon_days)

    upcoming: list[dict] = []
    rest_of_year = 0.0

    def emit(isin: str, position: dict, occurrence: datetime.date, amount: float, label: str, confidence: str) -> None:
        nonlocal rest_of_year
        if occurrence <= year_end:
            rest_of_year += amount
        if occurrence <= horizon_end:
            upcoming.append(
                {
                    "isin": isin,
                    "name": position.get("name"),
                    "date": occurrence.isoformat(),
                    "month": occurrence.isoformat()[:7],
                    "part": _month_part(occurrence.day),
                    "expected_eur": amount,
                    "cadence": label,
                    "confidence": confidence,
                    "source": "estimate",
                }
            )

    for isin, events in payment_events(dividends).items():
        position = held.get(isin)
        if position is None:
            continue  # sold out: their schedule ended with the position
        shares = position.get("shares_held")
        end = max(horizon_end, year_end)
        cadence = detect_cadence([d for d, _ in events])

        if cadence is not None:
            key, days, label, months = cadence
            gaps = [(b - a).days for (a, _), (b, _) in zip(events, events[1:])]
            regular = all(abs(g - days) / days <= 0.2 for g in gaps[-3:])
            if len(events) >= 5 and regular:
                confidence = "high"
            elif len(events) >= 3:
                confidence = "medium"
            else:
                confidence = "low"

            amount = round(_expected_amount(events, isin, shares, transactions), 2)
            if amount <= 0:
                continue

            # Roll the schedule forward from the last real payment to >= today,
            # in whole calendar months and always measured off that same anchor
            # (see _add_months).
            anchor = events[-1][0]
            step = 1
            nxt = _add_months(anchor, months)
            while nxt < today:
                step += 1
                nxt = _add_months(anchor, months * step)
            while nxt <= end:
                emit(isin, position, nxt, amount, label, confidence)
                step += 1
                nxt = _add_months(anchor, months * step)
            continue

        alternating = _detect_alternating(events)
        if alternating is None:
            continue  # 1 payment or no recognisable rhythm: omitted, not guessed

        # Interim/final payer: the amount belongs to the phase — a final can
        # be twice the interim, so each occurrence takes the typical payment
        # of *its own* phase (per-share scaled like everything else).
        gap_by_parity = alternating["gap_by_parity"]
        n = len(events) - 1
        phase_events: dict[int, list] = {0: [], 1: []}
        for i in range(n):
            phase_events[(n - i) % 2].append(events[i + 1])
        amount_by_parity = {
            p: round(_expected_amount(evs, isin, shares, transactions), 2) if evs else 0.0 for p, evs in phase_events.items()
        }

        parity = 0  # the gap after the last real payment has parity 0
        nxt = events[-1][0] + datetime.timedelta(days=gap_by_parity[0])
        while nxt < today:
            parity ^= 1
            nxt += datetime.timedelta(days=gap_by_parity[parity])
        while nxt <= end:
            if amount_by_parity[parity] > 0:
                emit(isin, position, nxt, amount_by_parity[parity], "semiannual", "medium")
            parity ^= 1
            nxt += datetime.timedelta(days=gap_by_parity[parity])

    upcoming.sort(key=lambda e: (e["date"], e["isin"]))
    return {"upcoming": upcoming, "rest_of_year_eur": round(rest_of_year, 2)}


def merge_official_ex_dividends(forecast: dict, official: list[dict]) -> dict:
    """Where a real upcoming ex-div exists (rare here — one stock at best),
    the official date replaces the holding's first estimated occurrence and
    is labeled so; the estimate keeps supplying the amount, since the
    calendar has none. A holding with an official date but no forecastable
    history still gets a row — a real date beats silence."""
    if not official:
        return forecast
    upcoming = list(forecast["upcoming"])
    for entry in official:
        isin = entry.get("isin")
        ex_date = (entry.get("ex_date") or "")[:10]
        if not isin or not ex_date:
            continue
        day = datetime.date.fromisoformat(ex_date)
        replacement = {
            "isin": isin,
            "name": entry.get("name"),
            "date": ex_date,
            "month": ex_date[:7],
            "part": _month_part(day.day),
            "cadence": None,
            "confidence": "high",
            "source": "official",
            "expected_eur": entry.get("estimate_eur"),
        }
        mine = [i for i, e in enumerate(upcoming) if e["isin"] == isin]
        if mine:
            first = mine[0]
            replacement["cadence"] = upcoming[first]["cadence"]
            replacement["expected_eur"] = upcoming[first]["expected_eur"]
            replacement["name"] = upcoming[first]["name"] or replacement["name"]
            upcoming[first] = replacement
        else:
            upcoming.append(replacement)
    upcoming.sort(key=lambda e: (e["date"], e["isin"]))
    return {**forecast, "upcoming": upcoming}


def dividend_outlook(
    conn: sqlite3.Connection,
    positions: list[dict],
    dividends: list[dict],
    transactions: list[dict] | None = None,
) -> dict:
    forecast = forecast_dividends(positions, dividends, transactions)
    return merge_official_ex_dividends(forecast, get_ex_dividends(conn, positions, dividends))
