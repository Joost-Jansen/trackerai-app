"""
Tests for etf_service.fund_breakdown — the look-through of one fund, under the
"What is in it" section of a position's own page.

The three things that can silently go wrong here, and are therefore what these
tests pin down:

  * the weights are renormalised, so a file that adds up to 99,4% (cash lines,
    rounding) does not put a column on the screen that adds up to 99,4%;
  * two share classes of one company are one row, the way get_stock_exposure
    already merges them — unmerged, Alphabet is the fifth *and* the seventh
    position of an S&P 500 fund instead of the third, and "top 10" then
    describes nine companies;
  * the euro amounts are the caller's own money, so they are the position's
    value split by those same renormalised weights.

Nothing here touches the network: fetch_issuer_holdings is stubbed.
"""

import pytest

from app.services import etf_service

HOLDINGS = [
    # Weights on purpose do not add up to 1: 0.994 in total, like a real file
    # with a cash line stripped out of it.
    {"symbol": "NVDA", "name": "NVIDIA CORP", "weight": 0.40, "sector": "Information Technology", "country": "United States"},
    {"symbol": "GOOGL", "name": "ALPHABET INC", "weight": 0.20, "sector": "Communication", "country": "United States"},
    {"symbol": "GOOG", "name": "ALPHABET INC", "weight": 0.15, "sector": "Communication", "country": "United States"},
    {"symbol": "ASML", "name": "ASML HOLDING", "weight": 0.244, "sector": "Information Technology", "country": "Netherlands"},
]


@pytest.fixture
def breakdown(monkeypatch):
    monkeypatch.setattr(
        etf_service.issuer_holdings,
        "fetch_issuer_holdings",
        lambda conn, isin, name=None: list(HOLDINGS),
    )
    monkeypatch.setattr(
        etf_service.issuer_holdings,
        "source_info",
        lambda conn, isin, name=None: ("iShares (issuer)", "exact"),
    )
    return etf_service.fund_breakdown(None, "IE00TEST", "TEST FUND", 1000.0)


def test_share_classes_of_one_company_are_one_row(breakdown):
    names = [h["name"] for h in breakdown["holdings"]]
    assert names.count("ALPHABET INC") == 1
    # 0.35 of 0.994 — and second, ahead of ASML, which it is not on either of
    # its own two lines.
    assert breakdown["holdings"][1] == {
        "name": "ALPHABET INC",
        "symbol": "GOOGL",
        "pct": 35.21,
        "value": 352.11,
    }


def test_holdings_are_counted_as_companies_not_as_lines(breakdown):
    """Four lines, three companies — and the page says "3 positions"."""
    assert breakdown["num_holdings"] == 3


def test_weights_are_renormalised_to_the_whole_fund(breakdown):
    assert sum(h["pct"] for h in breakdown["holdings"]) == pytest.approx(100.0)
    assert sum(s["pct"] for s in breakdown["sectors"]) == pytest.approx(100.0, abs=0.1)
    assert sum(c["pct"] for c in breakdown["countries"]) == pytest.approx(100.0, abs=0.1)


def test_euro_amounts_split_the_position_not_the_fund(breakdown):
    """The amounts beside the rows add up to the value printed above them."""
    assert sum(h["value"] for h in breakdown["holdings"]) == pytest.approx(1000.0, abs=0.05)


def test_sectors_are_merged_across_holdings(breakdown):
    assert breakdown["sectors"] == [
        # NVIDIA 40 + ASML 24.4 or 99.4. "Communication" comes out as
        # "Communication Services": _norm_sector equalises the two spellings of the
        # issuers, and the frontend translates that one.
        {"name": "Information Technology", "pct": 64.8},
        {"name": "Communication Services", "pct": 35.2},
    ]


def test_countries_counts_every_country_not_only_the_shown_ones(breakdown):
    assert breakdown["num_countries"] == 2
    assert [c["name"] for c in breakdown["countries"]] == ["United States", "Netherlands"]


def test_top10_of_a_short_fund_is_the_whole_fund(breakdown):
    assert breakdown["top10_pct"] == 100.0


def test_a_fund_without_a_readable_issuer_file_gets_the_empty_shape(monkeypatch):
    """Same keys, empty — the page has one thing to check, not eight."""
    monkeypatch.setattr(
        etf_service.issuer_holdings,
        "fetch_issuer_holdings",
        lambda conn, isin, name=None: None,
    )
    result = etf_service.fund_breakdown(None, "IE00BOND", "SOME BOND FUND", 1000.0)

    assert result == etf_service.fund_breakdown_unavailable()
    assert result["source"] is None
    assert result["holdings"] == []


def test_a_position_without_a_value_still_lists_what_is_in_the_fund(monkeypatch):
    """A position the backend could not price in euros has no amounts to split.

    The weights are still worth showing — "wat zit erin" does not depend on
    knowing what your stake is worth — so the rows come back with a null value
    rather than the whole section disappearing.
    """
    monkeypatch.setattr(
        etf_service.issuer_holdings,
        "fetch_issuer_holdings",
        lambda conn, isin, name=None: list(HOLDINGS),
    )
    monkeypatch.setattr(
        etf_service.issuer_holdings,
        "source_info",
        lambda conn, isin, name=None: ("iShares (issuer)", "exact"),
    )
    result = etf_service.fund_breakdown(None, "IE00TEST", "TEST FUND", None)

    assert all(h["value"] is None for h in result["holdings"])
    assert result["holdings"][0]["pct"] == 40.24
