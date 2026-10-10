"""
charts.portfolio_intraday_series — the 1D range's shape.

The daily series has two points for a day, so the one range whose whole point is
the shape drew a straight line. This series fills that in from yfinance's
5-minute bars, which means it has to get three things right that the daily one
never faces: which bars belong to today rather than to the previous session,
what the portfolio was worth at that previous close, and what to do when one
ticker's exchange posts on a different grid than another's.

yfinance is replaced by a fake download throughout — the assertions are about
the arithmetic, and a test that needs the market to be open is a test that fails
on Sundays.

Each test was watched fail first (rule 3): by reversing the session split, by
dropping the forward-fill, and by feeding the pre-fix tz handling that made an
Amsterdam session start at 07:00.
"""

import datetime

import pandas as pd
import pytest

from domain.portfolio import series as charts


TODAY = datetime.date.today()
YESTERDAY = TODAY - datetime.timedelta(days=1)


def _prices(**tickers):
    """{isin: {...}} the way database.load_prices returns it."""
    return {isin: {"ticker": t, "price": 100.0, "currency": "EUR"} for isin, t in tickers.items()}


def _buy(isin, qty, date=None):
    return {
        "isin": isin,
        "quantity": qty,
        "transaction_type": "BUY",
        "total_eur": -1000.0,
        "date": (date or (TODAY - datetime.timedelta(days=30))).isoformat(),
    }


def _sell(isin, qty, date=None):
    return {
        "isin": isin,
        "quantity": qty,
        "transaction_type": "SELL",
        "total_eur": 500.0,
        "date": (date or (TODAY - datetime.timedelta(days=10))).isoformat(),
    }


def _bars(rows, tickers):
    """A yfinance-shaped frame: MultiIndex columns, UTC index.

    *rows* is [(datetime, {ticker: close})]; a ticker missing from a row becomes
    NaN, which is what a real download gives for a bar an exchange did not post.
    """
    index = pd.DatetimeIndex([r[0] for r in rows], tz="UTC")
    data = {("Close", t): [r[1].get(t) for r in rows] for t in tickers}
    return pd.DataFrame(data, index=index)


def _utc(day, hour, minute=0):
    """Naive, the way pandas takes it when building a tz="UTC" index."""
    return datetime.datetime(day.year, day.month, day.day, hour, minute)


def _utc_aware(day, hour, minute=0):
    """Aware, the way the series hands timestamps back."""
    return _utc(day, hour, minute).replace(tzinfo=datetime.timezone.utc)


@pytest.fixture
def fake_download(monkeypatch):
    """Installs a frame as yf.download's answer; returns the call recorder."""
    calls = {}

    def install(frame):
        def fake(tickers, **kwargs):
            calls["tickers"] = tickers
            calls["kwargs"] = kwargs
            return frame

        monkeypatch.setattr(charts.yf, "download", fake)
        return calls

    return install


# ---------------------------------------------------------------------------
# The series itself
# ---------------------------------------------------------------------------

def test_values_are_shares_times_the_bar_close(fake_download):
    fake_download(_bars(
        [
            (_utc(YESTERDAY, 15, 25), {"A.AS": 10.0}),
            (_utc(TODAY, 7, 0), {"A.AS": 11.0}),
            (_utc(TODAY, 7, 5), {"A.AS": 12.0}),
        ],
        ["A.AS"],
    ))
    stamps, values, prev_close = charts.portfolio_intraday_series(
        [_buy("ISIN_A", 3.0)], _prices(ISIN_A="A.AS")
    )
    assert values == [33.0, 36.0]
    assert prev_close == (_utc_aware(YESTERDAY, 15, 25), 30.0)
    assert len(stamps) == 2


def test_only_todays_bars_are_returned(fake_download):
    fake_download(_bars(
        [
            (_utc(YESTERDAY, 7, 0), {"A.AS": 8.0}),
            (_utc(YESTERDAY, 15, 25), {"A.AS": 10.0}),
            (_utc(TODAY, 7, 0), {"A.AS": 11.0}),
        ],
        ["A.AS"],
    ))
    stamps, values, prev_close = charts.portfolio_intraday_series(
        [_buy("ISIN_A", 1.0)], _prices(ISIN_A="A.AS")
    )
    # The previous session contributes prev_close and nothing else — otherwise
    # the "day" would be two days wide and its move would be wrong.
    assert values == [11.0]
    # Carries its own timestamp: the card prepends it as the line's first point,
    # so the day is measured from the close and not from the open.
    assert prev_close == (_utc_aware(YESTERDAY, 15, 25), 10.0)
    assert stamps[0].date() == TODAY


