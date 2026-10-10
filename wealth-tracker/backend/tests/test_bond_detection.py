"""
Which positions count as bonds, and therefore fall outside the ETF-analyse
percentages.

This used to be a hand-maintained set of one ISIN — the author's own bond ETF.
Anyone else's was run straight through the sector and country machinery, and the
note that says bond funds are not included stayed hidden, because the excluded
percentage it is gated on was zero. Wrong numbers with nothing on screen to say
so, which is the worst shape a wrong number can take.

Three tests decide it now, and the order between them is the whole design: the
user's own classification beats the fund data beats the fallback list. The tests
below pin that order, including the case that makes it a real choice — a user
who says "not a bond" about a fund yfinance calls one.

Each test was watched fail first (rule 3): by reversing the precedence, by
dropping the threshold comparison, and by removing the negative-classification
branch.
"""

import pytest

from domain import database
from domain.portfolio import etf_holdings


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    c = database.connect("alice")
    database.init_db(c)
    return c


def _pos(isin, ticker="X.AS", value=1000.0):
    return {"isin": isin, "ticker": ticker, "name": isin, "current_value": value}


@pytest.fixture
def fund_data(monkeypatch):
    """Installs {ticker: bond fraction or None} as yfinance's answer."""
    def install(mapping):
        calls = []

        def fake_fraction(conn, ticker):
            calls.append(ticker)
            return mapping.get(ticker)

        monkeypatch.setattr(etf_holdings, "_bond_fraction", fake_fraction)
        return calls

    return install


# ---------------------------------------------------------------------------
# The fund's own asset mix — what makes this work without any user input
# ---------------------------------------------------------------------------

def test_a_fund_that_is_mostly_bonds_is_excluded(conn, fund_data):
    fund_data({"IEAC.AS": 0.9984})
    assert etf_holdings.bond_isins(conn, [_pos("IE00B3F81R35", "IEAC.AS")]) == {"IE00B3F81R35"}


def test_an_equity_fund_is_not_excluded(conn, fund_data):
    fund_data({"VUSA.AS": 0.0})
    assert etf_holdings.bond_isins(conn, [_pos("IE00B3XXRP09", "VUSA.AS")]) == set()


def test_a_term_bond_etf_holding_a_third_in_cash_still_counts(conn, fund_data):
    # CEBE.DE really reads 69% bonds / 31% cash as it approaches maturity. A
    # threshold set at "almost all bonds" would let it through.
    fund_data({"CEBE.DE": 0.6882})
    assert etf_holdings.bond_isins(conn, [_pos("IE000WA6L436", "CEBE.DE")]) == {"IE000WA6L436"}


@pytest.mark.parametrize("fraction,excluded", [(0.49, False), (0.5, False), (0.51, True)])
def test_the_threshold_is_more_than_half(conn, fund_data, fraction, excluded):
    fund_data({"MIX.AS": fraction})
    got = etf_holdings.bond_isins(conn, [_pos("IE00MIXED001", "MIX.AS")])
    assert bool(got) is excluded


def test_a_fund_yfinance_knows_nothing_about_falls_through(conn, fund_data):
    fund_data({"WEIRD.SG": None})
    assert etf_holdings.bond_isins(conn, [_pos("IE00UNKNOWN1", "WEIRD.SG")]) == set()


def test_a_position_without_a_ticker_is_not_looked_up(conn, fund_data):
    calls = fund_data({})
    assert etf_holdings.bond_isins(conn, [{"isin": "IE00NOTICKER", "current_value": 10.0}]) == set()
    assert calls == []


# ---------------------------------------------------------------------------
# The user's own classification wins
# ---------------------------------------------------------------------------

def test_a_position_the_user_called_a_bond_is_excluded(conn, fund_data):
    fund_data({"ODD.AS": 0.0})  # the fund data disagrees
    database.save_asset_category(conn, "IE00USERBOND", "Bonds")
    assert etf_holdings.bond_isins(conn, [_pos("IE00USERBOND", "ODD.AS")]) == {"IE00USERBOND"}


