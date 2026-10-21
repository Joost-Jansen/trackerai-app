"""The Tradegate adapter against the real website. Skipped unless asked for.

    TRADEGATE_LIVE=1 backend/venv/bin/python -m pytest backend/tests/test_tradegate_live.py -v

Never part of the normal suite: it needs the internet, it depends on
Tradegate's opening hours, and every run is requests to a site whose terms do
not invite them. Five ISINs, one request each, through the real cache.
"""

import os
import time

import pytest

from app.services import tradegate_service as tg

pytestmark = pytest.mark.skipif(os.environ.get("TRADEGATE_LIVE") != "1", reason="live Tradegate check; set TRADEGATE_LIVE=1")

LIVE_ISINS = [
    "IE00B4L5YC18",  # iShares MSCI EM (Acc) — held on TDG in the owner's portfolio
    "IE00B3XXRP09",  # Vanguard S&P 500 (Dist)
    "NL0010773842",  # NN Group
    "US0378331005",  # Apple
    "DE0007664039",  # Volkswagen Vz.
]


@pytest.fixture(autouse=True, scope="module")
def fresh_cache():
    tg.clear_cache()
    yield
    tg.clear_cache()


@pytest.mark.parametrize("isin", LIVE_ISINS)
def test_a_real_quote_comes_back_sane(isin):
    q = tg.get_quote(isin)
    time.sleep(1.5)  # be gentle between instruments
    assert q["status"] == "ok", q
    assert q["stale"] is False
    assert q["currency"] == "EUR"
    assert q["quote_time"] is None
    assert q["last"] is not None and q["last"] > 0
    if q["bid"] is not None and q["ask"] is not None:
        assert q["bid"] <= q["ask"]
    if q["low"] is not None and q["high"] is not None:
        assert q["low"] <= q["high"]
    print(
        f"\n{isin}: last={q['last']} bid={q['bid']} ask={q['ask']} "
        f"close={q['previous_close']} exec={q['executions']} fetched={q['fetched_at']}"
    )


def test_a_second_call_is_served_from_the_cache(monkeypatch):
    tg.get_quote("IE00B4L5YC18")

    def no_network(*args, **kwargs):
        raise AssertionError("should have come from the cache")

    monkeypatch.setattr(tg, "_http_get", no_network)
    assert tg.get_quote("IE00B4L5YC18")["status"] == "ok"


def test_a_well_formed_isin_tradegate_does_not_list_is_no_data():
    # A valid check digit on a number no instrument has.
    isin = next(f"NL000000000{d}" for d in range(10) if tg.is_valid_isin(f"NL000000000{d}"))
    q = tg.get_quote(isin)
    assert q["status"] == "no_data", q