def test_timestamps_keep_their_offset(fake_download):
    fake_download(_bars([(_utc(TODAY, 7, 0), {"A.AS": 11.0})], ["A.AS"]))
    stamps, _, _ = charts.portfolio_intraday_series(
        [_buy("ISIN_A", 1.0)], _prices(ISIN_A="A.AS")
    )
    # tz-aware, so the browser can render 07:00 UTC as 09:00 in Amsterdam. The
    # bug this replaced dropped the tz and shipped 07:00 as a local clock time.
    assert stamps[0].tzinfo is not None
    assert stamps[0].utcoffset() == datetime.timedelta(0)


def test_a_gap_in_one_ticker_holds_its_last_price(fake_download):
    fake_download(_bars(
        [
            (_utc(TODAY, 7, 0), {"A.AS": 10.0, "B.DE": 20.0}),
            (_utc(TODAY, 7, 5), {"A.AS": 11.0}),          # B posted no bar
            (_utc(TODAY, 7, 10), {"A.AS": 12.0, "B.DE": 21.0}),
        ],
        ["A.AS", "B.DE"],
    ))
    _, values, _ = charts.portfolio_intraday_series(
        [_buy("ISIN_A", 1.0), _buy("ISIN_B", 1.0)], _prices(ISIN_A="A.AS", ISIN_B="B.DE")
    )
    # Without the forward-fill the middle bar is 11.0 — the portfolio silently
    # losing B for one bar, which reads as a crash on the chart.
    assert values == [30.0, 31.0, 33.0]


def test_share_count_is_todays_and_flat_across_the_day(fake_download):
    fake_download(_bars(
        [
            (_utc(TODAY, 7, 0), {"A.AS": 10.0}),
            (_utc(TODAY, 7, 5), {"A.AS": 10.0}),
        ],
        ["A.AS"],
    ))
    _, values, _ = charts.portfolio_intraday_series(
        [_buy("ISIN_A", 2.0), _buy("ISIN_A", 3.0, date=TODAY)], _prices(ISIN_A="A.AS")
    )
    # Both bars value all five shares. Transactions carry no time, so the step
    # cannot be placed; holding it flat keeps the day's delta pure market move.
    assert values == [50.0, 50.0]


def test_sold_out_positions_drop_out(fake_download):
    calls = fake_download(_bars([(_utc(TODAY, 7, 0), {"A.AS": 10.0})], ["A.AS"]))
    _, values, _ = charts.portfolio_intraday_series(
        [_buy("ISIN_A", 1.0), _buy("ISIN_B", 4.0), _sell("ISIN_B", 4.0)],
        _prices(ISIN_A="A.AS", ISIN_B="B.DE"),
    )
    assert values == [10.0]
    assert calls["tickers"] == ["A.AS"]  # not downloaded at all


# ---------------------------------------------------------------------------
# Degrading instead of raising — the card falls back to the daily series
# ---------------------------------------------------------------------------

def test_no_previous_session_leaves_prev_close_none(fake_download):
    fake_download(_bars([(_utc(TODAY, 7, 0), {"A.AS": 10.0})], ["A.AS"]))
    _, values, prev_close = charts.portfolio_intraday_series(
        [_buy("ISIN_A", 1.0)], _prices(ISIN_A="A.AS")
    )
    assert values == [10.0]
    assert prev_close is None


def test_empty_frame_returns_nothing(fake_download):
    fake_download(pd.DataFrame())
    assert charts.portfolio_intraday_series(
        [_buy("ISIN_A", 1.0)], _prices(ISIN_A="A.AS")
    ) == ([], [], None)


