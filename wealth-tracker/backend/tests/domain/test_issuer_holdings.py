"""
Tests for issuer_holdings.py's parsing and name-matching — the two places
where a silent change on someone else's website turns "exact holdings" into
a Yahoo top-10 estimate without anything erroring.

Nothing here touches the network: the iShares payload below is a trimmed
capture of the real product-data response.
"""

from domain.portfolio import issuer_holdings


def _payload(**columns):
    """Wrap column arrays in the get-product-data envelope."""
    return {
        "componentsByNameMap": {
            "holdings": {
                "containersByNameMap": {"all": {"dataPointsByNameMap": {name: {"value": value} for name, value in columns.items()}}}
            }
        }
    }


ISHARES_API_SAMPLE = _payload(
    issueName=["NVIDIA CORP", "APPLE INC", "USD CASH", "ESTX 50 SEP 26", "TINY CORP"],
    ticker=["NVDA", "AAPL", "USD", "VGU6", ""],
    holdingPercent=[5.16038, 5.04996, 0.31, 0.12, 0.0],
    assetClass=["Equity", "Equity", "Cash", "Futures", "Equity"],
    sectorName=["Information Technology", "Information Technology", "Cash and/or Derivatives", "-", "Industrials"],
    countryOfRisk=["United States", "United States", "-", "-", "Japan"],
)


def test_ishares_api_parses_equity_rows_with_sector_and_country():
    holdings = issuer_holdings._parse_ishares_api(ISHARES_API_SAMPLE)

    assert holdings == [
        {"symbol": "NVDA", "name": "NVIDIA CORP", "weight": 0.0516038, "sector": "Information Technology", "country": "United States"},
        {"symbol": "AAPL", "name": "APPLE INC", "weight": 0.0504996, "sector": "Information Technology", "country": "United States"},
    ]


def test_ishares_api_drops_cash_futures_and_zero_weight_rows():
    """Cash/derivative rows aren't stock exposure, and a rounded-to-zero
    equity row would add a name at weight 0 — both must not reach the total."""
    names = {h["name"] for h in issuer_holdings._parse_ishares_api(ISHARES_API_SAMPLE)}

    assert "USD CASH" not in names
    assert "ESTX 50 SEP 26" not in names
    assert "TINY CORP" not in names


def test_ishares_api_falls_back_to_name_when_ticker_is_missing():
    holdings = issuer_holdings._parse_ishares_api(
        _payload(
            issueName=["SOME UNLISTED CO"],
            ticker=[None],
            holdingPercent=[1.0],
            assetClass=["Equity"],
        )
    )

    assert holdings == [{"symbol": "SOME UNLISTED CO", "name": "SOME UNLISTED CO", "weight": 0.01, "sector": None, "country": None}]


def test_ishares_api_returns_empty_on_an_unexpected_shape():
    """A site change or an error body must yield nothing, never a partial
    basket that would be reported as complete issuer data."""
    assert issuer_holdings._parse_ishares_api({}) == []
    assert issuer_holdings._parse_ishares_api({"error": "Not Found"}) == []
    assert issuer_holdings._parse_ishares_api(_payload(issueName=["A"])) == []


def test_product_page_path_yields_the_portfolio_id_the_api_needs():
    """Every registered iShares path must resolve to a portfolioId — that id
    is the only key the product-data API accepts."""
    paths = [
        *issuer_holdings.ISHARES_PRODUCTS.values(),
        *(cfg["path"] for cfg in issuer_holdings.PROXY_FUNDS.values()),
        *(src["path"] for src in issuer_holdings._INDEX_PROXY_SOURCES.values()),
    ]

    for path in paths:
        assert issuer_holdings._PORTFOLIO_ID_RE.search(path), path