def test_a_position_the_user_called_stocks_is_kept_even_if_the_fund_data_says_bonds(conn, fund_data):
    fund_data({"IEAC.AS": 0.9984})
    database.save_asset_category(conn, "IE00B3F81R35", "Stocks")
    # An explicit statement about their own portfolio outranks a data feed, in
    # both directions — otherwise "the app knows better" is unarguable.
    assert etf_holdings.bond_isins(conn, [_pos("IE00B3F81R35", "IEAC.AS")]) == set()


def test_the_classification_short_circuits_the_lookup(conn, fund_data):
    calls = fund_data({"IEAC.AS": 0.9984})
    database.save_asset_category(conn, "IE00B3F81R35", "Bonds")
    etf_holdings.bond_isins(conn, [_pos("IE00B3F81R35", "IEAC.AS")])
    assert calls == []  # no request for an answer already known


def test_the_older_bond_spelling_still_counts(conn, fund_data):
    """The Rebalancing tab wrote "Bond" before it wrote "Bonds"."""
    fund_data({"ODD.AS": 0.0})
    database.save_asset_category(conn, "IE00OLDBOND1", "Bond")
    assert etf_holdings.bond_isins(conn, [_pos("IE00OLDBOND1", "ODD.AS")]) == {"IE00OLDBOND1"}


# ---------------------------------------------------------------------------
# The fallback list, for what neither of the two above can settle
# ---------------------------------------------------------------------------

def test_the_hardcoded_list_catches_a_fund_with_no_data(conn, fund_data):
    fund_data({"CEBE.DE": None})
    assert etf_holdings.bond_isins(conn, [_pos("IE000WA6L436", "CEBE.DE")]) == {"IE000WA6L436"}


def test_the_hardcoded_list_does_not_override_the_user(conn, fund_data):
    fund_data({"CEBE.DE": None})
    database.save_asset_category(conn, "IE000WA6L436", "Stocks")
    assert etf_holdings.bond_isins(conn, [_pos("IE000WA6L436", "CEBE.DE")]) == set()


def test_a_mixed_portfolio_separates_correctly(conn, fund_data):
    fund_data({"IEAC.AS": 0.99, "VUSA.AS": 0.0, "NN.AS": None})
    positions = [
        _pos("IE00B3F81R35", "IEAC.AS"),
        _pos("IE00B3XXRP09", "VUSA.AS"),
        _pos("NL0010773842", "NN.AS"),
    ]
    assert etf_holdings.bond_isins(conn, positions) == {"IE00B3F81R35"}


# ---------------------------------------------------------------------------
# What is left out and what is *reported* as left out must be the same set
# ---------------------------------------------------------------------------
#
# The docstring at the top of this file describes a bug that was only half
# fixed: bond_isins() decides what falls outside the percentages, but
# get_portfolio_breakdown went on building its "excluded" list from the
# hand-maintained set alone. A bond the user classified themselves was dropped
# from the percentages and named nowhere — excluded_pct came back 0, and the
# sentence that qualifies every figure on the page is only rendered above zero.


def test_a_user_classified_bond_is_reported_as_excluded(conn, fund_data, monkeypatch):
    fund_data({"BOND.AS": None, "IWDA.AS": None})
    monkeypatch.setattr(etf_holdings, "_fetch_countries_justetf", lambda isin: {"United States": 1.0})
    monkeypatch.setattr(etf_holdings, "_fetch_sector_weights", lambda t: {"Information Technology": 1.0})
    monkeypatch.setattr(etf_holdings.issuer_holdings, "fetch_issuer_holdings", lambda *a, **k: None)
    monkeypatch.setattr(etf_holdings, "_fetch_stock_info", lambda *a, **k: None)
    database.save_asset_category(conn, "NL0000BOND1", "Bonds")

    positions = [_pos("NL0000BOND1", "BOND.AS", 3000.0), _pos("IE00B4L5Y983", "IWDA.AS", 7000.0)]
    _sec, _reg, _cont, coverage, excluded_pct, _all = etf_holdings.get_portfolio_breakdown(conn, positions)

    assert excluded_pct == 30.0
    rows = {c["isin"]: c for c in coverage}
    assert set(rows) == {"NL0000BOND1", "IE00B4L5Y983"}, "every position needs a row"
    assert rows["NL0000BOND1"]["region_data"] == "excluded"


