"""
dashboard_service._day_anchors — one answer to "what did today do".

Three sources used to answer it: the hero chip reads the price cache, the daily
value series reads yfinance's daily closes, and the intraday series its 5-minute
feed, which runs about a quarter of an hour behind. They disagreed by several
euros on the same screen — the card said +€74,28 under a chip saying +€79,19.

The bars now supply the shape of the day and these two figures its endpoints, so
the chip and the card cannot differ. That only holds if the anchors are computed
off exactly the prices the chip uses, and if a portfolio the chip cannot fully
price does not get anchored at all.

Each test was watched fail first (rule 3): by anchoring a partial sum, by
swapping previous_close for price, and by dropping the shares multiplier.
"""

import datetime

import pytest

from app.services import dashboard_service as ds


def _pos(isin="X1", shares=10.0, value=1100.0):
    return {"isin": isin, "name": "Fund", "ticker": "X1.AS",
            "shares_held": shares, "current_value": value}


def _price(price=110.0, prev=100.0, currency="EUR", fetched_at=None):
    """A row of the price cache. `fetched_at` defaults to now, because that is
    what the refresher (app/core/price_refresh.py) keeps it at during market
    hours and what anchoring requires — see the staleness tests below."""
    return {
        "price": price, "previous_close": prev, "currency": currency,
        "fetched_at": fetched_at or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def test_anchors_are_shares_times_each_price():
    anchors = ds._day_anchors([_pos(shares=10.0)], {"X1": _price(price=110.0, prev=100.0)})
    assert anchors == (1000.0, 1100.0)


def test_anchors_reproduce_the_hero_chip_exactly():
    """The whole point: chip delta == live − prev_close, to the cent."""
    positions = [_pos("A", shares=10.0, value=1100.0), _pos("B", shares=4.0, value=840.0)]
    prices = {"A": _price(price=110.0, prev=100.0), "B": _price(price=210.0, prev=200.0)}

    prev_close, live = ds._day_anchors(positions, prices)
    chip = ds.portfolio_day_change(positions, prices)

    assert round(live - prev_close, 2) == chip["delta_eur"]
    assert round((live / prev_close - 1) * 100, 2) == chip["pct"]


def test_a_position_without_a_previous_close_blocks_anchoring():
    positions = [_pos("A"), _pos("B")]
    prices = {"A": _price(), "B": {"price": 210.0, "previous_close": None, "currency": "EUR"}}
    # Anchoring part of the portfolio to a chart drawn from all of it would be
    # worse than not anchoring: the day would gain or lose a whole position.
    assert ds._day_anchors(positions, prices) is None


def test_a_non_eur_position_blocks_anchoring():
    positions = [_pos("A"), _pos("B")]
    prices = {"A": _price(), "B": _price(currency="USD")}
    assert ds._day_anchors(positions, prices) is None


def test_a_missing_price_blocks_anchoring():
    assert ds._day_anchors([_pos("A"), _pos("B")], {"A": _price()}) is None


def test_no_positions_gives_no_anchors():
    assert ds._day_anchors([], {"X1": _price()}) is None


def test_a_price_from_yesterday_blocks_anchoring():
    """Fresh bars pinned to a stale cache is not one answer, it is two.

    The bars are today's; the cache, unrefreshed, is last night's. Anchoring
    across that put a cliff at the end of the line the size of everything the
    market had done since — measured at €435 on a nine-day-old cache.
    """
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    assert ds._day_anchors([_pos()], {"X1": _price(fetched_at=f"{yesterday} 22:14:03")}) is None


def test_one_stale_price_among_fresh_ones_blocks_anchoring():
    old = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
    prices = {"A": _price(), "B": _price(fetched_at=f"{old} 17:31:00")}
    assert ds._day_anchors([_pos("A"), _pos("B")], prices) is None


def test_a_price_row_without_a_timestamp_blocks_anchoring():
    """Pre-migration rows carry no fetched_at; unknown age is not fresh."""
    row = {"price": 110.0, "previous_close": 100.0, "currency": "EUR"}
    assert ds._day_anchors([_pos()], {"X1": row}) is None


# ---------------------------------------------------------------------------
# Where they land: get_intraday replaces the last bar and the baseline
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path, monkeypatch):
    from domain import database
    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    c = database.connect("alice")
    database.init_db(c)  # get_or_fetch writes to api_cache
    return c


def _stub_bars(monkeypatch, points, prev_close):
    monkeypatch.setattr(
        ds, "_build_intraday", lambda tx, prices: {"points": list(points), "prev_close": prev_close}
    )


