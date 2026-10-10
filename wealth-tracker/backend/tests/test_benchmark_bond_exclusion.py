"""
"Exclude bonds" on the Benchmarks tab must mean the same thing it means
on the Allocation tab.

It did not. Benchmarks read database.bond_isins — only what the user classified
by hand — while Allocation read etf_holdings.bond_isins, which also asks the fund
for its own asset mix. Classifying happens on the Rebalancing tab, which is
behind a beta flag, so for an account that has never opened it there is nothing
to match: the checkbox is on by default, said it was leaving bonds out, and left
none out. The same account's Allocation tab meanwhile listed those funds as
excluded bonds. One portfolio, two answers.

Watched fail first (rule 3): with the router reading database.bond_isins again,
the bond fund below stays in and both assertions on `_inputs` drop.
"""

import pytest

from domain import database
from domain.portfolio import etf_holdings
from app.routers import benchmarks


EQUITY = "IE00EQUITY001"
BOND = "IE00BONDFUND1"


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    c = database.connect("alice")
    database.init_db(c)
    return c


@pytest.fixture(autouse=True)
def fund_data(monkeypatch):
    """yfinance's asset mix, without the network: BOND is 90% bonds."""
    monkeypatch.setattr(
        etf_holdings,
        "_bond_fraction",
        lambda conn, ticker: 0.90 if ticker == "BND.AS" else 0.0,
    )


@pytest.fixture(autouse=True)
def _no_downloads(monkeypatch):
    """`_inputs` is the unit under test; the two fetches beyond it are not."""
    monkeypatch.setattr(
        benchmarks, "get_benchmark_prices", lambda conn, start: {"S&P 500 (SPY)": object()}
    )
    monkeypatch.setattr(
        benchmarks, "get_portfolio_segments", lambda conn, tx, prices, divs: []
    )


def _seed(conn):
    """One equity position and one bond fund, both held, neither classified."""
    database.save_transactions(conn, [
        {
            "date": "2026-01-05", "time": "09:30", "isin": isin, "name": isin,
            "exchange": "EAM", "venue": "EAM", "quantity": 10.0, "price": 100.0,
            "local_value": -1000.0, "value_eur": -1000.0, "exchange_rate": 1.0,
            "transaction_fee": -1.0, "autofx_cost": 0.0, "total_eur": -1001.0,
            "order_id": f"order-{isin}", "transaction_type": "BUY",
        }
        for isin in (EQUITY, BOND)
    ])
    for isin, ticker in ((EQUITY, "EQT.AS"), (BOND, "BND.AS")):
        database.save_price(
            conn, isin=isin, name=isin, ticker=ticker,
            price=100.0, currency="EUR", previous_close=99.0,
        )


def _isins_used(conn, *, exclude_bonds):
    transactions, _prices, _bench, _divs, _segments = benchmarks._inputs(
        conn, exclude_bonds
    )
    return {t["isin"] for t in transactions}


def test_a_bond_fund_the_user_never_classified_is_still_excluded(conn):
    _seed(conn)
    assert _isins_used(conn, exclude_bonds=True) == {EQUITY}


def test_unticking_the_box_puts_it_back(conn):
    _seed(conn)
    assert _isins_used(conn, exclude_bonds=False) == {EQUITY, BOND}


def test_the_two_tabs_now_agree_on_what_a_bond_is(conn):
    """The point of the change, stated directly against the other reader."""
    _seed(conn)
    from domain.portfolio import positions as portfolio

    positions = portfolio.calculate_positions(
        database.load_transactions(conn), database.load_prices(conn)
    )
    allocation = etf_holdings.bond_isins(conn, positions)
    benchmarks_excluded = {EQUITY, BOND} - _isins_used(conn, exclude_bonds=True)

    assert benchmarks_excluded == allocation == {BOND}


def test_the_users_own_word_still_wins(conn):
    """Precedence is etf_holdings.bond_isins', unchanged: classification first."""
    _seed(conn)
    database.save_asset_category(conn, BOND, "Stocks")

    assert _isins_used(conn, exclude_bonds=True) == {EQUITY, BOND}
