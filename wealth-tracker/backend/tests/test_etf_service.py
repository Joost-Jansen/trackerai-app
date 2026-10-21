"""
The ETF tab's data-quality arithmetic.

The plan singles this tab out: "coverage %/excluded % match exactly — this tab's
data-quality logic is the most intricate, so numeric parity (not just 'renders')
is the bar." The subtlety is that a fund is graded by the *worse* of its two
sources, and that those sources are a mix of strings and booleans — `True` means
"estimated", which sorts between "proxy" and missing, and is emphatically not
`"exact"`.

Verified against app.py's own inline version on real data (testuser, 9
positions): identical buckets, identical percentages to six decimals.
"""

from app.services.etf_service import diversification_quality, exposure_quality


def _fund(ticker, value, region, sector):
    return {"ticker": ticker, "current_value": value, "region_data": region, "sector_data": sector}


def _buckets(result):
    return {b["kind"]: b for b in result["buckets"]}


def test_a_fund_is_graded_by_its_worse_source():
    """Exact countries + guessed sectors is not an exact fund."""
    result = diversification_quality(
        [
            _fund("A", 100.0, "exact", True),  # exact region, estimated sector -> est
            _fund("B", 100.0, "exact", "exact"),
        ]
    )
    buckets = _buckets(result)
    assert buckets["est"]["tickers"] == ["A"]
    assert buckets["exact"]["tickers"] == ["B"]


def test_manual_counts_as_exact_and_proxy_sits_between():
    result = diversification_quality(
        [
            _fund("A", 100.0, "manual", "manual"),
            _fund("B", 100.0, "proxy", "exact"),
            _fund("C", 100.0, "exact", False),
        ]
    )
    buckets = _buckets(result)
    assert buckets["exact"]["tickers"] == ["A"]
    assert buckets["proxy"]["tickers"] == ["B"]  # proxy is worse than exact
    assert buckets["none"]["tickers"] == ["C"]  # False is worse than True


def test_percentages_are_of_value_not_of_fund_count():
    """One big exact fund and three tiny bad ones is mostly-exact data."""
    result = diversification_quality(
        [
            _fund("BIG", 970.0, "exact", "exact"),
            _fund("a", 10.0, False, False),
            _fund("b", 10.0, False, False),
            _fund("c", 10.0, False, False),
        ]
    )
    buckets = _buckets(result)
    assert buckets["exact"]["pct"] == 97.0
    assert buckets["none"]["pct"] == 3.0


def test_excluded_funds_are_left_out_of_the_denominator():
    """Bond ETFs carry no meaningful sector/country data and app.py drops them.

    Counting them would dilute every percentage by the bond share of the
    portfolio, making good data look worse than it is.
    """
    result = diversification_quality(
        [
            _fund("EQ", 100.0, "exact", "exact"),
            _fund("BOND", 900.0, "excluded", "excluded"),
        ]
    )
    assert result["total"] == 100.0
    assert _buckets(result)["exact"]["pct"] == 100.0


def test_diversification_quality_of_an_empty_or_valueless_portfolio():
    assert diversification_quality([]) == {"total": 0, "buckets": []}
    assert diversification_quality([_fund("A", 0.0, "exact", "exact")]) == {"total": 0, "buckets": []}


def test_exposure_quality_buckets_by_declared_level_and_keeps_order():
    result = exposure_quality(
        [
            {"ticker": "C", "value": 10.0, "quality": "none"},
            {"ticker": "A", "value": 60.0, "quality": "exact"},
            {"ticker": "B", "value": 30.0, "quality": "approx"},
        ]
    )
    # Best first, as the strip reads left to right.
    assert [b["kind"] for b in result["buckets"]] == ["exact", "approx", "none"]
    assert _buckets(result)["exact"]["pct"] == 60.0
    assert _buckets(result)["approx"]["pct"] == 30.0


def test_exposure_quality_of_nothing():
    assert exposure_quality([]) == {"total": 0, "buckets": []}


def test_a_directly_held_share_counts_as_exact_not_as_a_guess():
    """ "stock" was in neither the rank table nor the bucket mapping, so a share
    whose sector and country come straight from its own yfinance profile landed
    in the worst bucket — the strip said "only derived from the name" while the
    coverage table two clicks away said "share (exact)" for the same row.
    """
    quality = diversification_quality(
        [
            {"ticker": "ASML.AS", "current_value": 1000.0, "region_data": "stock", "sector_data": "stock"},
            {"ticker": "IWDA.AS", "current_value": 1000.0, "region_data": "exact", "sector_data": "exact"},
        ]
    )
    assert [b["kind"] for b in quality["buckets"]] == ["exact"]
    assert quality["buckets"][0]["pct"] == 100.0
    assert sorted(quality["buckets"][0]["tickers"]) == ["ASML.AS", "IWDA.AS"]


