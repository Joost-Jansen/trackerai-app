"""The Tradegate quote adapter — reading its JSON, and surviving Tradegate.

All offline: the HTTP call, the clock and the sleep are stubbed. The live
counterpart is test_tradegate_live.py, which only runs with TRADEGATE_LIVE=1.

The payloads below are shaped after real answers from refresh.php (14 Sep
2026), including its habit of sending some numbers as German strings.
"""

import datetime

import pytest
import requests

from app.services import tradegate_service as tg

# A real answer, verbatim, for IE00B3XXRP09 — note "low" as a string.
REAL_PAYLOAD = {
    "bid": 125.38,
    "ask": 125.465,
    "bidsize": 1000,
    "asksize": 1000,
    "delta": 0.08,
    "stueck": 25575,
    "umsatz": 3198126,
    "avg": 125.0489,
    "executions": 3991,
    "last": 125.36,
    "high": 125.545,
    "low": "124,80",
    "close": 125.265,
}

# Wednesday 16 September 2026, mid-session.
IN_SESSION = datetime.datetime(2026, 9, 16, 14, 0, 0)
# The same day, after Tradegate's 22:00 close.
AFTER_CLOSE = datetime.datetime(2026, 9, 16, 22, 30, 0)


class UnexpectedNetwork(BaseException):
    """Not an Exception: get_quote swallows every Exception by design, and a
    network call that should not have happened must not be swallowed."""


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=None):
        self.status_code = status_code
        self._json = json_body
        if text is None:
            text = "" if json_body is None else "{...}"
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeHttp:
    """Answers from a script, one per call, and counts the calls."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Fresh cache, no sleeping, a controllable monotonic clock, and a
    network that fails loudly unless a test scripts it."""
    tg.clear_cache()
    clock = Clock()
    monkeypatch.setattr(tg, "_monotonic", clock)
    monkeypatch.setattr(tg, "_sleep", lambda s: None)
    monkeypatch.setattr(tg, "_now", lambda: IN_SESSION)
    monkeypatch.setattr(tg, "_http_get", FakeHttp(UnexpectedNetwork("unexpected network call")))
    monkeypatch.delenv("TRADEGATE_QUOTES", raising=False)
    yield clock
    tg.clear_cache()


def _script(monkeypatch, *answers) -> FakeHttp:
    http = FakeHttp(*answers)
    monkeypatch.setattr(tg, "_http_get", http)
    return http


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("isin", ["IE00B4L5YC18", "IE00B3XXRP09", "US0378331005", "DE0007664039", "NL0010773842"])
def test_real_isins_pass_the_checksum(isin):
    assert tg.is_valid_isin(isin)


@pytest.mark.parametrize(
    "isin",
    [
        "US0378331006",  # one digit off in the check digit
        "IE00B4L5YC1",  # too short
        "ie00b4l5yc18",  # lower case is not normalised here
        "1E00B4L5YC18",  # country code must be letters
        "",
        None,
        12345,
    ],
)
def test_malformed_isins_are_rejected(isin):
    assert not tg.is_valid_isin(isin)


@pytest.mark.parametrize(
    "raw, expected",
    [
        (55.52, 55.52),
        (0, 0.0),
        ("124,80", 124.8),
        ("1 234,56", 1234.56),
        ("1 234,56", 1234.56),
        ("1.234,56", 1234.56),
        ("-1,39%", -1.39),
        ("55.52", 55.52),
        ("./.", None),
        ("", None),
        ("abc", None),
        (None, None),
        (True, None),
        (float("nan"), None),
    ],
)
def test_numbers_are_read_in_both_notations(raw, expected):
    assert tg.parse_number(raw) == expected


# ---------------------------------------------------------------------------
# Reading a quote
# ---------------------------------------------------------------------------


def test_last_bid_and_ask_stay_three_separate_numbers():
    q = tg.parse_quote("IE00B3XXRP09", REAL_PAYLOAD, IN_SESSION)
    assert (q["last"], q["bid"], q["ask"]) == (125.36, 125.38, 125.465)
    assert q["previous_close"] == 125.265
    assert q["low"] == 124.8  # the German-string field
    assert q["volume"] == 25575 and q["executions"] == 3991
    assert q["currency"] == "EUR"
    assert q["venue"] == "TDG"


