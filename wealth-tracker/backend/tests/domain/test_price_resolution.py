"""
Tests for portfolio.fetch_price_for_isin's venue handling — specifically that a
holding on a foreign exchange gets a price at all.

Yahoo indexes no US ISINs, and US product names defeat its name search ("ADR ON
TAIWAN SEMICONDUCTOR MANUFACTURING COMPANY LIMITED" returns nothing, while
"TAIWAN SEMICONDUCTOR MANUFACTURING" returns TSM), so such a position used to
end up with no price — showing "—" in the table and quietly dropping out of the
portfolio total. Every network call is stubbed here.
"""

import sqlite3

import pytest

from domain import database
from domain.portfolio import positions as portfolio

# Captured before the autouse fixture below replaces it, for the one test that
# exercises the real OpenFIGI parsing against a stubbed HTTP response.
_REAL_OPENFIGI_TICKER = portfolio._openfigi_ticker


@pytest.fixture()
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    database.init_db(conn)
    return conn


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly instead of hitting Yahoo or OpenFIGI; each test opts back in."""
    monkeypatch.setattr(portfolio, "_openfigi_ticker", lambda *a, **k: None)
    monkeypatch.setattr(portfolio, "_fetch_by_ticker", lambda symbol: None)
    monkeypatch.setattr(portfolio, "_search_candidates", lambda *a, **k: [])
    monkeypatch.setattr(portfolio, "_fx_to_eur_rate", lambda ccy: None)
    # The trade-consistency check: no history means nothing to check against.
    monkeypatch.setattr(portfolio, "_close_on", lambda *a, **k: None)
    monkeypatch.setattr(portfolio, "_split_factor_since", lambda *a, **k: 1.0)
    # The share-class check: a listing whose name says nothing is never refused.
    monkeypatch.setattr(portfolio, "_yahoo_long_name", lambda *a, **k: None)
    # A 429 is waited out once; here that wait costs nothing.
    monkeypatch.setattr(portfolio.time, "sleep", lambda s: None)


def _quote(symbol, price, currency, previous_close=None):
    return {
        "ticker": symbol,
        "price": price,
        "currency": currency,
        "previous_close": previous_close,
    }


def test_us_holding_is_priced_from_its_own_listing_in_eur(conn, monkeypatch):
    """NYSE position: OpenFIGI's ticker, converted at the spot rate."""
    monkeypatch.setattr(
        portfolio, "_openfigi_ticker",
        lambda c, isin, mics: "TSM" if "XNYS" in mics else None,
    )
    monkeypatch.setattr(
        portfolio, "_fetch_by_ticker",
        lambda symbol: _quote("TSM", 400.0, "USD", 380.0) if symbol == "TSM" else None,
    )
    monkeypatch.setattr(portfolio, "_fx_to_eur_rate", lambda ccy: 0.5 if ccy == "USD" else None)

    result = portfolio.fetch_price_for_isin(
        conn,
        "US8740391003",
        "ADR ON TAIWAN SEMICONDUCTOR MANUFACTURING COMPANY LIMITED",
        degiro_exchange="NSY",
    )

    assert result["ticker"] == "TSM"
    assert result["currency"] == "EUR"
    assert result["price"] == 200.0
    # previous_close shares the spot rate, or the day move would be pure FX.
    assert result["previous_close"] == 190.0


def test_share_class_ticker_is_rewritten_for_yahoo(conn, monkeypatch):
    """OpenFIGI writes share classes as BRK/B, Yahoo as BRK-B."""
    fetched = []

    def _fetch(symbol):
        fetched.append(symbol)
        return _quote("BRK-B", 100.0, "USD") if symbol == "BRK-B" else None

    monkeypatch.setattr(portfolio, "_openfigi_ticker", _REAL_OPENFIGI_TICKER)
    monkeypatch.setattr(portfolio, "requests", _StubRequests("BRK/B"))
    monkeypatch.setattr(portfolio, "_fetch_by_ticker", _fetch)
    monkeypatch.setattr(portfolio, "_fx_to_eur_rate", lambda ccy: 1.0)

    result = portfolio.fetch_price_for_isin(
        conn, "US0846707026", "BERKSHIRE HATHAWAY INC-CL B", degiro_exchange="NSY",
    )

    assert fetched == ["BRK-B"]
    assert result["ticker"] == "BRK-B"