def test_a_fund_the_user_calls_stocks_is_not_also_reported_as_excluded(conn, fund_data, monkeypatch):
    """The mirror image: the one hardcoded ISIN, classified as Stocks. It used
    to be counted in the percentages *and* appended to the excluded list — two
    rows for one position, under an excluded_pct describing nothing."""
    fund_data({"CEBE.DE": None, "IWDA.AS": None})
    monkeypatch.setattr(etf_holdings, "_fetch_countries_justetf", lambda isin: {"United States": 1.0})
    monkeypatch.setattr(etf_holdings, "_fetch_sector_weights", lambda t: {"Information Technology": 1.0})
    monkeypatch.setattr(etf_holdings.issuer_holdings, "fetch_issuer_holdings", lambda *a, **k: None)
    monkeypatch.setattr(etf_holdings, "_fetch_stock_info", lambda *a, **k: None)
    database.save_asset_category(conn, "IE000WA6L436", "Stocks")

    positions = [_pos("IE000WA6L436", "CEBE.DE", 2000.0), _pos("IE00B4L5Y983", "IWDA.AS", 8000.0)]
    _sec, _reg, _cont, coverage, excluded_pct, _all = etf_holdings.get_portfolio_breakdown(conn, positions)

    assert excluded_pct == 0.0
    assert len(coverage) == 2, "one row per position, not one plus a duplicate"
    assert [c["isin"] for c in coverage].count("IE000WA6L436") == 1


def test_the_weight_column_is_one_fraction_of_one_whole(conn, fund_data, monkeypatch):
    """Included rows were divided by the equity part and excluded rows by
    everything, so the column added up to 120%."""
    fund_data({"CEBE.DE": 0.99, "IWDA.AS": 0.0})
    monkeypatch.setattr(etf_holdings, "_fetch_countries_justetf", lambda isin: {"United States": 1.0})
    monkeypatch.setattr(etf_holdings, "_fetch_sector_weights", lambda t: {"Information Technology": 1.0})
    monkeypatch.setattr(etf_holdings.issuer_holdings, "fetch_issuer_holdings", lambda *a, **k: None)
    monkeypatch.setattr(etf_holdings, "_fetch_stock_info", lambda *a, **k: None)

    positions = [_pos("IE000WA6L436", "CEBE.DE", 2000.0), _pos("IE00B4L5Y983", "IWDA.AS", 8000.0)]
    _sec, _reg, _cont, coverage, _excluded_pct, _all = etf_holdings.get_portfolio_breakdown(conn, positions)

    assert round(sum(c["weight_pct"] for c in coverage), 2) == 100.0
    by_isin = {c["isin"]: c["weight_pct"] for c in coverage}
    assert by_isin["IE00B4L5Y983"] == 80.0
    assert by_isin["IE000WA6L436"] == 20.0


def test_a_fund_without_sector_data_shows_as_unknown_rather_than_scaling_the_rest(
    conn, fund_data, monkeypatch
):
    """The country side always lands a fund's weight somewhere; sectors had no
    such floor, so the renormalise scaled the funds that *did* have data up to
    fill the gap — a portfolio half covered showed the covered half at double."""
    fund_data({"HASDATA": 0.0, "NODATA": 0.0})
    monkeypatch.setattr(etf_holdings, "_fetch_countries_justetf", lambda isin: {"United States": 1.0})
    monkeypatch.setattr(
        etf_holdings, "_fetch_sector_weights",
        lambda t: {"Information Technology": 0.5, "Financials": 0.5} if t == "HASDATA" else None,
    )
    monkeypatch.setattr(etf_holdings.issuer_holdings, "fetch_issuer_holdings", lambda *a, **k: None)
    monkeypatch.setattr(etf_holdings, "_fetch_stock_info", lambda *a, **k: None)

    positions = [_pos("AAA", "HASDATA", 5000.0), _pos("BBB", "NODATA", 5000.0)]
    sector, _reg, _cont, _cov, _excl, _all = etf_holdings.get_portfolio_breakdown(conn, positions)

    assert round(sector["Information Technology"] * 100, 1) == 25.0
    assert round(sector["Financials"] * 100, 1) == 25.0
    assert round(sector["Unknown"] * 100, 1) == 50.0
    assert round(sum(sector.values()), 6) == 1.0
