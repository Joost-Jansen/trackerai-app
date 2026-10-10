"""
charts.py — the portfolio series the app draws, and the number formatting it
draws them with.

This file used to build Plotly figures: it took positions, transactions and
prices and returned go.Figure objects that the Streamlit app embedded directly.
Those functions are gone (CHART_MIGRATION_PLAN.md) — every chart is now drawn in
the browser from data, so nothing here renders anything any more.

What is left is the arithmetic the figures were built on, which had no business
being in the drawing code in the first place:

  - portfolio_history_series(transactions, prices, dividends)
        The daily invested / value / value+dividends series. Feeds the
        dashboard's value-over-time card.
  - build_portfolio_segments(...) / _compute_twr_index(segments)
        Contiguous-investment segments and the time-weighted-return index over
        them. Feed the three Benchmarks comparisons via benchmark_service.
  - fetch_benchmark_prices(start)
        Daily total-return benchmark closes, converted to EUR.
  - fmt_eu(...)
        European number formatting. tests/test_format_parity.py holds
        frontend/lib/format.ts to this character for character.

The name is now a poor fit for the contents; renaming it touches every import in
the backend, so that is left for a moment when something else in here moves too.
"""

import datetime
import yfinance as yf
import pandas as pd
from domain.i18n import tr


class DataUnavailable(RuntimeError):
    """A download answered with nothing where it should have carried data.

    The distinction this exists to make: *nothing to say* versus *nothing
    fetched*. yf.download does not raise when the network is gone — it returns
    an empty DataFrame and writes "N Failed downloads" to a logger of its own —
    so every `except Exception` wrapped around it here was dead code, and each
    caller's fallback path treated an outage as a fact about the market.

    What that looked like: a portfolio's whole history priced at today's cached
    close, drawing a perfectly flat "Waarde" line — measured at 936 days, 796
    of them on the same euro, against EUR 6.000 invested. On the Returns tab
    the same outage picked the *cost basis* instead, so the TWR line sat on
    exactly 0,00% beside a simple return of +16,67%. Both look like an answer.

    Raised rather than returned so database.get_or_fetch cannot store it: an
    empty result cached for the hour outlives the outage that caused it, and
    "try again in a few minutes" then cannot work.
    """


def _download_closes(tickers: list[str], **kwargs) -> dict[str, pd.Series]:
    """{ticker: daily closes} for every ticker that actually came back.

    A ticker the download had no data for is simply absent from the result —
    that is an ordinary partial answer (a fund listed last month has no history
    from 2019) and the callers substitute for it. But *nothing* coming back is
    not a partial answer, it is no answer, and raises DataUnavailable.

    Both shapes yfinance can return are handled here rather than in each
    caller, which is where the two versions of this had drifted: one dropped a
    single-ticker frame on the floor, the other kept it.
    """
    if not tickers:
        return {}

    try:
        raw = yf.download(tickers, progress=False, **kwargs)
    except Exception as e:
        raise DataUnavailable(f"download of {len(tickers)} ticker(s) failed: {e}") from e

    if raw is None or raw.empty:
        raise DataUnavailable(f"download of {len(tickers)} ticker(s) came back empty")

    if isinstance(raw.columns, pd.MultiIndex):
        close_df = raw["Close"]
    else:
        close_df = raw[["Close"]]
        close_df.columns = [tickers[0]]

    out: dict[str, pd.Series] = {}
    for ticker in tickers:
        if ticker in close_df.columns:
            series = close_df[ticker].dropna()
            if not series.empty:
                out[ticker] = series

    # A frame arrived but every column of it is NaN: that is the failure shape a
    # partly-reachable Yahoo produces, and it must not read as "no history".
    if not out:
        raise DataUnavailable(f"no usable closes for any of {len(tickers)} ticker(s)")
    return out


def listing_currency(price_row: dict) -> str | None:
    """The currency a price row's *ticker* quotes in.

    Usually `currency`. Not for a listing outside the euro area: TSM and MCD
    are stored converted (portfolio._to_eur), so the row says EUR while the
    ticker's history — what these series download — is in dollars. Summed as
    euros that made a TSMC share worth EUR 446 on the value card beside EUR 392
    at the top of the same page. Rows from before quote_currency existed fall
    back to `currency`, which is right for every EUR listing and is filled in
    for the others by the next price refresh.
    """
    return price_row.get("quote_currency") or price_row.get("currency")


