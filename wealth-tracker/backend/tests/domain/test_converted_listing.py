"""
A listing stored converted must be valued in euros by the series too.

TSM and MCD have no euro listing worth using, so portfolio._to_eur stores their
dollar quote restated in EUR: the price row says EUR, the ticker stays TSM. The
series download that ticker's history — in dollars — and used to add it to the
euro total as it came. On one account on 2026-09-24 that put TSMC at 2 x $446,57
= "EUR 893" on the value card, against EUR 784 at the top of the same page, and
the two return percentages 2,7 points apart.

The row's quote_currency says what the ticker quotes in; the series convert its
closes at each day's rate (USDEUR=X), the intraday line at the spot rate.

Watched fail first: without the conversion in _eur_daily_closes the dollar leg
below counts 10 x 110 = 1100 instead of 10 x 110 x 0,9 = 990.
"""

import datetime
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from domain.portfolio import series as charts  # noqa: E402
from domain.portfolio import positions as portfolio  # noqa: E402


FIRST_BUY = datetime.date.today() - datetime.timedelta(days=6)
DAYS = pd.DatetimeIndex([FIRST_BUY + datetime.timedelta(days=i) for i in range(7)])


@pytest.fixture
def closes(monkeypatch):
    """yf.download answers each call with a flat frame for what it was asked."""
    def install(**by_ticker):
        by_ticker = {t.replace("_", ".").replace("EUR.X", "EUR=X"): v for t, v in by_ticker.items()}

        def download(tickers, **kw):
            asked = [t for t in tickers if t in by_ticker]
            return pd.DataFrame(
                {("Close", t): [by_ticker[t]] * len(DAYS) for t in asked}, index=DAYS
            )
        monkeypatch.setattr(charts.yf, "download", download)
    return install


def _buy(isin, quantity, total_eur):
    return {
        "date": FIRST_BUY.isoformat(), "time": "09:30", "isin": isin, "name": isin,
        "quantity": quantity, "total_eur": total_eur, "transaction_type": "BUY",
    }


TRANSACTIONS = [_buy("NL_FUND", 10.0, -1000.0), _buy("US_TSMC", 10.0, -1000.0)]

#: The dollar leg as the price refresh stores it: EUR 99 = $110 x 0,9.
PRICES = {
    "NL_FUND": {"ticker": "AAA.AS", "price": 100.0, "currency": "EUR", "quote_currency": "EUR"},
    "US_TSMC": {"ticker": "TSM", "price": 99.0, "currency": "EUR", "quote_currency": "USD"},
}


def test_the_value_series_converts_a_dollar_ticker(closes):
    closes(AAA_AS=100.0, TSM=110.0, USDEUR_X=0.9)

    _dates, _invested, values, _vd = charts.portfolio_history_series(TRANSACTIONS, PRICES, [])

    assert values[-1] == pytest.approx(1000.0 + 990.0)


def test_the_segments_convert_it_the_same_way(closes):
    closes(AAA_AS=100.0, TSM=110.0, USDEUR_X=0.9)

    _dates, values, _cf = charts.build_portfolio_segments(TRANSACTIONS, PRICES, [])[0]

    assert values[-1] == pytest.approx(1990.0)


def test_no_rate_means_no_chart_rather_than_a_flat_estimate(closes):
    """Without a rate the dollar history is unusable. Carrying the holding at
    its cached price drew a flat stretch that looked measured; the card says
    the history could not be fetched instead."""
    closes(AAA_AS=100.0, TSM=110.0)

    with pytest.raises(charts.DataUnavailable):
        charts.portfolio_history_series(TRANSACTIONS, PRICES, [])
    with pytest.raises(charts.DataUnavailable):
        charts.build_portfolio_segments(TRANSACTIONS, PRICES, [])


def test_a_rate_that_starts_after_the_history_means_no_chart(closes, monkeypatch):
    closes(AAA_AS=100.0, TSM=110.0)
    late = pd.Series([0.9], index=DAYS[-1:])
    real = charts._download_closes

    def download(tickers, **kw):
        if tickers == ["USDEUR=X"]:
            return {"USDEUR=X": late}
        return real(tickers, **kw)
    monkeypatch.setattr(charts, "_download_closes", download)

    with pytest.raises(charts.DataUnavailable):
        charts.portfolio_history_series(TRANSACTIONS, PRICES, [])


def test_a_row_from_before_quote_currency_is_read_as_its_currency(closes):
    """Old rows have no quote_currency; for a euro listing that is still right."""
    closes(AAA_AS=100.0)
    prices = {"NL_FUND": {"ticker": "AAA.AS", "price": 100.0, "currency": "EUR"}}

    _dates, _invested, values, _vd = charts.portfolio_history_series(
        [TRANSACTIONS[0]], prices, []
    )

    assert values[-1] == pytest.approx(1000.0)


def test_to_eur_remembers_what_the_ticker_quotes_in(monkeypatch):
    monkeypatch.setattr(portfolio, "_fx_to_eur_rate", lambda ccy: 0.9)

    converted = portfolio._to_eur(
        {"ticker": "TSM", "price": 110.0, "currency": "USD", "previous_close": 100.0}
    )

    assert converted["currency"] == "EUR"
    assert converted["price"] == pytest.approx(99.0)
    assert converted["quote_currency"] == "USD"


def test_to_eur_keeps_the_rate_it_converted_at(monkeypatch):
    monkeypatch.setattr(portfolio, "_fx_to_eur_rate", lambda ccy: 0.9)

    converted = portfolio._to_eur({"ticker": "TSM", "price": 110.0, "currency": "USD"})

    assert converted["quote_fx_rate"] == pytest.approx(0.9)