def test_anchors_replace_both_endpoints_and_leave_the_shape(conn, monkeypatch):
    # points[0] is the previous close, prepended by _build_intraday.
    bars = [{"d": "2026-07-29T15:25+00:00", "value": 985.0},
            {"d": "2026-07-30T07:00+00:00", "value": 990.0},
            {"d": "2026-07-30T15:25+00:00", "value": 1090.0}]
    _stub_bars(monkeypatch, bars, 985.0)

    out = ds.get_intraday(
        conn, [{"isin": "X1"}], {"X1": _price(price=110.0, prev=100.0)}, [_pos(shares=10.0)]
    )
    # The delayed final bar (1090) gives way to the live value (1100), and both
    # the baseline and the point drawn at it to the chip's previous close (1000)
    # — so the line's endpoints and the chip describe the same two prices.
    assert out["prev_close"] == 1000.0
    assert out["points"][0]["value"] == 1000.0
    assert out["points"][-1]["value"] == 1100.0
    # The shape in between is untouched: those are the real bars, at their own
    # timestamps.
    assert out["points"][1] == {"d": "2026-07-30T07:00+00:00", "value": 990.0}


def test_selecting_the_whole_line_gives_the_chips_own_number(conn, monkeypatch):
    """The line's first point is the previous close, so first→last is the day.

    It used to start at the open, and the overnight gap fell outside the line:
    dragging across the whole chart answered +€116,61 under a figure saying
    +€79,19. Both were right about different things, which is the worst kind of
    disagreement to put on one card.
    """
    bars = [{"d": "2026-07-29T15:25+00:00", "value": 985.0},   # prepended baseline
            {"d": "2026-07-30T07:00+00:00", "value": 970.0},   # opened below it
            {"d": "2026-07-30T15:25+00:00", "value": 1090.0}]
    _stub_bars(monkeypatch, bars, 985.0)
    positions, prices = [_pos(shares=10.0)], {"X1": _price(price=110.0, prev=100.0)}

    out = ds.get_intraday(conn, [{"isin": "X1"}], prices, positions)
    first, last = out["points"][0]["value"], out["points"][-1]["value"]

    assert round(last - first, 2) == ds.portfolio_day_change(positions, prices)["delta_eur"]


def test_without_anchors_the_bars_are_left_alone_and_marked_unanchored(conn, monkeypatch):
    """The bars stay — the visit strip reads their timestamps — but the card is
    told not to draw them: an unpinned day is a second answer to a question
    that has one, and it falls back to the daily series instead."""
    bars = [{"d": "2026-07-30T07:00+00:00", "value": 990.0},
            {"d": "2026-07-30T15:25+00:00", "value": 1090.0}]
    _stub_bars(monkeypatch, bars, 985.0)

    out = ds.get_intraday(
        conn, [{"isin": "X1"}], {"X1": _price(currency="USD")}, [_pos()]
    )
    assert out["anchored"] is False
    assert out["prev_close"] == 985.0
    assert out["points"][-1]["value"] == 1090.0


def test_anchored_bars_say_so(conn, monkeypatch):
    bars = [{"d": "2026-07-29T15:25+00:00", "value": 985.0},
            {"d": "2026-07-30T07:00+00:00", "value": 990.0},
            {"d": "2026-07-30T15:25+00:00", "value": 1090.0}]
    _stub_bars(monkeypatch, bars, 985.0)

    out = ds.get_intraday(conn, [{"isin": "X1"}], {"X1": _price()}, [_pos()])
    assert out["anchored"] is True


def test_bars_without_a_previous_close_are_not_anchored(conn, monkeypatch):
    """Only the far end could be pinned, so the day would be measured from the
    open — the +€116,61-against-+€79,19 reading this whole anchoring exists to
    remove. Half-pinned is not pinned."""
    bars = [{"d": "2026-07-30T07:00+00:00", "value": 990.0},
            {"d": "2026-07-30T15:25+00:00", "value": 1090.0}]
    _stub_bars(monkeypatch, bars, None)

    out = ds.get_intraday(conn, [{"isin": "X1"}], {"X1": _price()}, [_pos()])
    assert out["anchored"] is False
    assert out["points"][-1]["value"] == 1090.0


def test_anchors_are_applied_outside_the_cache(conn, monkeypatch):
    """A cached payload must not pin a stale live price for the whole TTL."""
    bars = [{"d": "2026-07-30T07:00+00:00", "value": 990.0},
            {"d": "2026-07-30T15:25+00:00", "value": 1090.0}]
    _stub_bars(monkeypatch, bars, 985.0)
    tx = [{"isin": "X1"}]

    first = ds.get_intraday(conn, tx, {"X1": _price(price=110.0, prev=100.0)}, [_pos()])
    assert first["points"][-1]["value"] == 1100.0

    # Same cache entry (the key does not depend on the price), moved market.
    second = ds.get_intraday(conn, tx, {"X1": _price(price=120.0, prev=100.0)}, [_pos()])
    assert second["points"][-1]["value"] == 1200.0


def test_empty_bars_are_not_anchored(conn, monkeypatch):
    _stub_bars(monkeypatch, [], None)
    out = ds.get_intraday(conn, [{"isin": "X1"}], {"X1": _price()}, [_pos()])
    assert out == {"points": [], "prev_close": None, "anchored": False}


def test_a_portfolio_without_transactions_is_not_anchored(conn):
    assert ds.get_intraday(conn, [], {}, []) == {
        "points": [], "prev_close": None, "anchored": False,
    }