def _fx_pair(currency: str) -> tuple[str, float]:
    """(Yahoo FX ticker, scale) that turn one unit of *currency* into EUR —
    the same pairs portfolio._fx_to_eur_rate reads, pence included."""
    if currency in ("GBp", "GBX"):
        return "GBPEUR=X", 0.01
    return f"{currency}EUR=X", 1.0


def _eur_daily_closes(prices: dict[str, dict], **download_kwargs) -> dict[str, pd.Series]:
    """{isin: daily closes in EUR} for every EUR-valued price row with a ticker.

    The ticker's closes, converted at each day's own rate where the ticker
    quotes in another currency (listing_currency). Raises DataUnavailable as
    _download_closes does — and also when such a rate cannot be fetched, or
    does not reach back over the ticker's history. The callers used to carry
    that holding at its cached price then, drawing a flat stretch that read as
    a measurement; no chart, with the reason, is the honest answer instead.
    """
    ticker_to_isin: dict[str, str] = {}
    for isin, p in prices.items():
        if p.get("ticker") and p.get("currency") == "EUR":
            ticker_to_isin[p["ticker"].upper()] = isin

    closes = _download_closes(list(ticker_to_isin), **download_kwargs)
    ccy_of = {t: listing_currency(prices[ticker_to_isin[t]]) for t in closes}

    rates: dict[str, pd.Series] = {}
    pairs = {c: _fx_pair(c) for c in set(ccy_of.values()) if c and c != "EUR"}
    if pairs:
        fx = _download_closes(sorted({pair for pair, _ in pairs.values()}), **download_kwargs)
        for c, (pair, scale) in pairs.items():
            if pair not in fx:
                raise DataUnavailable(f"no {pair} rate to convert {c} listings with")
            rates[c] = fx[pair].sort_index() * scale

    out: dict[str, pd.Series] = {}
    for ticker, series in closes.items():
        ccy = ccy_of[ticker]
        if ccy and ccy != "EUR":
            # Weekends and holidays differ per market: the last known rate holds.
            aligned = rates[ccy].reindex(series.index, method="ffill")
            if aligned.isna().any():
                raise DataUnavailable(f"{ccy} rate does not cover {ticker}'s history")
            series = series * aligned
        out[ticker_to_isin[ticker]] = series
    return out


# ── European number formatting ──────────────────────────────────────────────
# Text built in Python f-strings is formatted by Python, which always uses
# "1,234.56". fmt_eu() swaps the separators so those read "1.234,56" instead. It
# only touches the *display string*; the underlying float is untouched, so
# calculations are completely unaffected.
_EU_SWAP = str.maketrans({",": ".", ".": ","})


def fmt_eu(value, decimals: int = 2, prefix: str = "", suffix: str = "",
           plus: bool = False) -> str:
    """
    Format a number in Dutch/European notation: 1.234,56 (dot thousands,
    comma decimal).  Returns '—' for missing values.

    prefix : e.g. '€'   suffix : e.g. '%'
    plus   : show a leading '+' for non-negative values (negatives always
             keep their '-').
    """
    if value is None or pd.isna(value):
        return "–"
    body = f"{value:,.{decimals}f}".translate(_EU_SWAP)
    lead = "+" if (plus and value >= 0) else ""
    return f"{lead}{prefix}{body}{suffix}"