def test_a_missing_last_is_never_filled_from_bid_ask_or_their_middle():
    payload = {**REAL_PAYLOAD, "last": "./."}
    q = tg.parse_quote("IE00B3XXRP09", payload, IN_SESSION)
    assert q["last"] is None
    assert q["bid"] == 125.38 and q["ask"] == 125.465


def test_zero_bid_and_ask_mean_no_quote_not_a_price_of_zero():
    payload = {**REAL_PAYLOAD, "bid": "0,00", "ask": "0,00", "state": "I"}
    q = tg.parse_quote("IE00B3XXRP09", payload, IN_SESSION)
    assert q["bid"] is None and q["ask"] is None
    assert q["trading_state"] == "I"


def test_the_quote_carries_no_time_of_its_own_only_the_fetch_time():
    q = tg.parse_quote("IE00B3XXRP09", REAL_PAYLOAD, IN_SESSION)
    assert q["quote_time"] is None
    assert q["fetched_at"] == "2026-09-16T14:00:00"


def test_an_explicit_currency_wins_over_the_eur_default():
    q = tg.parse_quote("XS0000000009", {**REAL_PAYLOAD, "waehrung": "usd"}, IN_SESSION)
    assert q["currency"] == "USD"


def test_session_and_traded_today_are_reported():
    assert tg.parse_quote("IE00B3XXRP09", REAL_PAYLOAD, IN_SESSION)["session_open"] is True
    assert tg.parse_quote("IE00B3XXRP09", REAL_PAYLOAD, AFTER_CLOSE)["session_open"] is False
    saturday = datetime.datetime(2026, 9, 19, 12, 0)
    assert tg.parse_quote("IE00B3XXRP09", REAL_PAYLOAD, saturday)["session_open"] is False

    quiet = tg.parse_quote("IE00B3XXRP09", {**REAL_PAYLOAD, "executions": 0, "stueck": 0}, IN_SESSION)
    assert quiet["traded_today"] is False
    unknown = {k: v for k, v in REAL_PAYLOAD.items() if k != "executions"}
    assert tg.parse_quote("IE00B3XXRP09", unknown, IN_SESSION)["traded_today"] is None


def test_the_terms_link_tradegate_sometimes_adds_is_ignored():
    payload = {**REAL_PAYLOAD, "terms_and_conditions": "https://www.tradegatebsx.com/nutzungsbedingung.php"}
    assert tg.parse_quote("IE00B3XXRP09", payload, IN_SESSION)["last"] == 125.36


@pytest.mark.parametrize("payload", [None, [], "text", {}, {"bid": "0,00", "ask": "./.", "last": 0}])
def test_a_payload_without_any_price_is_no_data(payload):
    with pytest.raises(tg.TradegateNoData):
        tg.parse_quote("IE00B3XXRP09", payload, IN_SESSION)


# ---------------------------------------------------------------------------
# get_quote: statuses, cache, failures
# ---------------------------------------------------------------------------


def test_an_ok_answer(monkeypatch):
    http = _script(monkeypatch, FakeResponse(json_body=REAL_PAYLOAD))
    q = tg.get_quote("IE00B3XXRP09")
    assert q["status"] == "ok" and q["stale"] is False and q["last"] == 125.36
    url, kwargs = http.calls[0]
    assert url == tg.REFRESH_URL and kwargs["params"] == {"isin": "IE00B3XXRP09"}
    assert kwargs["timeout"] == tg.TIMEOUT
    assert kwargs["allow_redirects"] is False
    assert "stock-tracker" in kwargs["headers"]["User-Agent"]


def test_an_invalid_isin_costs_no_request():
    # The autouse network raises on any call; reaching it would fail the test.
    assert tg.get_quote("US0378331006")["status"] == "invalid_isin"
    assert tg.get_quote("")["status"] == "invalid_isin"


def test_the_switch_turns_it_off_without_a_request(monkeypatch):
    monkeypatch.setenv("TRADEGATE_QUOTES", "off")
    assert tg.get_quote("IE00B3XXRP09")["status"] == "disabled"


def test_a_second_render_within_the_ttl_is_served_from_cache(monkeypatch, offline):
    http = _script(monkeypatch, FakeResponse(json_body=REAL_PAYLOAD))
    tg.get_quote("IE00B3XXRP09")
    offline.t += tg.TTL_SESSION_SECONDS - 1
    tg.get_quote("IE00B3XXRP09")
    assert len(http.calls) == 1
    offline.t += 2
    tg.get_quote("IE00B3XXRP09")
    assert len(http.calls) == 2


