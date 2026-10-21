"""
holdings_service.listing_quote — a position's price in the currency it trades in.

TSM is stored converted (EUR 392,13) while its chart is Yahoo's dollar history
($446,57 at the end). The page printed that line with a euro sign, 14% above
the price beside it. The price is now divided back by the rate it was stored
at, so header and chart are one number in one currency.
"""

import pytest

from app.services import holdings_service as hs


def test_a_euro_listing_is_left_as_stored():
    q = hs.listing_quote({"price": 64.17, "previous_close": 64.0, "currency": "EUR"})

    assert q == {"currency": "EUR", "price": 64.17, "previous_close": 64.0}


def test_a_converted_listing_is_restated_in_its_own_currency():
    q = hs.listing_quote(
        {
            "price": 392.1331,
            "previous_close": 396.3861,
            "currency": "EUR",
            "quote_currency": "USD",
            "quote_fx_rate": 0.8781,
        }
    )

    assert q["currency"] == "USD"
    assert q["price"] == pytest.approx(392.1331 / 0.8781, abs=1e-3)
    assert q["previous_close"] == pytest.approx(396.3861 / 0.8781, abs=1e-3)


def test_without_a_rate_there_is_no_price_rather_than_a_guess():
    q = hs.listing_quote({"price": 392.13, "currency": "EUR", "quote_currency": "USD"})

    assert q == {"currency": "USD", "price": None, "previous_close": None}