def test_eur_venue_keeps_hunting_for_a_eur_listing(conn, monkeypatch):
    """A European position is not settled with a converted foreign quote.

    XETRA's Yahoo listing answering in USD means the wrong listing was found,
    so the search below must still run — unlike a US venue, there is a EUR
    quote to hold out for.
    """
    monkeypatch.setattr(
        portfolio, "_openfigi_ticker",
        lambda c, isin, mics: "IQQH" if "XETR" in mics else None,
    )
    quotes = {
        "IQQH.DE": _quote("IQQH.DE", 20.0, "USD"),
        "INRG.AS": _quote("INRG.AS", 18.0, "EUR"),
    }
    monkeypatch.setattr(portfolio, "_fetch_by_ticker", lambda symbol: quotes.get(symbol))
    monkeypatch.setattr(portfolio, "_search_candidates",
                        lambda query, **k: [("INRG.AS", "AMS")])
    monkeypatch.setattr(portfolio, "_fx_to_eur_rate", lambda ccy: 0.5)

    result = portfolio.fetch_price_for_isin(
        conn, "IE00B1XNHC34x", "Some Clean Energy ETF",
        preferred_suffix=".AS", degiro_exchange="XET",
    )

    assert result["ticker"] == "INRG.AS"
    assert result["price"] == 18.0


def test_unknown_venue_still_falls_back_to_search(conn, monkeypatch):
    """A venue in neither MIC table (e.g. Tokyo) loses nothing it had before."""
    monkeypatch.setattr(portfolio, "_search_candidates",
                        lambda query, **k: [("SONY.AS", "AMS")])
    monkeypatch.setattr(portfolio, "_fetch_by_ticker",
                        lambda symbol: _quote("SONY.AS", 25.0, "EUR") if symbol == "SONY.AS" else None)

    result = portfolio.fetch_price_for_isin(
        conn, "JP3435000009", "SONY GROUP CORP", degiro_exchange="TSE",
    )

    assert result["ticker"] == "SONY.AS"


def test_a_london_ticker_loses_its_bloomberg_slash(conn, monkeypatch):
    """OpenFIGI answers "BP/" for BP; Yahoo knows it as BP.L."""
    fetched = []

    def _fetch(symbol):
        fetched.append(symbol)
        return _quote("BP.L", 500.0, "GBp") if symbol == "BP.L" else None

    monkeypatch.setattr(portfolio, "_openfigi_ticker", _REAL_OPENFIGI_TICKER)
    monkeypatch.setattr(portfolio, "requests", _StubRequests("BP/ LN Equity"))
    monkeypatch.setattr(portfolio, "_fetch_by_ticker", _fetch)
    monkeypatch.setattr(portfolio, "_fx_to_eur_rate", lambda ccy: 0.0116)   # pence → EUR

    result = portfolio.fetch_price_for_isin(
        conn, "GB0007980591", "BP PLC", degiro_exchange="LSE",
    )

    assert fetched == ["BP.L"]
    assert result["currency"] == "EUR"
    assert result["price"] == 5.8


def test_a_nordic_share_class_is_retried_with_a_dash(conn, monkeypatch):
    """Bloomberg writes NOVOB, Yahoo writes NOVO-B — only the second prices."""
    monkeypatch.setattr(portfolio, "_openfigi_ticker", lambda c, isin, mics: "NOVOB")
    monkeypatch.setattr(
        portfolio, "_fetch_by_ticker",
        lambda symbol: _quote("NOVO-B.CO", 300.0, "DKK") if symbol == "NOVO-B.CO" else None,
    )
    monkeypatch.setattr(portfolio, "_fx_to_eur_rate", lambda ccy: 0.134)

    result = portfolio.fetch_price_for_isin(
        conn, "DK0062498333", "NOVO NORDISK B", degiro_exchange="CPH",
    )

    assert result["ticker"] == "NOVO-B.CO"
    assert result["currency"] == "EUR"