def portfolio_history_series(
    transactions: list[dict],
    prices: dict[str, dict],
    dividends: list[dict] | None = None,
    estimated: list[dict] | None = None,
) -> tuple[list, list, list, list]:
    """The daily portfolio-history series, as four parallel lists.

    Returns (plot_dates, cumulative_invested, portfolio_values,
    value_plus_dividends). Extracted from portfolio_history_chart so the exact
    same numbers feed both the Streamlit Plotly figure and the new dashboard
    value-over-time card — the card needs the raw daily points to slice by its
    period toggles, not a pre-baked figure. Empty lists when there is nothing
    priceable to draw (no transactions, or no historical data yet).

    The "Invested" line is a step-function that rises on each buy; "Value" is
    the shares' worth per calendar day from historical closes (carry-forward on
    non-trading days); "Value + Dividends" adds cumulative dividend income.

    Raises DataUnavailable when the closes could not be fetched at all, rather
    than drawing every day at today's price — see that class. *estimated*, if
    given, is filled with {isin, name, basis} for each holding that had to be
    substituted for anyway, so the card can say which part of the line is not
    measured. Same out-parameter shape as dividend_parser's `warnings=`.
    """
    if not transactions:
        return [], [], [], []

    # --- Build a daily timeline from first trade to today ---
    first_date = min(datetime.date.fromisoformat(t["date"]) for t in transactions)
    today      = datetime.date.today()
    date_range = pd.date_range(start=first_date, end=today, freq="D")

    # --- Fetch historical prices for each held ticker ---
    # EUR-quoted listings only, the same rule portfolio.calculate_positions
    # applies. Every number in this series is added straight into a euro total,
    # and a quote in another currency was going in unconverted: a holding worth
    # $110 a share counted as EUR 110 a share, drawing a line about 9% too high
    # on a chart whose axis says EUR — while the Portfolio tab, correctly,
    # refused to value the same position at all. Where a listing has to be
    # dropped for that reason the cost basis stands in below, exactly as
    # _build_portfolio_daily_series already does it.
    #
    # "EUR-quoted" is the stored price; the ticker's own history can still be in
    # dollars, and _eur_daily_closes converts it — see listing_currency.
    eur_isins = {isin for isin, p in prices.items() if p.get("currency") == "EUR"}

    # Fallback: cached current price for ISINs with no usable historical data
    current_price_fallback: dict[str, float] = {
        isin: p["price"]
        for isin, p in prices.items()
        if p.get("price") is not None and isin in eur_isins
    }

    # No try/except: a failed download raises DataUnavailable and the caller
    # decides. Swallowing it here is what turned an outage into a flat line.
    hist_prices: dict[str, pd.Series] = _eur_daily_closes(   # isin → daily EUR price
        prices,
        start=first_date.isoformat(),
        end=(today + datetime.timedelta(days=1)).isoformat(),
        auto_adjust=True,
    )

    # --- Build a sorted list of (date_str, net_eur) for dividends ---
    sorted_divs = sorted(
        (d for d in (dividends or []) if d.get("date") and d.get("net_eur") is not None),
        key=lambda d: d["date"],
    )
    div_idx = 0
    cumulative_div_so_far = 0.0

    # --- For each day, calculate cumulative invested and total portfolio value ---
    cumulative_invested = []
    portfolio_values    = []
    portfolio_plus_divs = []
    plot_dates          = []

    sorted_tx = sorted(transactions, key=lambda t: t["date"])

    total_invested_so_far = 0.0
    shares_held: dict[str, float] = {}
    # Weighted-average cost per share, the last-resort price — always in EUR,
    # because it comes off the trade's own EUR total. Same fallback (and the
    # same arithmetic) as _build_portfolio_daily_series.
    cost_base_per_share: dict[str, float] = {}
    #: {isin: which substitute stood in} — reported through `estimated` so the
    #: card can name the part of its line that was not measured. A holding can
    #: hit both fallbacks on different days; the last one wins, which is the one
    #: nearest today and so the one the reader is looking at.
    substituted: dict[str, str] = {}

    tx_idx = 0

    for day in date_range:
        day_date = day.date()
        day_ts   = pd.Timestamp(day_date)

        while tx_idx < len(sorted_tx) and sorted_tx[tx_idx]["date"] <= str(day_date):
            t = sorted_tx[tx_idx]
            isin = t["isin"]
            qty  = t["quantity"]
            if t["transaction_type"] == "BUY":
                cost = abs(t["total_eur"]) if t["total_eur"] is not None else 0.0
                old_qty   = shares_held.get(isin, 0.0)
                old_base = cost_base_per_share.get(isin, 0.0)
                new_qty   = old_qty + qty
                cost_base_per_share[isin] = (
                    (old_qty * old_base + cost) / new_qty if new_qty > 0 else 0.0
                )
                shares_held[isin]      = new_qty
                total_invested_so_far += cost
            elif t["transaction_type"] == "SELL":
                shares_held[isin] = max(shares_held.get(isin, 0.0) - qty, 0.0)
                # Subtract actual proceeds — allows total to go negative when
                # you've cashed out more than you ever put in.
                total_invested_so_far -= abs(t["total_eur"]) if t["total_eur"] is not None else 0.0
            tx_idx += 1

        # Accumulate dividends up to and including this day
        while div_idx < len(sorted_divs) and sorted_divs[div_idx]["date"] <= str(day_date):
            cumulative_div_so_far += sorted_divs[div_idx]["net_eur"]
            div_idx += 1

        # Only skip the very first days before any transaction has been made
        if not shares_held and total_invested_so_far == 0:
            continue

        day_value = 0.0
        can_value = True
        for isin, qty in shares_held.items():
            if qty <= 0:
                continue
            price = None
            if isin in hist_prices:
                # Use the most recent price on or before this day (carry-forward)
                series    = hist_prices[isin]
                available = series[series.index <= day_ts]
                if not available.empty:
                    price = float(available.iloc[-1])
            if price is None:
                # History missing or not reaching back this far — the cached
                # current price as a flat approximation for this period.
                price = current_price_fallback.get(isin)
                if price is not None:
                    substituted[isin] = tr("current price")
            if price is None:
                # Nothing quoted in EUR for this holding. Its cost basis keeps
                # the day valuable rather than dropping it (and with it every
                # other position of that day) out of the chart entirely.
                price = cost_base_per_share.get(isin)
                if price is not None:
                    substituted[isin] = "purchase_price"
            if price is None:
                can_value = False
                break
            day_value += qty * price

        if not can_value:
            continue

        plot_dates.append(day_date)
        cumulative_invested.append(round(total_invested_so_far, 2))
        value_today = round(day_value, 2)
        portfolio_values.append(value_today)
        # Rounded once, off the already-rounded value: round(a + b) and round(a)
        # are each half a cent off, so value_plus_dividends - value wobbled by a
        # cent between two days on which no dividend was paid at all. Anything
        # that reads the gap as "dividend received" then invents a cent.
        portfolio_plus_divs.append(round(value_today + round(cumulative_div_so_far, 2), 2))

    if estimated is not None:
        # .get: a transaction row without a name is not a reason to lose the
        # whole chart, and this runs on the success path too.
        names = {t["isin"]: t.get("name") or t["isin"] for t in transactions}
        estimated.extend(
            {"isin": isin, "name": names.get(isin, isin), "base": base}
            for isin, base in sorted(substituted.items())
        )

    return plot_dates, cumulative_invested, portfolio_values, portfolio_plus_divs


