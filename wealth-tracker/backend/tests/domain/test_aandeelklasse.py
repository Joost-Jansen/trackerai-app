"""
A Dist and an Acc class of one fund are two different instruments.

On real data it went wrong like this: "VANGUARD FTSE ALL-WORLD UCITS ETF USD DIS"
got VWCE, the Acc class, and "VANGUARD S&P 500 UCITS ETF USD DIS" got VUAA. Both
prices are a few percent off the right one, so the price check let them
through, and the position was valued as a fund the user does not hold.

It started at OpenFIGI: that translates ISIN plus exchange straight into the
right ticker, but without a key it allows 25 requests per minute, and a first
price round over more ISINs got a 429 halfway. Everything after that fell back
on Yahoo's name search.

Every network request is simulated here.
"""

import sqlite3

import pytest

from domain import database
from domain.portfolio import positions as portfolio


@pytest.fixture()
def conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    database.init_db(conn)
    return conn


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(portfolio, "_openfigi_ticker", lambda *a, **k: None)
    monkeypatch.setattr(portfolio, "_fetch_by_ticker", lambda symbol: None)
    monkeypatch.setattr(portfolio, "_search_candidates", lambda *a, **k: [])
    monkeypatch.setattr(portfolio, "_fx_to_eur_rate", lambda ccy: None)
    monkeypatch.setattr(portfolio, "_close_on", lambda *a, **k: None)
    monkeypatch.setattr(portfolio, "_split_factor_since", lambda *a, **k: 1.0)
    monkeypatch.setattr(portfolio, "_yahoo_long_name", lambda *a, **k: None)


def _price(symbol, unit_price):
    return {"ticker": symbol, "price": unit_price, "currency": "EUR", "previous_close": None}


# ---------------------------------------------------------------------------
# The class from a name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, share_class", [
    ("VANGUARD FTSE ALL-WORLD UCITS ETF USD DIS", "dist"),
    ("ISHARES STOXX EUROPE 600 UCITS (DE) EUR (DIST)", "dist"),
    ("Vanguard FTSE All-World UCITS ETF USD Distributing", "dist"),
    ("ISHARES CORE S&P 500 UCITS ETF USD (ACC)", "acc"),
    ("Vanguard FTSE All-World UCITS ETF USD Accumulation", "acc"),
    ("Vanguard FTSE All-World UCITS ETF", None),
    ("APPLE INC", None),
    ("ASML HOLDING", None),
    ("", None),
    (None, None),
])
def test_the_class_is_in_the_name(name, share_class):
    assert portfolio._share_class(name) == share_class


def test_a_word_that_happens_to_start_that_way_does_not_count():
    """'DISCOVERY' and 'ACCENTURE' are not classes."""
    assert portfolio._share_class("WARNER BROS DISCOVERY") is None
    assert portfolio._share_class("ACCENTURE PLC") is None


# ---------------------------------------------------------------------------
# The search
# ---------------------------------------------------------------------------

DIS = ("IE00B3RBWM25", "VANGUARD FTSE ALL-WORLD UCITS ETF USD DIS")
NAMES = {
    "VWCE.DE": "Vanguard FTSE All-World UCITS ETF USD Accumulation",
    "VGWL.DE": "Vanguard FTSE All-World UCITS ETF",
}


def _search_stubs(monkeypatch, candidates):
    prices = {"VWCE.DE": _price("VWCE.DE", 166.86), "VGWL.DE": _price("VGWL.DE", 158.10)}
    monkeypatch.setattr(portfolio, "_search_candidates", lambda q, **k: candidates)
    monkeypatch.setattr(portfolio, "_fetch_by_ticker", lambda s: prices.get(s))
    monkeypatch.setattr(portfolio, "_yahoo_long_name", lambda c, s: NAMES.get(s))


def test_a_dist_position_does_not_get_the_acc_class(conn, monkeypatch):
    _search_stubs(monkeypatch, [("VWCE.DE", "GER"), ("VGWL.DE", "GER")])
    assert portfolio.fetch_price_for_isin(conn, *DIS)["ticker"] == "VGWL.DE"


def test_an_acc_position_does_not_get_the_dist_class(conn, monkeypatch):
    names = {"VWCE.DE": "Vanguard FTSE All-World UCITS ETF USD Accumulation",
             "VGWL.DE": "Vanguard FTSE All-World UCITS ETF USD Distributing"}
    _search_stubs(monkeypatch, [("VGWL.DE", "GER"), ("VWCE.DE", "GER")])
    monkeypatch.setattr(portfolio, "_yahoo_long_name", lambda c, s: names.get(s))
    result = portfolio.fetch_price_for_isin(conn, "IE00BK5BQT80", "VANGUARD FTSE ALL-WORLD UCITS ETF USD ACC")
    assert result["ticker"] == "VWCE.DE"


