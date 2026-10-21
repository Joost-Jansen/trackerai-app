"""
charts.build_portfolio_segments must value a portfolio the way the rest of the
app does: in euros, from euro-quoted listings only.

adcb571 fixed exactly this in portfolio_history_series — the value card's daily
series — and left the segment builder beside it untouched. The two have fed the
same screen ever since: returns_service.build takes its inleg and gain from the
value series and its TWR from the segments, so a dollar-quoted holding made the
percentage and the euro figure on the Returns tab disagree, and put the
Benchmarks line above an index it was being compared to.

The rule both now share is portfolio.calculate_positions': a quote in another
currency cannot be added to a euro cost basis, so it is treated as missing and
the position is carried at what was paid for it.

Watched fail first (rule 3): with the currency filter removed, the segment
below values the USD position at 10 x $110 = 2100 and the assertion drops.
"""

import datetime
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from domain.portfolio import series as charts  # noqa: E402

FIRST_BUY = datetime.date.today() - datetime.timedelta(days=6)


@pytest.fixture
def closes(monkeypatch):
    """Installs a flat daily frame as yf.download's answer, per ticker."""

    def install(**by_ticker):
        days = pd.DatetimeIndex([FIRST_BUY + datetime.timedelta(days=i) for i in range(7)])
        data = {("Close", ticker.replace("_", ".")): [price] * len(days) for ticker, price in by_ticker.items()}
        frame = pd.DataFrame(data, index=days)
        monkeypatch.setattr(charts.yf, "download", lambda tickers, **kw: frame)

    return install


def _buy(isin, quantity, total_eur):
    return {
        "date": FIRST_BUY.isoformat(),
        "time": "09:30",
        "isin": isin,
        "name": isin,
        "quantity": quantity,
        "total_eur": total_eur,
        "transaction_type": "BUY",
    }


#: Both positions cost EUR 1.000. The euro listing is still worth exactly that
#: (10 x EUR 100); the dollar listing is quoted at $110, which is *not* EUR
#: 1.100 and must not be counted as such.
TRANSACTIONS = [
    _buy("NL_EUR_FUND", 10.0, -1000.0),
    _buy("US_USD_STOCK", 10.0, -1000.0),
]

PRICES = {
    "NL_EUR_FUND": {"ticker": "AAA.AS", "price": 100.0, "currency": "EUR"},
    "US_USD_STOCK": {"ticker": "TSM", "price": 110.0, "currency": "USD"},
}


def test_a_dollar_quote_is_not_counted_as_euros(closes):
    closes(AAA_AS=100.0, TSM=110.0)

    segments = charts.build_portfolio_segments(TRANSACTIONS, PRICES, [])

    _dates, values, _cashflows = segments[0]
    # EUR 1.000 of euro-quoted shares at their close, plus the dollar position
    # held at the EUR 1.000 it was bought for. Not 2100, which is what summing
    # $110 into a euro total produces.
    assert values[-1] == pytest.approx(2000.0)


def test_the_euro_leg_still_moves_with_its_price(closes):
    """The fallback must not freeze the whole portfolio, only the odd listing."""
    closes(AAA_AS=120.0, TSM=110.0)

    segments = charts.build_portfolio_segments(TRANSACTIONS, PRICES, [])

    _dates, values, _cashflows = segments[0]
    assert values[-1] == pytest.approx(1200.0 + 1000.0)


def test_it_agrees_with_the_value_series_it_shares_a_screen_with(closes):
    """The whole point: one portfolio, one valuation, two series."""
    closes(AAA_AS=100.0, TSM=110.0)
    _dates, _invested, series_values, _with_divs = charts.portfolio_history_series(TRANSACTIONS, PRICES, [])

    closes(AAA_AS=100.0, TSM=110.0)
    _seg_dates, segment_values, _cf = charts.build_portfolio_segments(TRANSACTIONS, PRICES, [])[0]

    assert segment_values[-1] == pytest.approx(series_values[-1])