def portfolio_intraday_series(
    transactions: list[dict],
    prices: dict[str, dict],
) -> tuple[list, list, tuple | None]:
    """Today's portfolio value per 5 minutes, as (timestamps, values, prev_close).

    The daily series has exactly two points for a 1D range — yesterday's close
    and today's — so the card drew a straight line for the one period where the
    shape is the whole point. This fills that in from yfinance's intraday bars.

    *timestamps* are timezone-aware (UTC) datetimes and *values* the portfolio's
    worth in EUR at each. *prev_close* is `(timestamp, value)` at the previous
    session's close — the level the day is measured against, carrying its own
    timestamp because the card prepends it as the line's first point: a day that
    starts at the opening price measures the wrong thing, since the overnight gap
    then falls outside the line.
    All three are empty/None when there is no intraday data (a market holiday, a
    portfolio of tickers yfinance has no minute bars for, a failed download).

    Two deliberate flattenings, both of which make the day's move read as pure
    market movement:

      - Share counts are today's, held constant across the day. A position
        bought at 15:00 is therefore valued at the 09:00 price too. Transactions
        carry a date but no time, so placing the step correctly is not possible;
        holding it flat at least keeps Δvalue free of it.
      - Cumulative invested is likewise today's, so a deposit today shifts
        prev_close rather than appearing as a jump inside the day.

    Currency: a position stored in something other than EUR is never drawn —
    dashboard_service._day_anchors refuses to anchor such a portfolio, and the
    other two series drop it to its cost basis, which a day does not have. A
    listing stored *converted* (TSM: EUR price, dollar ticker) is drawn, so its
    dollar bars are restated at today's spot rate, the one its stored price was
    converted at. No rate means no line rather than dollars summed as euros.
    """
    if not transactions:
        return [], [], None

    # Upper-cased on both sides of the match below, because yf.download does the
    # same to everything it is handed (`[t.upper() for t in tickers]`) and
    # returns its columns that way. A stored ticker in lower case — which the
    # override editor accepted, and which prices perfectly well through
    # yf.Ticker, since Yahoo itself is case-insensitive — therefore never
    # matched its own column. See the coverage guard further down for what that
    # cost.
    ticker_to_isin = {
        p["ticker"].upper(): isin for isin, p in prices.items() if p.get("ticker")
    }
    if not ticker_to_isin:
        return [], [], None

    # Share counts as of today, from the same replay portfolio_history_series does.
    today = datetime.date.today()
    shares_held: dict[str, float] = {}
    for t in sorted(transactions, key=lambda t: t["date"]):
        if t["date"] > str(today):
            break
        qty = t["quantity"]
        if t["transaction_type"] == "BUY":
            shares_held[t["isin"]] = shares_held.get(t["isin"], 0.0) + qty
        elif t["transaction_type"] == "SELL":
            shares_held[t["isin"]] = max(shares_held.get(t["isin"], 0.0) - qty, 0.0)
    held = {isin: qty for isin, qty in shares_held.items() if qty > 0}
    if not held:
        return [], [], None

    # Only the tickers actually held: downloading the rest costs a request and
    # its bars would be dropped anyway.
    tickers = sorted({t for t, isin in ticker_to_isin.items() if isin in held})
    if not tickers:
        return [], [], None

    try:
        # period="2d" rather than "1d": it spans the previous session too, which
        # is where prev_close comes from, and it keeps the series non-empty
        # before the open and over a weekend (when "today" has no bars at all).
        raw = yf.download(
            tickers,
            period="2d",
            interval="5m",
            auto_adjust=True,
            progress=False,
        )
    except Exception as e:
        print(f"Warning: could not fetch intraday prices: {e}")
        return [], [], None

    if raw is None or raw.empty:
        return [], [], None

    close_df = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    if not isinstance(raw.columns, pd.MultiIndex):
        close_df.columns = [tickers[0]]

    # Bars come back in the exchange's timezone. They are normalised to UTC and
    # kept tz-*aware*: the caller serialises them with their offset, and the
    # browser renders them in the reader's own timezone. Dropping the tz here
    # (tz_convert(None) converts to UTC and forgets it) is what made an Amsterdam
    # session start at 07:00.
    close_df = close_df.copy()
    if getattr(close_df.index, "tz", None) is not None:
        close_df.index = close_df.index.tz_convert("UTC")

    # Forward-fill across the union of timestamps, so a ticker whose exchange
    # posts on a different grid (or pauses) holds its last price instead of
    # dropping the whole portfolio out of the sum for that bar.
    close_df = close_df.sort_index().ffill()

    columns = [t for t in tickers if t in close_df.columns]
    if not columns:
        return [], [], None

    # Everything asked for must come back. This function is the one place in the
    # app that sums over *columns* rather than over positions, so a ticker that
    # was downloaded but is missing from the frame was dropped from `columns`
    # and from the total with it — no exception, no gap in the line, just a
    # smaller number. get_intraday hides it further by overwriting the first and
    # last points with the anchored values, so the shortfall lived only in the
    # middle of the day: a line starting at EUR 6.940, sinking to EUR 5.000,
    # closing at EUR 7.000. On a small position that reads as ordinary noise,
    # and _day_anchors cannot catch it, because the missing position is normally
    # priced and passes every check it makes.
    #
    # Measured against `tickers` (what was requested) and not against `held`
    # (every position): a holding with no price row at all was never requested,
    # was never in the sum, and is already handled — _day_anchors refuses to
    # anchor such a portfolio, so no line is drawn from it. Widening this to
    # `held` would empty the payload for that case too, and the visit strip
    # reads the bars' *timestamps* out of it to find the gap between two
    # sessions. Those stay correct whatever the values do.
    if set(columns) != set(tickers):
        return [], [], None

    # A bar is only usable once every held ticker has a price; before that the
    # sum would silently understate the portfolio.
    usable = close_df[columns].dropna()
    if usable.empty:
        return [], [], None

    spot: dict[str, float | None] = {"EUR": 1.0}
    rate: dict[str, float] = {}
    for ticker in columns:
        ccy = listing_currency(prices[ticker_to_isin[ticker]]) or "EUR"
        if ccy not in spot:
            from domain.portfolio.positions import _fx_to_eur_rate   # portfolio is the heavier import
            spot[ccy] = _fx_to_eur_rate(ccy)
        if not spot[ccy]:
            return [], [], None
        rate[ticker] = spot[ccy]

    def value_at(row) -> float:
        total = 0.0
        for ticker in columns:
            total += held[ticker_to_isin[ticker]] * float(row[ticker]) * rate[ticker]
        return round(total, 2)

    sessions = sorted({ts.date() for ts in usable.index})
    last_session = sessions[-1]
    prev_close = None
    if len(sessions) > 1:
        earlier = usable[[ts.date() < last_session for ts in usable.index]]
        if not earlier.empty:
            prev_close = (earlier.index[-1].to_pydatetime(), value_at(earlier.iloc[-1]))

    latest = usable[[ts.date() == last_session for ts in usable.index]]
    stamps = [ts.to_pydatetime() for ts in latest.index]
    values = [value_at(latest.iloc[i]) for i in range(len(latest))]
    return stamps, values, prev_close
















# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# Benchmark comparison helpers
# ---------------------------------------------------------------------------

BENCHMARK_TICKERS = {
    "S&P 500 (SPY)":        "SPY",
    "EURO STOXX 50 (FEZ)":  "FEZ",
    # EXSA tracks the STOXX Europe 600 (all of Europe) — not the
    # eurozone-only "EURO STOXX" index family.
    "STOXX Europe 600 (EXSA.DE)": "EXSA.DE",
}



# Priced in USD, so converted to EUR before being compared with a EUR portfolio.
USD_BENCHMARK_TICKERS = {"SPY", "FEZ"}


def fetch_benchmark_prices(start_date_iso: str) -> dict:
    """
    Fetches daily total-return closing prices for all benchmark tickers from
    *start_date_iso* until today.  Returns a dict of {label: pd.Series}.

    - auto_adjust=True so dividends are reinvested (total-return basis),
      matching the portfolio's total-return TWR.
    - USD-denominated benchmarks (SPY, FEZ) are converted to EUR using the
      daily EURUSD=X rate so all lines are on the same currency basis.

    Uncached and blocking — every caller must wrap it. app.py has
    @st.cache_data; the backend has database.get_or_fetch (see
    backend/app/services/benchmark_service.py).

    Lives here, beside the tickers it fetches, rather than in app.py where it
    started: the FastAPI backend needs the same three lines, and duplicating a
    yfinance call and an FX conversion is exactly how two screens start
    disagreeing about a number.
    """
    from datetime import date, timedelta

    end_date  = (date.today() + timedelta(days=1)).isoformat()
    tickers   = list(BENCHMARK_TICKERS.values())
    label_map = {v: k for k, v in BENCHMARK_TICKERS.items()}
    result: dict = {}

    # --- The benchmark closes themselves ---
    # Raises DataUnavailable when nothing came back. It used to return {}, which
    # database.get_or_fetch then stored for the full hour — so the tab's own
    # "try again in a few minutes" was advice that could not work
    # until the cache expired.
    closes = _download_closes(
        tickers,
        start=start_date_iso,
        end=end_date,
        auto_adjust=True,   # total-return (dividends reinvested)
    )

    # --- EUR/USD, needed before any USD benchmark can be compared in euro ---
    needs_fx = any(t in USD_BENCHMARK_TICKERS for t in closes)
    eurusd: pd.Series | None = None
    if needs_fx:
        # Its own call, so its own failure. This used to fall back to "leave the
        # series in USD", which is not a degraded answer but a wrong one: the
        # rebasing to 100 cancels a constant rate, never a *change* in it, so a
        # 10% euro move put SPY and FEZ almost 11 percentage points off — under
        # a sentence on the page promising they were converted at the day rate.
        # Nothing said otherwise, because the fallback path never even reached
        # the print(): an empty frame does not raise.
        fx = _download_closes(
            "EURUSD=X".split(),
            start=start_date_iso,
            end=end_date,
            auto_adjust=True,
        )
        eurusd = fx.get("EURUSD=X")
        if eurusd is None or eurusd.empty:
            raise DataUnavailable("no EURUSD rate to convert the USD benchmarks with")

    def _to_eur(series: pd.Series) -> pd.Series:
        # Reindex FX to the benchmark's dates, forward-fill missing weekends
        fx_aligned = eurusd.reindex(series.index, method="ffill")
        return series / fx_aligned

    for ticker, series in closes.items():
        if ticker in USD_BENCHMARK_TICKERS:
            series = _to_eur(series)
        result[label_map[ticker]] = series

    return result