def test_download_failure_returns_nothing(monkeypatch):
    def tree(*a, **k):
        raise RuntimeError("no network")

    monkeypatch.setattr(charts.yf, "download", tree)
    assert charts.portfolio_intraday_series(
        [_buy("ISIN_A", 1.0)], _prices(ISIN_A="A.AS")
    ) == ([], [], None)


def test_no_transactions_returns_nothing():
    assert charts.portfolio_intraday_series([], _prices(ISIN_A="A.AS")) == ([], [], None)


def test_prices_without_tickers_return_nothing():
    assert charts.portfolio_intraday_series(
        [_buy("ISIN_A", 1.0)], {"ISIN_A": {"price": 10.0, "currency": "EUR"}}
    ) == ([], [], None)


# ---------------------------------------------------------------------------
# Every held position must be in the sum
#
# This series is the only place in the app that totals over *columns* rather
# than over positions, and a position whose ticker was missing from the frame
# was dropped from `columns` and from the total with it — no exception, no gap
# in the line, just a smaller number. get_intraday then overwrites the first
# and last points with the anchored values, so the shortfall lived only in the
# middle of the day, where on a small position it reads as ordinary noise.
#
# The way in was a lower-case ticker override: Yahoo resolves "spy" and "SPY"
# alike, so the position priced perfectly and looked fine, but yf.download
# upper-cases everything it is handed and returns its columns that way, so the
# stored string never matched its own column.
#
# Watched fail first (rule 3): both tests pass on the pre-fix code with a
# silently understated total, which is exactly what made this worth closing.
# ---------------------------------------------------------------------------

def test_a_position_missing_from_the_frame_empties_the_series(fake_download):
    """Fail closed, rather than quietly leave a holding out of the total."""
    prices = _prices(X1="AAA.AS", X2="BBB.AS")
    transactions = [_buy("X1", 10), _buy("X2", 10)]
    # BBB.AS never comes back — not even as a NaN column.
    frame = _bars(
        [
            (_utc(YESTERDAY, 15, 30), {"AAA.AS": 100.0}),
            (_utc(TODAY, 9, 0), {"AAA.AS": 110.0}),
        ],
        ["AAA.AS"],
    )
    fake_download(frame)

    stamps, values, prev_close = charts.portfolio_intraday_series(transactions, prices)

    # Pre-fix this returned a line worth 10 x AAA only: EUR 1.100 where the
    # portfolio holds EUR 2.200. The card falls back to the daily series now.
    assert (stamps, values, prev_close) == ([], [], None)


def test_a_lower_case_ticker_still_matches_its_column(fake_download):
    """The override editor accepted "aaa.as"; the download answers "AAA.AS"."""
    prices = _prices(X1="aaa.as")
    transactions = [_buy("X1", 10)]
    frame = _bars(
        [
            (_utc(YESTERDAY, 15, 30), {"AAA.AS": 100.0}),
            (_utc(TODAY, 9, 0), {"AAA.AS": 110.0}),
        ],
        ["AAA.AS"],
    )
    fake_download(frame)

    stamps, values, prev_close = charts.portfolio_intraday_series(transactions, prices)

    assert values == [1100.0]
    assert prev_close == (_utc_aware(YESTERDAY, 15, 30), 1000.0)


def test_an_unpriced_holding_still_yields_bars_for_the_visit_strip(fake_download):
    """The guard covers what was *requested*, not every position held.

    A holding with no price row was never downloaded and was never in the sum,
    and _day_anchors already refuses to anchor such a portfolio, so no line is
    drawn from it. The bars must still come back: /dashboard/visit reads their
    timestamps to find the gap between two sessions, and those are right
    whatever the values do.
    """
    prices = _prices(X1="AAA.AS")            # X2 has never been priced
    transactions = [_buy("X1", 10), _buy("X2", 10)]
    frame = _bars(
        [
            (_utc(YESTERDAY, 15, 30), {"AAA.AS": 100.0}),
            (_utc(TODAY, 9, 0), {"AAA.AS": 110.0}),
        ],
        ["AAA.AS"],
    )
    fake_download(frame)

    stamps, values, prev_close = charts.portfolio_intraday_series(transactions, prices)

    assert stamps == [_utc_aware(TODAY, 9, 0)]
    assert prev_close is not None