def test_outside_the_session_the_cache_lasts_longer(monkeypatch, offline):
    monkeypatch.setattr(tg, "_now", lambda: AFTER_CLOSE)
    http = _script(monkeypatch, FakeResponse(json_body=REAL_PAYLOAD))
    tg.get_quote("IE00B3XXRP09")
    offline.t += tg.TTL_SESSION_SECONDS + 60
    tg.get_quote("IE00B3XXRP09")
    assert len(http.calls) == 1


def test_timeouts_are_retried_a_bounded_number_of_times(monkeypatch):
    http = _script(monkeypatch, requests.Timeout("slow"))
    q = tg.get_quote("IE00B3XXRP09")
    assert q["status"] == "unavailable"
    assert len(http.calls) == tg.MAX_ATTEMPTS


def test_a_server_error_is_retried_and_can_recover(monkeypatch):
    http = _script(monkeypatch, FakeResponse(status_code=502), FakeResponse(json_body=REAL_PAYLOAD))
    q = tg.get_quote("IE00B3XXRP09")
    assert q["status"] == "ok"
    assert len(http.calls) == 2


@pytest.mark.parametrize("code", [301, 302, 403, 429])
def test_a_refusal_is_not_retried_and_backs_off(monkeypatch, offline, code):
    http = _script(monkeypatch, FakeResponse(status_code=code, text="<html>"))
    assert tg.get_quote("IE00B3XXRP09")["status"] == "refused"
    assert len(http.calls) == 1
    offline.t += tg.TTL_UNAVAILABLE_SECONDS + 1  # a normal failure would retry by now
    tg.get_quote("IE00B3XXRP09")
    assert len(http.calls) == 1


def test_an_unknown_isin_is_no_data_and_not_asked_again_soon(monkeypatch, offline):
    # What Tradegate really does: HTTP 200, text/html, empty body.
    http = _script(monkeypatch, FakeResponse(status_code=200, text=""))
    assert tg.get_quote("IE00B4L5YC18")["status"] == "no_data"
    offline.t += 60 * 60
    assert tg.get_quote("IE00B4L5YC18")["status"] == "no_data"
    assert len(http.calls) == 1


def test_html_instead_of_json_is_no_data(monkeypatch):
    _script(monkeypatch, FakeResponse(status_code=200, text="<!DOCTYPE html>"))
    assert tg.get_quote("IE00B3XXRP09")["status"] == "no_data"


def test_an_outage_after_a_good_quote_serves_it_marked_stale(monkeypatch, offline):
    _script(monkeypatch, FakeResponse(json_body=REAL_PAYLOAD))
    tg.get_quote("IE00B3XXRP09")

    offline.t += tg.TTL_SESSION_SECONDS + 30
    http = _script(monkeypatch, requests.ConnectionError("down"))
    q = tg.get_quote("IE00B3XXRP09")
    assert q["status"] == "ok"
    assert q["stale"] is True
    assert q["last"] == 125.36
    assert q["age_seconds"] == tg.TTL_SESSION_SECONDS + 30
    assert "ConnectionError" in q["error"]

    # And the outage itself is cached: the next render does not hammer.
    tg.get_quote("IE00B3XXRP09")
    assert len(http.calls) == tg.MAX_ATTEMPTS


def test_an_outage_without_any_earlier_quote_says_so(monkeypatch, offline):
    http = _script(monkeypatch, requests.ConnectionError("down"))
    q = tg.get_quote("IE00B3XXRP09")
    assert q["status"] == "unavailable"
    assert "last" not in q
    tg.get_quote("IE00B3XXRP09")
    assert len(http.calls) == tg.MAX_ATTEMPTS
    offline.t += tg.TTL_UNAVAILABLE_SECONDS + 1
    tg.get_quote("IE00B3XXRP09")
    assert len(http.calls) == 2 * tg.MAX_ATTEMPTS


def test_an_unexpected_exception_never_escapes(monkeypatch):
    _script(monkeypatch, RuntimeError("something odd"))
    q = tg.get_quote("IE00B3XXRP09")
    assert q["status"] == "unavailable"


def test_lowercase_input_is_normalised_before_the_lookup(monkeypatch):
    http = _script(monkeypatch, FakeResponse(json_body=REAL_PAYLOAD))
    assert tg.get_quote(" ie00b3xxrp09 ")["status"] == "ok"
    assert http.calls[0][1]["params"] == {"isin": "IE00B3XXRP09"}