def _build_portfolio_daily_series(
    transactions: list[dict],
    prices: dict[str, dict],
    dividends: list[dict] | None = None,
) -> list[tuple[list, list, list]]:
    """
    Builds a daily portfolio value series, split into contiguous segments.

    Returns a list of (dates, values, cashflows) tuples.  A new segment begins
    whenever the portfolio is completely liquidated (all positions at zero) and
    then re-enters the market.  Chaining TWR across segments avoids phantom
    losses that would otherwise appear when the gap-period prev_value is used
    as the denominator for a fresh investment.

    Dividends are treated as part of the portfolio value (total-return basis).
    Each dividend payment is added to day_value on the ex-date so the TWR
    line reflects the same total return as a dividend-reinvesting benchmark.

    For positions where yfinance has no historical data for a given period
    (e.g. a ticker that only became available recently), the weighted-average
    cost basis is used as the price instead of today's spot price.  This
    prevents phantom gains from being injected into the TWR on the purchase
    date.  When actual historical data resumes the transition reflects the
    real accumulated gain or loss during the gap.

    Cashflows from days that cannot be priced (can_value=False) are carried
    forward to the next successfully priced day.
    """
    if not transactions:
        return []

    first_date = min(datetime.date.fromisoformat(t["date"]) for t in transactions)
    today      = datetime.date.today()
    date_range = pd.date_range(start=first_date, end=today, freq="D")

    # Build ticker→isin and fetch historical prices
    #
    # EUR-quoted listings only, the same rule portfolio_history_series and
    # portfolio.calculate_positions apply. adcb571 fixed this in the value
    # series and left it here, so the two have disagreed since: a holding worth
    # $110 a share counted as EUR 110 in a euro total, which put the TWR line
    # and the benchmark comparison on a portfolio the Portfolio tab refused
    # to value at all. A dropped listing falls to its cost basis below, exactly
    # as one with no history does.
    #
    # Upper-cased to match yf.download's own columns, as above: unmatched, the
    # position falls to its cost basis for every day and contributes a flat 0%
    # to the TWR for as long as the ticker stays that way.
    #
    # A converted listing (TSM) keeps its history, in EUR at each day's rate —
    # see listing_currency.
    #
    # Raises DataUnavailable rather than falling through to the cost basis for
    # every holding, which made the day value equal the invested amount by
    # construction and drew a TWR line pinned to exactly 0,00%.
    hist_prices: dict[str, pd.Series] = _eur_daily_closes(
        prices,
        start=first_date.isoformat(),
        end=(today + datetime.timedelta(days=1)).isoformat(),
        auto_adjust=False,   # raw prices so execution prices match historical prices
    )

    # Build a sorted list of (date_str, net_eur) for dividends so we can
    # accumulate them in a single forward pass alongside the price loop.
    sorted_divs = sorted(
        (d for d in (dividends or []) if d.get("date") and d.get("net_eur") is not None),
        key=lambda d: d["date"],
    )
    div_idx              = 0
    cumulative_div_eur   = 0.0   # running total of all dividends received so far

    sorted_tx = sorted(transactions, key=lambda t: t["date"])
    tx_idx = 0
    shares_held: dict[str, float] = {}
    # Weighted-average cost basis per share — used as price fallback when
    # no historical market data is available for a given period.
    cost_base_per_share: dict[str, float] = {}

    segments: list[tuple[list, list, list]] = []
    seg_dates:  list[datetime.date] = []
    seg_values: list[float]         = []
    seg_cfs:    list[float]         = []
    pending_cf: float = 0.0

    for day in date_range:
        day_date = day.date()
        day_ts   = pd.Timestamp(day_date)

        # Accumulate dividends up to and including this day
        while div_idx < len(sorted_divs) and sorted_divs[div_idx]["date"] <= str(day_date):
            cumulative_div_eur += sorted_divs[div_idx]["net_eur"]
            div_idx += 1

        cf_today = 0.0
        while tx_idx < len(sorted_tx) and sorted_tx[tx_idx]["date"] <= str(day_date):
            t    = sorted_tx[tx_idx]
            isin = t["isin"]
            qty  = t["quantity"]
            cost = abs(t["total_eur"]) if t["total_eur"] is not None else 0.0
            if t["transaction_type"] == "BUY":
                old_qty   = shares_held.get(isin, 0.0)
                old_base = cost_base_per_share.get(isin, 0.0)
                new_qty   = old_qty + qty
                buy_price = cost / qty if qty > 0 else 0.0
                cost_base_per_share[isin] = (
                    (old_qty * old_base + qty * buy_price) / new_qty
                    if new_qty > 0 else 0.0
                )
                shares_held[isin] = new_qty
                cf_today += cost
            elif t["transaction_type"] == "SELL":
                shares_held[isin] = max(shares_held.get(isin, 0.0) - qty, 0.0)
                cf_today -= cost
            tx_idx += 1

        is_in_market = any(v > 0 for v in shares_held.values())

        if not is_in_market:
            # Portfolio is fully liquidated — close the current segment.
            if seg_dates:
                segments.append((seg_dates, seg_values, seg_cfs))
                seg_dates, seg_values, seg_cfs = [], [], []
            pending_cf = 0.0
            continue

        pending_cf += cf_today

        day_value = 0.0
        can_value = True
        for isin, qty in shares_held.items():
            if qty <= 0:
                continue
            if isin in hist_prices:
                avail = hist_prices[isin][hist_prices[isin].index <= day_ts].dropna()
                if not avail.empty:
                    # Actual historical market price — ideal case.
                    day_value += qty * float(avail.iloc[-1])
                else:
                    # Historical data exists but doesn't cover this period
                    # (e.g. ticker only listed recently).  Use cost basis so
                    # no phantom return is injected on the purchase date.
                    if isin in cost_base_per_share:
                        day_value += qty * cost_base_per_share[isin]
                    else:
                        can_value = False
                        break
            else:
                # No historical data fetched.  Use cost basis rather than
                # today's spot price to keep the TWR clean.
                if isin in cost_base_per_share:
                    day_value += qty * cost_base_per_share[isin]
                else:
                    can_value = False
                    break

        if not can_value:
            # Carry pending_cf forward to the next successfully priced day.
            continue

        # Add cumulative dividends on a total-return basis so the portfolio
        # line is comparable to a dividend-reinvesting benchmark index.
        total_return_value = day_value + cumulative_div_eur

        seg_dates.append(day_date)
        seg_values.append(round(total_return_value, 4))
        seg_cfs.append(round(pending_cf, 4))
        pending_cf = 0.0

    if seg_dates:
        segments.append((seg_dates, seg_values, seg_cfs))

    return segments