def test_every_venue_row_is_shaped_like_a_venue():
    """The table is the whole point: a typo in it puts a venue back in the dark."""
    for code, (mics, suffix, quotes_eur) in portfolio._DEGIRO_VENUES.items():
        assert code.isupper() and code.isalnum(), code
        assert isinstance(mics, tuple) and mics, f"{code}: MICs must be a non-empty tuple"
        for mic in mics:
            assert len(mic) == 4 and mic.isupper(), f"{code}: {mic} is not a MIC"
        assert suffix == "" or (suffix.startswith(".") and suffix[1:].isalpha()), f"{code}: {suffix}"
        assert isinstance(quotes_eur, bool), code
    # The euro map the name search is pinned to is derived from it, never
    # maintained beside it.
    assert set(portfolio._DEGIRO_EXCHANGE_SUFFIX) == {
        code for code, (_m, _s, eur) in portfolio._DEGIRO_VENUES.items() if eur
    }
    # Venues seen in real uploads. Losing one of these is losing prices.
    assert {"EAM", "XET", "TDG", "NSY", "NDQ"} <= set(portfolio._DEGIRO_VENUES)
    # The operating MICs that name a whole exchange match nothing at OpenFIGI;
    # only its segments do. These two cost every Nasdaq and Milan holding its
    # authoritative ticker until 2026-09-04, silently.
    listed = {m for mics, _s, _e in portfolio._DEGIRO_VENUES.values() for m in mics}
    assert "XNAS" not in listed and "XMIL" not in listed
    assert portfolio._DEGIRO_VENUES["NDQ"][0] == ("XNGS", "XNMS", "XNCM")


class _StubRequests:
    """Minimal stand-in for the `requests` module used by _openfigi_ticker."""

    def __init__(self, ticker):
        self._ticker = ticker

    def post(self, *args, **kwargs):
        stub = self

        class _Response:
            status_code = 200

            @staticmethod
            def json():
                return [{"data": [{"ticker": stub._ticker}]}]

        return _Response()


class _StubResponses:
    """Serves a scripted status/payload per (isin, MIC) asked for."""

    def __init__(self, answers: dict, status: int = 200):
        self.answers = answers
        self.status = status
        self.asked: list[str] = []

    def post(self, *args, **kwargs):
        job = kwargs["json"][0]
        mic = job["micCode"]
        self.asked.append(mic)
        ticker = self.answers.get(mic)
        outer = self

        class _Response:
            status_code = outer.status

            @staticmethod
            def json():
                return [{"data": [{"ticker": ticker}]} if ticker else {"warning": "none"}]

        return _Response()


def test_openfigi_walks_the_venue_segments_until_one_answers(conn, monkeypatch):
    """
    A Nasdaq listing sits in exactly one segment. Asking only the operating MIC
    (XNAS) matched nothing at all, which is how every Nasdaq holding lost its
    authoritative ticker and fell through to the name search.
    """
    monkeypatch.setattr(portfolio, "_openfigi_ticker", _REAL_OPENFIGI_TICKER)
    stub = _StubResponses({"XNMS": "CRSP"})
    monkeypatch.setattr(portfolio, "requests", stub)

    assert portfolio._openfigi_ticker(conn, "CH0334081137", ("XNGS", "XNMS", "XNCM")) == "CRSP"
    # Stops as soon as it has an answer.
    assert stub.asked == ["XNGS", "XNMS"]


def test_openfigi_does_not_cache_a_miss_it_never_got_an_answer_for(conn, monkeypatch):
    """
    A 429 from the unauthenticated rate limit says nothing about the ISIN.
    Storing it as a known miss would blind the venue for the full 30 days over
    one busy minute.
    """
    monkeypatch.setattr(portfolio, "_openfigi_ticker", _REAL_OPENFIGI_TICKER)
    throttled = _StubResponses({"XNGS": "GOOGL"}, status=429)
    monkeypatch.setattr(portfolio, "requests", throttled)
    assert portfolio._openfigi_ticker(conn, "US02079K3059", ("XNGS",)) is None

    # Nothing was written, so the next call asks again and gets the real answer.
    ok = _StubResponses({"XNGS": "GOOGL"})
    monkeypatch.setattr(portfolio, "requests", ok)
    assert portfolio._openfigi_ticker(conn, "US02079K3059", ("XNGS",)) == "GOOGL"


