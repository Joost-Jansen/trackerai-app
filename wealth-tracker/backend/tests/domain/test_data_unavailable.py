"""What the series do when the closes never arrive.

The bug this closes: yf.download does not raise when the network is gone, it
returns an empty DataFrame. Every `except Exception` wrapped around it was
therefore dead code, and each caller's fallback ran as if the emptiness were a
fact about the market:

  * portfolio_history_series priced every past day at today's cached close,
    drawing a perfectly flat "Waarde" line — measured at 936 days, 796 on the
    same euro, against EUR 6.000 invested.
  * _build_portfolio_daily_series used the cost basis instead, making the day
    value equal the amount invested by construction, so the TWR index never
    left 100 and the Returns tab read 0,00%.
  * fetch_benchmark_prices left SPY and FEZ in dollars when only the FX leg
    failed, under a sentence on the page promising they were converted.

Each test below was watched fail first (rule 3) by reverting the guard: all
three then return a plausible, fully-drawable, wrong answer.
"""

import datetime

import pandas as pd
import pytest

from domain.portfolio import series as charts

TODAY = datetime.date.today()
START = TODAY - datetime.timedelta(days=30)


@pytest.fixture
def download(monkeypatch):
    """Installs a frame (or an exception) as yf.download's answer."""

    def install(frame):
        def fake(tickers, **kwargs):
            if isinstance(frame, Exception):
                raise frame
            return frame

        monkeypatch.setattr(charts.yf, "download", fake)

    return install


def _empty():
    return pd.DataFrame()


def _closes(**by_ticker):
    """A yfinance-shaped daily frame; a None value becomes an all-NaN column."""
    days = pd.DatetimeIndex([START + datetime.timedelta(days=i) for i in range(5)])
    data = {}
    for ticker, value in by_ticker.items():
        ticker = ticker.replace("_", ".").replace("=", "=")
        data[("Close", ticker)] = [value] * 5 if value is not None else [float("nan")] * 5
    return pd.DataFrame(data, index=days)


def _txns():
    return [
        {
            "date": START.isoformat(),
            "isin": "X1",
            "name": "Een fonds",
            "quantity": 10.0,
            "transaction_type": "BUY",
            "total_eur": 1000.0,
        }
    ]


def _prices():
    return {"X1": {"ticker": "AAA.AS", "price": 110.0, "currency": "EUR"}}


# ---------------------------------------------------------------------------
# The value line
# ---------------------------------------------------------------------------


def test_an_empty_download_raises_instead_of_drawing_a_flat_line(download):
    download(_empty())
    with pytest.raises(charts.DataUnavailable):
        charts.portfolio_history_series(_txns(), _prices(), [])


def test_an_all_nan_frame_raises_too(download):
    """The shape a partly-reachable Yahoo returns: columns, no numbers."""
    download(_closes(AAA_AS=None))
    with pytest.raises(charts.DataUnavailable):
        charts.portfolio_history_series(_txns(), _prices(), [])


def test_a_raising_download_raises_ours(download):
    download(RuntimeError("connection reset"))
    with pytest.raises(charts.DataUnavailable):
        charts.portfolio_history_series(_txns(), _prices(), [])


def test_real_closes_still_draw(download):
    download(_closes(AAA_AS=100.0))
    dates, invested, values, _divs = charts.portfolio_history_series(_txns(), _prices(), [])
    assert values and set(values) == {1000.0}  # 10 shares at the real EUR 100
    assert invested[0] == 1000.0
    assert dates


def test_a_substituted_holding_is_named(download):
    """Partial is still drawn — but the card has to be able to say which part."""
    prices = {
        "X1": {"ticker": "AAA.AS", "price": 110.0, "currency": "EUR"},
        "X2": {"ticker": "BBB.AS", "price": 50.0, "currency": "EUR"},
    }
    txns = _txns() + [
        {
            "date": START.isoformat(),
            "isin": "X2",
            "name": "Tweede fonds",
            "quantity": 10.0,
            "transaction_type": "BUY",
            "total_eur": 500.0,
        }
    ]
    # Only AAA came back; BBB is a column of NaN.
    download(_closes(AAA_AS=100.0, BBB_AS=None))

    estimated = []
    charts.portfolio_history_series(txns, prices, [], estimated=estimated)

    assert estimated == [{"isin": "X2", "name": "Tweede fonds", "base": "huidige koers"}]


def test_nothing_is_estimated_when_everything_was_fetched(download):
    download(_closes(AAA_AS=100.0))
    estimated = []
    charts.portfolio_history_series(_txns(), _prices(), [], estimated=estimated)
    assert estimated == []


# ---------------------------------------------------------------------------
# The TWR segments
# ---------------------------------------------------------------------------


def test_segments_raise_rather_than_pin_the_twr_to_zero(download):
    download(_empty())
    with pytest.raises(charts.DataUnavailable):
        charts.build_portfolio_segments(_txns(), _prices(), [])


def test_segments_still_build_from_real_closes(download):
    download(_closes(AAA_AS=100.0))
    segments = charts.build_portfolio_segments(_txns(), _prices(), [])
    assert segments and segments[0][0]


# ---------------------------------------------------------------------------
# Benchmarks and the exchange rate
# ---------------------------------------------------------------------------


def _benchmark_frame(with_fx: bool):
    """SPY/FEZ/EXSA plus, optionally, a usable EURUSD column."""
    days = pd.DatetimeIndex([START + datetime.timedelta(days=i) for i in range(5)])
    data = {
        ("Close", "SPY"): [400.0] * 5,
        ("Close", "FEZ"): [50.0] * 5,
        ("Close", "EXSA.DE"): [200.0] * 5,
    }
    fx = {("Close", "EURUSD=X"): ([1.10] * 5 if with_fx else [float("nan")] * 5)}
    return pd.DataFrame(data, index=days), pd.DataFrame(fx, index=days)


def test_a_failed_exchange_rate_raises_instead_of_leaving_usd(monkeypatch):
    benchmarks, fx = _benchmark_frame(with_fx=False)

    def fake(tickers, **kwargs):
        return fx if "EURUSD=X" in tickers else benchmarks

    monkeypatch.setattr(charts.yf, "download", fake)

    # Pre-fix: SPY and FEZ came back at their dollar prices, silently, and the
    # rebasing hid it until the euro moved.
    with pytest.raises(charts.DataUnavailable):
        charts.fetch_benchmark_prices(START.isoformat())


def test_benchmarks_are_converted_when_the_rate_is_there(monkeypatch):
    benchmarks, fx = _benchmark_frame(with_fx=True)

    def fake(tickers, **kwargs):
        return fx if "EURUSD=X" in tickers else benchmarks

    monkeypatch.setattr(charts.yf, "download", fake)

    result = charts.fetch_benchmark_prices(START.isoformat())

    assert set(result) == set(charts.BENCHMARK_TICKERS)
    # USD ones divided by the rate, the EUR one untouched.
    assert round(float(result["S&P 500 (SPY)"].iloc[0]), 2) == round(400.0 / 1.10, 2)
    assert float(result["STOXX Europe 600 (EXSA.DE)"].iloc[0]) == 200.0


def test_no_benchmark_data_at_all_raises(monkeypatch):
    monkeypatch.setattr(charts.yf, "download", lambda tickers, **kw: pd.DataFrame())
    with pytest.raises(charts.DataUnavailable):
        charts.fetch_benchmark_prices(START.isoformat())
