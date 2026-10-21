"""What one price refresh reports about itself.

refresh_all_prices used to return `database.load_prices(conn)` — the whole
cache, which says nothing about what the pass did. Both callers took `len()` of
it, so a round in which every fetch failed answered with a full count: the
sheet went green ("Prices updated.") over a portfolio that had not moved a
cent, and the log said "18 prices for 1 account(s)". These hold the three
states apart.

Watched fail first (rule 3): by asserting the old `len(cache)` semantics, which
passes the all-failed test with the exact number that made it a bug.
"""

import sqlite3
import time

import pytest

from domain import database
from domain.portfolio import positions as portfolio

#: Captured before any test patches time.sleep. The tests below neutralise the
#: 0,5s courtesy pause between ISINs by patching time.sleep, which is the same
#: module object a slow fake fetch would otherwise use to burn its own clock —
#: so a fetch that patched itself away ran instantly and the deadline never
#: fired. This keeps one real handle for the fakes that must actually take time.
_real_sleep = time.sleep


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    database.init_db(conn)
    return conn


def _tx(isin, name, order_ref):
    return {
        "date": "2025-01-02",
        "time": "10:00",
        "isin": isin,
        "name": name,
        "transaction_type": "BUY",
        "quantity": 10.0,
        "price": 100.0,
        "total_eur": 1000.0,
        "order_ref": order_ref,
        "currency": "EUR",
        "exchange": "EAM",
        "transaction_fee": 1.0,
        "autofx_cost": 0.0,
    }


def _with_positions(*isins):
    conn = _conn()
    database.save_transactions(conn, [_tx(isin, f"Fund {i}", f"o{i}") for i, isin in enumerate(isins)])
    return conn


def _priced(ticker="AAA.AS", price=100.0):
    return {"ticker": ticker, "price": price, "currency": "EUR", "previous_close": 99.0}


# ---------------------------------------------------------------------------
# The count means what it says
# ---------------------------------------------------------------------------


def test_every_fetch_failing_reports_zero(monkeypatch):
    """The bug, stated: a warm cache must not make a dead uplink look healthy."""
    conn = _with_positions("NL0000001", "NL0000002")
    # Both ISINs already have a price from a previous, working round.
    for isin in ("NL0000001", "NL0000002"):
        database.save_price(conn, isin=isin, name="Fund", ticker="AAA.AS", price=100.0, currency="EUR", previous_close=99.0)

    monkeypatch.setattr(portfolio, "fetch_price_for_isin", lambda *a, **k: None)
    monkeypatch.setattr(portfolio.time, "sleep", lambda _s: None)

    result = portfolio.refresh_all_prices(conn)

    assert result.refreshed == 0
    assert len(result.failed) == 2
    assert result.complete is False
    # The old return value is still sitting right there, and is still 2.
    assert len(database.load_prices(conn)) == 2


def test_a_working_round_reports_every_isin(monkeypatch):
    conn = _with_positions("NL0000001", "NL0000002")
    monkeypatch.setattr(portfolio, "fetch_price_for_isin", lambda *a, **k: _priced())
    monkeypatch.setattr(portfolio.time, "sleep", lambda _s: None)

    result = portfolio.refresh_all_prices(conn)

    assert result.refreshed == 2
    assert result.failed == []
    assert result.complete is True


def test_a_partial_round_names_what_failed(monkeypatch):
    conn = _with_positions("NL0000001", "NL0000002")

    def _fetch(conn_, isin, name, **kwargs):
        return _priced() if isin == "NL0000001" else None

    monkeypatch.setattr(portfolio, "fetch_price_for_isin", _fetch)
    monkeypatch.setattr(portfolio.time, "sleep", lambda _s: None)

    result = portfolio.refresh_all_prices(conn)

    assert result.refreshed == 1
    assert [f["isin"] for f in result.failed] == ["NL0000002"]
    assert result.complete is False
    # The failed one keeps its previous price rather than losing it.
    assert "NL0000002" not in database.load_prices(conn)


def test_an_empty_portfolio_is_not_a_failure():
    result = portfolio.refresh_all_prices(_conn())
    assert result == portfolio.RefreshResult(refreshed=0, failed=[])
    assert result.complete is True


# ---------------------------------------------------------------------------
# The deadline
#
# A stalled network does not fail fast: yfinance's cookie bootstrap ignores the
# timeout its caller passes, and one ISIN was measured at 721 seconds. Without
# a bound, "Ververs prices" holds a request thread — and the browser tab
# waiting on it — for hours.
# ---------------------------------------------------------------------------


def test_the_deadline_stops_starting_new_isins(monkeypatch):
    conn = _with_positions("NL0000001", "NL0000002", "NL0000003")
    calls = []

    def _slow(conn_, isin, name, **kwargs):
        calls.append(isin)
        _real_sleep(0.05)
        return _priced()

    monkeypatch.setattr(portfolio, "fetch_price_for_isin", _slow)
    monkeypatch.setattr(portfolio.time, "sleep", lambda _s: None)

    result = portfolio.refresh_all_prices(conn, deadline_seconds=0.04)

    # The first is always attempted (the check runs before each, so it cannot
    # cut a round to nothing); the rest are reported, not silently dropped.
    assert len(calls) < 3
    assert result.refreshed == len(calls)
    assert result.skipped == 3 - len(calls)
    assert result.complete is False


def test_a_fetch_already_running_is_not_cut_in_half(monkeypatch):
    """The deadline gates starting work, never interrupts it."""
    conn = _with_positions("NL0000001")
    finished = []

    def _slow(conn_, isin, name, **kwargs):
        _real_sleep(0.05)
        finished.append(isin)
        return _priced()

    monkeypatch.setattr(portfolio, "fetch_price_for_isin", _slow)
    monkeypatch.setattr(portfolio.time, "sleep", lambda _s: None)

    result = portfolio.refresh_all_prices(conn, deadline_seconds=0.001)

    assert finished == ["NL0000001"]
    assert result.refreshed == 1