def test_share_class_suffixes_are_stripped_from_fund_names():
    """DeGiro spells the same fund a dozen ways; the share class carries no
    fund identity, so all of these must reduce to one comparable core."""
    variants = [
        "VANGUARD FTSE ALL-WORLD UCITS ETF USD DIS",
        "VANGUARD FTSE ALL-WORLD UCITS ETF USD DIST",
        "VANGUARD FTSE ALL-WORLD UCITS - (USD) ACCUMULATING ETF",
        "VANGUARD FTSE ALL-WORLD UCITS ETF USDACC",
    ]

    assert {issuer_holdings._norm_fund_name(v) for v in variants} == {"ftse all world"}


def test_words_that_merely_start_with_a_share_class_bit_survive():
    """'dis' is a share class; 'Discretionary' and 'Disney' are not."""
    assert not issuer_holdings._is_shareclass_token("discretionary")
    assert not issuer_holdings._is_shareclass_token("disney")
    assert not issuer_holdings._is_shareclass_token("dividend")
    assert issuer_holdings._is_shareclass_token("dis")
    assert issuer_holdings._is_shareclass_token("usddis")


# ---------------------------------------------------------------------------
# DeGiro's own issuer abbreviations
# ---------------------------------------------------------------------------
#
# The names reaching the matcher come out of DeGiro's export, which writes
# "VNGU" and "VGRD" where the fund says "Vanguard" (the same set
# portfolio._NAME_EXPANSIONS exists for). Left in, the abbreviation stayed in
# the normalised index name, matched nothing in Vanguard's catalogue, and the
# fund got no issuer holdings at all — while the very same fund spelled out in
# full resolved to exact ones.


def test_degiro_issuer_abbreviations_do_not_survive_the_index_name():
    spellings = [
        "VANGUARD FTSE ALL-WORLD UCITS ETF USD ACC",
        "VNGU FTSE ALL-WORLD UCITS ETF USDACC",
        "VGRD FTSE ALL-WORLD UCITS ETF",
    ]
    assert {issuer_holdings._norm_index_name(s) for s in spellings} == {"ftse all world"}


def test_the_index_name_still_keeps_what_identifies_the_basket():
    """Guards the test above: dropping issuer words must not start dropping the
    qualifiers that make two baskets different."""
    assert issuer_holdings._norm_index_name("VNGU FTSE DEVELOPED EUROPE EX UK UCITS ETF") == "ftse developed europe ex uk"
    assert issuer_holdings._norm_index_name("VNGU FTSE DEVELOPED EUROPE UCITS ETF") == "ftse developed europe"


def _stub_catalog(monkeypatch, names):
    monkeypatch.setattr(
        issuer_holdings,
        "_vanguard_catalog",
        lambda conn: [{"productType": "ETF", "assetClass": "Equity", "portId": str(9500 + i), "name": n} for i, n in enumerate(names)],
    )


def test_an_abbreviated_vanguard_fund_still_gets_its_own_exact_holdings(monkeypatch):
    _stub_catalog(monkeypatch, ["FTSE All-World UCITS ETF", "S&P 500 UCITS ETF"])
    for spelling in ("VANGUARD FTSE ALL-WORLD UCITS ETF USD ACC", "VNGU FTSE ALL-WORLD UCITS ETF USDACC", "VGRD FTSE ALL-WORLD UCITS ETF"):
        kind, ref, _label, quality = issuer_holdings._resolve(None, "IE00NEW00001", spelling)
        assert (kind, ref, quality) == ("vanguard_auto", "9500", "exact"), spelling


def test_another_issuer_on_the_same_index_stays_a_proxy(monkeypatch):
    """The abbreviation list must not turn someone else's fund into "exact"."""
    _stub_catalog(monkeypatch, ["FTSE All-World UCITS ETF"])
    kind, ref, _label, quality = issuer_holdings._resolve(None, "IE00NEW00002", "Invesco FTSE All-World UCITS ETF")
    assert (kind, ref, quality) == ("vanguard_auto", "9500", "proxy")


def test_a_name_that_matches_nothing_resolves_to_nothing(monkeypatch):
    _stub_catalog(monkeypatch, ["FTSE All-World UCITS ETF"])
    assert issuer_holdings._resolve(None, "IE00NEW00003", "Some Bespoke Thematic ETF") is None