def test_the_worse_of_two_sources_still_decides_the_bucket():
    """Guards the premise of the test above: "stock" moving to rank 0 must not
    let a fund with one weak source pass as exact."""
    quality = diversification_quality(
        [
            {"ticker": "X.AS", "current_value": 1000.0, "region_data": "stock", "sector_data": True},
        ]
    )
    assert [b["kind"] for b in quality["buckets"]] == ["est"]


# ---------------------------------------------------------------------------
# Effective per-company exposure: one bar per company
# ---------------------------------------------------------------------------


def _exposure(monkeypatch, tmp_path, holdings):
    from domain import database
    from domain.portfolio import etf_holdings

    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    conn = database.connect("alice")
    database.init_db(conn)
    monkeypatch.setattr(etf_holdings.issuer_holdings, "fetch_issuer_holdings", lambda c, isin, name=None: holdings.get(isin))
    monkeypatch.setattr(etf_holdings.issuer_holdings, "source_info", lambda c, isin, name=None: ("test", "exact"))
    monkeypatch.setattr(etf_holdings, "bond_isins", lambda c, p: set())
    positions = [{"isin": isin, "name": f"Fund {isin}", "ticker": f"{isin}.AS", "current_value": 10000.0} for isin in holdings]
    stocks, _cov, _srcs = etf_holdings.get_stock_exposure(conn, positions)
    conn.close()
    return {s["name"]: s["value"] for s in stocks}


def test_two_companies_that_share_a_name_are_not_summed_into_one_bar(monkeypatch, tmp_path):
    """Merck & Co (US) and Merck KGaA (Germany) have been separate companies
    since 1917, but both reduce to the key 'MERCK' once the legal-form tokens
    come off — so one bar showed their combined value under whichever name the
    holdings file listed first."""
    values = _exposure(
        monkeypatch,
        tmp_path,
        {
            "F1": [
                {"symbol": "MRK", "name": "MERCK & CO INC", "weight": 0.30, "country": "United States"},
                {"symbol": "MRK", "name": "MERCK", "weight": 0.20, "country": "Germany"},
            ]
        },
    )
    assert values == {"MERCK & CO INC": 3000.0, "MERCK": 2000.0}


def test_the_same_company_spelled_differently_across_funds_stays_one_bar(monkeypatch, tmp_path):
    """The reason the name is normalised at all — this must keep working."""
    values = _exposure(
        monkeypatch,
        tmp_path,
        {
            "F1": [{"symbol": "NVDA", "name": "NVIDIA CORP", "weight": 0.5, "country": "United States"}],
            "F2": [{"symbol": "NVDA", "name": "NVIDIA Corporation", "weight": 0.5, "country": "United States"}],
        },
    )
    assert values == {"NVIDIA CORP": 10000.0}


def test_an_unknown_country_joins_the_company_rather_than_splitting_it(monkeypatch, tmp_path):
    """The yfinance top-10 fallback carries no country. Treating that as "a
    different country" would show one company as two bars whenever a covered
    and an uncovered fund both hold it."""
    values = _exposure(
        monkeypatch,
        tmp_path,
        {
            "F1": [{"symbol": "AAPL", "name": "APPLE INC", "weight": 0.5, "country": "United States"}],
            "F2": [{"symbol": "AAPL", "name": "Apple Inc.", "weight": 0.5, "country": None}],
        },
    )
    assert values == {"APPLE INC": 10000.0}


def test_country_spellings_that_normalise_to_one_do_not_split_a_company(monkeypatch, tmp_path):
    values = _exposure(
        monkeypatch,
        tmp_path,
        {
            "F1": [{"symbol": "TSM", "name": "TAIWAN SEMICONDUCTOR", "weight": 0.5, "country": "Taiwan, Province of China"}],
            "F2": [{"symbol": "TSM", "name": "Taiwan Semiconductor", "weight": 0.5, "country": "Taiwan"}],
        },
    )
    assert values == {"TAIWAN SEMICONDUCTOR": 10000.0}
