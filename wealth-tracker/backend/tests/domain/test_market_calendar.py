"""Whether the app may call a number "today".

The hero chip is `price` against `previous_close`, straight off the price cache.
Those two fields are always the last two closes the exchange printed — which on
a Saturday means Friday against Thursday. The cache is perfectly fresh (there is
no newer quote in existence), staleness detection therefore says nothing, and
the chip printed Friday's move under the word "today": on 8 August 2026, a
Saturday, "↓ €9,24 today" over a portfolio that had not moved since the
Friday close.

So the question staleness cannot answer — "was there a session at all?" — gets
its own calendar, and every figure labelled today reads zero on a day the
exchange did not open.

Watched fail first (rule 3): by reverting is_trading_day to the weekday-only
test, which puts Good Friday back in the trading set and lets the chip claim
Thursday's move on it.
"""

import datetime
import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "backend"))
sys.path.insert(0, _REPO_ROOT)

from app.core import price_refresh                    # noqa: E402
from app.services import dashboard_service            # noqa: E402


D = datetime.date
DT = datetime.datetime


# ---------------------------------------------------------------------------
# The calendar
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("year,easter", [
    (2024, D(2024, 3, 31)),
    (2025, D(2025, 4, 20)),
    (2026, D(2026, 4, 5)),
    (2027, D(2027, 3, 28)),
])
def test_easter_dates(year, easter):
    assert price_refresh._easter(year) == easter


@pytest.mark.parametrize("day", [
    D(2026, 1, 1),    # New Year's Day
    D(2026, 4, 3),    # Good Friday
    D(2026, 4, 6),    # Easter Monday
    D(2026, 5, 1),    # Labour Day
    D(2026, 12, 25),
    D(2026, 12, 26),
])
def test_holidays_are_not_trading_days(day):
    assert not price_refresh.is_trading_day(day)


@pytest.mark.parametrize("day", [
    D(2026, 8, 8),    # Saturday — the day from the bug report
    D(2026, 8, 9),    # Sunday
])
def test_weekend_is_not_a_trading_day(day):
    assert not price_refresh.is_trading_day(day)


@pytest.mark.parametrize("day", [
    D(2026, 8, 7),    # Friday
    D(2026, 8, 10),   # Monday
    D(2026, 4, 2),    # Maundy Thursday: the exchange is simply open
    D(2026, 12, 24),  # Christmas Eve: a shortened day, but a trading day
])
def test_ordinary_weekdays_trade(day):
    assert price_refresh.is_trading_day(day)


# ---------------------------------------------------------------------------
# "Has a session begun printing prices today?"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("now,expected", [
    (DT(2026, 8, 7, 10, 0), True),    # Friday, during trading
    (DT(2026, 8, 7, 23, 0), True),    # Friday after the close: the day *has* happened
    (DT(2026, 8, 8, 10, 0), False),   # Saturday
    (DT(2026, 8, 9, 21, 0), False),   # Sunday
    (DT(2026, 8, 10, 8, 0), False),   # Monday before the open
    (DT(2026, 8, 10, 9, 30), True),   # Monday after the open
    (DT(2026, 4, 3, 14, 0), False),   # Good Friday, in the middle of the day
])
def test_traded_today(now, expected):
    assert price_refresh.traded_today(now) is expected


def test_last_close_passed_walks_back_over_a_holiday():
    """Easter Monday 2026 falls on Monday 6 April, so the last close a Monday morning
    is measured against is Thursday 2 April's — not Friday's, and not that of the
    Monday itself.
    """
    assert price_refresh.last_close_passed(DT(2026, 4, 6, 11, 0)).date() == D(2026, 4, 2)


def test_a_quote_from_before_the_weekend_is_not_stale_on_saturday():
    friday_close = DT(2026, 8, 7, 22, 30).isoformat(sep=" ")
    assert not price_refresh.is_stale(friday_close, DT(2026, 8, 8, 11, 0))


# ---------------------------------------------------------------------------
# What the chip and the Attention block then report
# ---------------------------------------------------------------------------

def _portfolio():
    positions = [
        {"isin": "NL0011794037", "name": "Ahold", "shares_held": 100.0, "current_value": 3333.0},
        {"isin": "IE00B4L5Y983", "name": "iShares World", "shares_held": 50.0, "current_value": 6432.5},
    ]
    prices = {
        # Friday's close against Thursday's — exactly what the cache holds over the
        # weekend: -€67.00 and +€21.50, together -€45.50.
        "NL0011794037": {"price": 33.33, "previous_close": 34.00, "currency": "EUR",
                         "ticker": "AD.AS", "fetched_at": "2026-08-07 22:30:00"},
        "IE00B4L5Y983": {"price": 128.65, "previous_close": 128.22, "currency": "EUR",
                         "ticker": "IWDA.AS", "fetched_at": "2026-08-07 22:30:00"},
    }
    return positions, prices


def test_day_change_on_a_trading_day(monkeypatch):
    monkeypatch.setattr(price_refresh, "traded_today", lambda now=None: True)
    positions, prices = _portfolio()
    day = dashboard_service.portfolio_day_change(positions, prices)
    assert day["delta_eur"] == -45.5
    assert day["market_closed"] is False


def test_day_change_is_zero_when_the_exchange_did_not_trade(monkeypatch):
    monkeypatch.setattr(price_refresh, "traded_today", lambda now=None: False)
    positions, prices = _portfolio()
    day = dashboard_service.portfolio_day_change(positions, prices)
    assert day["delta_eur"] == 0.0
    assert day["pct"] == 0.0
    assert day["market_closed"] is True
    # No second, contradictory explanation next to "market closed".
    assert day["stale"] is False
    # The chip does not disappear: it says €0.00, because *that* is what happened today.
    assert day is not None


def test_movers_are_empty_when_the_exchange_did_not_trade(monkeypatch):
    positions, prices = _portfolio()

    monkeypatch.setattr(price_refresh, "traded_today", lambda now=None: True)
    open_day = dashboard_service.day_movers(positions, prices)
    assert open_day["top"]["name"] == "iShares World"
    assert open_day["bottom"]["name"] == "Ahold"

    monkeypatch.setattr(price_refresh, "traded_today", lambda now=None: False)
    assert dashboard_service.day_movers(positions, prices) == {"top": None, "bottom": None}