def test_openfigi_caches_a_genuine_miss(conn, monkeypatch):
    """A real 200-with-no-data is worth remembering, so it is."""
    monkeypatch.setattr(portfolio, "_openfigi_ticker", _REAL_OPENFIGI_TICKER)
    stub = _StubResponses({})
    monkeypatch.setattr(portfolio, "requests", stub)
    assert portfolio._openfigi_ticker(conn, "LU2314763264", ("XNGS",)) is None

    stub.asked.clear()
    assert portfolio._openfigi_ticker(conn, "LU2314763264", ("XNGS",)) is None
    assert stub.asked == []   # answered from cache, not asked again


def test_us_position_prefers_its_own_listing_over_a_cached_cross_listing(conn, monkeypatch):
    """
    Tesla on Nasdaq had TL0.DE — its Frankfurt line — cached as the EUR ticker.
    Because `preferred_suffix` is None for a venue that does not quote in euro,
    _matches_pref waved that cache through before OpenFIGI was ever asked, and
    the refresh then wrote it back, so the position could never return to its
    own listing.
    """
    database.save_price(conn, isin="US88160R1014", name="TESLA INC", ticker="TL0.DE",
                        price=304.15, currency="EUR", previous_close=300.0)
    monkeypatch.setattr(
        portfolio, "_openfigi_ticker",
        lambda c, isin, mics: "TSLA" if "XNGS" in mics else None,
    )
    quotes = {
        "TL0.DE": _quote("TL0.DE", 304.15, "EUR"),
        "TSLA": _quote("TSLA", 400.0, "USD", 380.0),
    }
    monkeypatch.setattr(portfolio, "_fetch_by_ticker", lambda symbol: quotes.get(symbol))
    monkeypatch.setattr(portfolio, "_fx_to_eur_rate", lambda ccy: 0.8 if ccy == "USD" else None)

    result = portfolio.fetch_price_for_isin(
        conn, "US88160R1014", "TESLA INC", preferred_suffix=None, degiro_exchange="NDQ")

    assert result["ticker"] == "TSLA"
    assert result["price"] == 320.0     # 400 USD converted, not the Frankfurt line
    assert result["currency"] == "EUR"


def test_cached_ticker_still_wins_on_a_euro_venue(conn, monkeypatch):
    """The demotion above must not cost euro venues their cheap cache hit."""
    database.save_price(conn, isin="NL0010273215", name="ASML HOLDING N.V.",
                        ticker="ASML.AS", price=1467.4, currency="EUR", previous_close=1450.0)
    monkeypatch.setattr(portfolio, "_fetch_by_ticker",
                        lambda symbol: _quote("ASML.AS", 1467.4, "EUR") if symbol == "ASML.AS" else None)

    result = portfolio.fetch_price_for_isin(
        conn, "NL0010273215", "ASML HOLDING N.V.",
        preferred_suffix=".AS", degiro_exchange="EAM")

    assert result["ticker"] == "ASML.AS"   # answered from cache, OpenFIGI never consulted



# ---------------------------------------------------------------------------
# A searched ticker has to agree with what the user paid
# ---------------------------------------------------------------------------

_ISIN = "XX0000000001"   # not a real instrument: the check is generic


def _trade(conn, day, qty, eur):
    conn.execute(
        "INSERT INTO transactions (date, name, isin, transaction_type, quantity, price, value_eur) "
        "VALUES (?, 'SOME NASDAQ-100 ETF', ?, 'BUY', ?, ?, ?)",
        (day, _ISIN, qty, eur / qty, -eur),
    )
    conn.commit()