def test_a_wrong_class_in_the_cache_is_looked_up_again(conn, monkeypatch):
    """Whoever already had VWCE in the cache now loses it and gets the right one."""
    database.save_price(conn, DIS[0], DIS[1], "VWCE.DE", 166.86, "EUR")
    _search_stubs(monkeypatch, [("VWCE.DE", "GER"), ("VGWL.DE", "GER")])
    assert portfolio.fetch_price_for_isin(conn, *DIS)["ticker"] == "VGWL.DE"


def test_a_name_without_a_class_is_not_held_back(conn, monkeypatch):
    """Yahoo usually puts nothing on the Dist listing: that must not be a refusal."""
    _search_stubs(monkeypatch, [("VGWL.DE", "GER")])
    assert portfolio.fetch_price_for_isin(conn, *DIS)["ticker"] == "VGWL.DE"


def test_a_share_costs_no_extra_lookups(conn, monkeypatch):
    """Only a name with a class asks Yahoo for the candidate's name."""
    def not_ask(*a, **k):
        raise AssertionError("naam opgevraagd voor een positie zonder klasse")
    monkeypatch.setattr(portfolio, "_search_candidates", lambda q, **k: [("ASML.AS", "AMS")])
    monkeypatch.setattr(portfolio, "_fetch_by_ticker", lambda s: _price(s, 600.0))
    monkeypatch.setattr(portfolio, "_yahoo_long_name", not_ask)
    assert portfolio.fetch_price_for_isin(conn, "NL0010273215", "ASML HOLDING")["ticker"] == "ASML.AS"


# ---------------------------------------------------------------------------
# OpenFIGI
# ---------------------------------------------------------------------------

class _Answer:
    def __init__(self, status, data=None, headers=None):
        self.status_code = status
        self._data = data
        self.headers = headers or {}

    def json(self):
        return self._data


class _Server:
    """Returns the answers in order and remembers what was asked."""
    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.requests.append(headers)
        return self.answers.pop(0)


_MATCH = _Answer(200, [{"data": [{"ticker": "VGWL GY"}]}])


@pytest.fixture()
def real_openfigi(monkeypatch):
    """The real _openfigi_ticker against a simulated server; waiting costs nothing."""
    monkeypatch.setattr(portfolio, "_openfigi_ticker", _REAL_OPENFIGI)
    waited = []
    monkeypatch.setattr(portfolio.time, "sleep", waited.append)
    monkeypatch.delenv("OPENFIGI_API_KEY", raising=False)
    return waited


_REAL_OPENFIGI = portfolio._openfigi_ticker


def test_after_a_429_it_waits_and_asks_again(conn, monkeypatch, real_openfigi):
    server = _Server(_Answer(429, headers={"Retry-After": "7"}), _MATCH)
    monkeypatch.setattr(portfolio, "requests", server)
    assert portfolio._openfigi_ticker(conn, DIS[0], ("XETR",)) == "VGWL"
    assert real_openfigi == [7.0]
    assert len(server.requests) == 2


def test_without_a_wait_time_in_the_response_it_waits_the_default(conn, monkeypatch, real_openfigi):
    monkeypatch.setattr(portfolio, "requests", _Server(_Answer(429), _MATCH))
    assert portfolio._openfigi_ticker(conn, DIS[0], ("XETR",)) == "VGWL"
    assert real_openfigi == [portfolio._OPENFIGI_DEFAULT_WAIT_SECONDS]


def test_a_too_long_wait_time_is_not_sat_out(conn, monkeypatch, real_openfigi):
    """The price round has a deadline; then rather the next round."""
    server = _Server(_Answer(429, headers={"Retry-After": "600"}))
    monkeypatch.setattr(portfolio, "requests", server)
    assert portfolio._openfigi_ticker(conn, DIS[0], ("XETR",)) is None
    assert real_openfigi == []
    assert len(server.requests) == 1


def test_two_429s_are_not_stored_as_a_miss(conn, monkeypatch, real_openfigi):
    monkeypatch.setattr(portfolio, "requests", _Server(_Answer(429), _Answer(429)))
    assert portfolio._openfigi_ticker(conn, DIS[0], ("XETR",)) is None
    # A next round simply asks again, and then gets an answer.
    monkeypatch.setattr(portfolio, "requests", _Server(_MATCH))
    assert portfolio._openfigi_ticker(conn, DIS[0], ("XETR",)) == "VGWL"


def test_an_api_key_is_sent_when_there_is_one(conn, monkeypatch, real_openfigi):
    monkeypatch.setenv("OPENFIGI_API_KEY", "sleutel-uit-de-omgeving")
    server = _Server(_MATCH)
    monkeypatch.setattr(portfolio, "requests", server)
    portfolio._openfigi_ticker(conn, DIS[0], ("XETR",))
    assert server.requests[0]["X-OPENFIGI-APIKEY"] == "sleutel-uit-de-omgeving"


def test_without_a_key_no_key_is_sent(conn, monkeypatch, real_openfigi):
    server = _Server(_MATCH)
    monkeypatch.setattr(portfolio, "requests", server)
    portfolio._openfigi_ticker(conn, DIS[0], ("XETR",))
    assert "X-OPENFIGI-APIKEY" not in server.requests[0]