def build_portfolio_segments(
    transactions: list[dict],
    prices: dict[str, dict],
    dividends: list[dict] | None = None,
) -> list[tuple[list, list, list]]:
    """
    Public wrapper around the internal daily-series builder so app.py can
    compute the segments once (and cache them) instead of every benchmark
    chart re-downloading the same price history.
    """
    return _build_portfolio_daily_series(transactions, prices, dividends)


def _compute_twr_index(
    segments: list[tuple[list, list, list]],
    base: float = 100.0,
) -> pd.Series:
    """
    Computes a daily time-weighted return (TWR) index starting at `base`.

    Accepts a list of contiguous-investment segments as returned by
    _build_portfolio_daily_series().  Within each segment:

        daily_return = V(d) / (V(d-1) + CF(d))

    where CF(d) is the net cash deposited on day d.

    Segments are chained: the endpoint of segment N becomes the starting level
    for segment N+1, so a complete portfolio liquidation followed by
    re-investment creates no phantom loss — the new sub-period continues
    seamlessly from where the previous one left off.

    Returns a pd.Series indexed by date.
    """
    if not segments:
        return pd.Series(dtype=float)

    all_dates: list = []
    all_false:  list = []
    running_level   = base

    for seg_dates, seg_values, seg_cfs in segments:
        seg_index = [running_level]
        for i in range(1, len(seg_dates)):
            prev_v    = seg_values[i - 1]
            cf        = seg_cfs[i]
            denom     = prev_v + cf
            daily_ret = seg_values[i] / denom if denom > 0 else 1.0
            seg_index.append(round(seg_index[-1] * daily_ret, 6))
        all_dates.extend(seg_dates)
        all_false.extend(seg_index)
        running_level = seg_index[-1]

    return pd.Series(all_false, index=pd.to_datetime(all_dates))