def _two_candidates(monkeypatch, closes):
    """Search returns the wrong fund first, the right one second."""
    monkeypatch.setattr(portfolio, "_search_candidates",
                        lambda *a, **k: [("WRONG.DE", "GER"), ("RIGHT.DE", "GER")])
    quotes = {"WRONG.DE": _quote("WRONG.DE", 1458.6, "EUR"), "RIGHT.DE": _quote("RIGHT.DE", 246.75, "EUR")}
    monkeypatch.setattr(portfolio, "_fetch_by_ticker", lambda s: quotes.get(s))
    calls = []
    def close_on(symbol, day):
        calls.append(symbol)
        return closes.get(symbol)
    monkeypatch.setattr(portfolio, "_close_on", close_on)
    return calls


def test_a_candidate_priced_far_from_the_users_trade_is_rejected(conn, monkeypatch):
    """The name search lands on a sibling fund at ~7x the price. On the day of
    the user's trade it closed at 1.450 while the trade was at 209: a factor,
    not a market move. The next candidate agrees with the trade and wins."""
    _trade(conn, "2025-12-17", 30, 30 * 209.35)
    _two_candidates(monkeypatch, {"WRONG.DE": 1450.0, "RIGHT.DE": 210.0})

    result = portfolio.fetch_price_for_isin(conn, _ISIN, "SOME NASDAQ-100 ETF", preferred_suffix=".DE")
    assert result["ticker"] == "RIGHT.DE"


def test_a_cached_ticker_that_fails_the_check_is_resolved_again(conn, monkeypatch):
    """The cache is where a wrong guess used to live forever."""
    _trade(conn, "2025-12-17", 30, 30 * 209.35)
    database.save_price(conn, isin=_ISIN, name="SOME NASDAQ-100 ETF", ticker="WRONG.DE",
                        price=1458.6, currency="EUR", previous_close=None)
    _two_candidates(monkeypatch, {"WRONG.DE": 1450.0, "RIGHT.DE": 210.0})

    result = portfolio.fetch_price_for_isin(conn, _ISIN, "SOME NASDAQ-100 ETF", preferred_suffix=".DE")
    assert result["ticker"] == "RIGHT.DE"


def test_without_a_trade_there_is_nothing_to_check_against(conn, monkeypatch):
    """No evidence, no rejection: the first candidate wins, as it always did."""
    _two_candidates(monkeypatch, {"WRONG.DE": 1450.0, "RIGHT.DE": 210.0})
    result = portfolio.fetch_price_for_isin(conn, _ISIN, "SOME NASDAQ-100 ETF", preferred_suffix=".DE")
    assert result["ticker"] == "WRONG.DE"


def test_without_history_the_candidate_is_accepted(conn, monkeypatch):
    """A candidate Yahoo has no history for cannot be checked; refusing it would
    cost a position its price over missing data, not over evidence."""
    _trade(conn, "2025-12-17", 30, 30 * 209.35)
    _two_candidates(monkeypatch, {})
    result = portfolio.fetch_price_for_isin(conn, _ISIN, "SOME NASDAQ-100 ETF", preferred_suffix=".DE")
    assert result["ticker"] == "WRONG.DE"


def test_a_split_since_the_trade_is_taken_into_account(conn, monkeypatch):
    """Bought at 1.000 before a 10-for-1 split; Yahoo's history says 100 for that
    day. That is the same share, not a different instrument."""
    _trade(conn, "2024-01-10", 1, 1000.0)
    _two_candidates(monkeypatch, {"WRONG.DE": 100.0})
    monkeypatch.setattr(portfolio, "_split_factor_since", lambda s, d: 10.0)
    result = portfolio.fetch_price_for_isin(conn, _ISIN, "SOME NASDAQ-100 ETF", preferred_suffix=".DE")
    assert result["ticker"] == "WRONG.DE"


def test_the_verdict_is_cached_across_refreshes(conn, monkeypatch):
    """The refresh loop asks on every pass; the history lookup happens once."""
    _trade(conn, "2025-12-17", 30, 30 * 209.35)
    calls = _two_candidates(monkeypatch, {"WRONG.DE": 1450.0, "RIGHT.DE": 210.0})
    portfolio.fetch_price_for_isin(conn, _ISIN, "SOME NASDAQ-100 ETF", preferred_suffix=".DE")
    portfolio.fetch_price_for_isin(conn, _ISIN, "SOME NASDAQ-100 ETF", preferred_suffix=".DE")
    assert calls.count("WRONG.DE") == 1
