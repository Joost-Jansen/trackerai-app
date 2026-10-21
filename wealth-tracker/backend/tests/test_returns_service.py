"""
The Returns tab's arithmetic: TWR, IRR, and the difference between them.

The whole reason the tab exists is that these two disagree, so the tests that
matter are the ones that pin *why*: same investments, different deposit timing,
identical TWR, different IRR. If that pair ever stops holding, the tab is
showing one number twice.

IRR is checked against cases whose answer is known by hand — €1.000 becoming
€1.100 in exactly a year is 10%, and nothing about the solver may change that.

Each test was watched fail first (rule 3): by flipping the cash-flow signs, by
dropping the day-count from the discounting, and by removing the short-window
guard.
"""

import datetime

import pytest

from app.services import returns_service as rs

D0 = datetime.date(2020, 1, 1)


def _d(days: int) -> datetime.date:
    return D0 + datetime.timedelta(days=days)


def _pct(rate: float | None) -> float | None:
    return None if rate is None else round(rate * 100, 2)


# ---------------------------------------------------------------------------
# IRR against answers known by hand
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "end_value,days,expected",
    [
        (1100.0, 365, 10.0),  # a tenth, in a year
        (1000.0, 365, 0.0),  # nothing, in a year
        (2000.0, 365, 100.0),  # doubled
        (500.0, 365, -50.0),  # halved
        (1210.0, 730, 10.0),  # 10% compounded twice
        (1100.0, 182, 21.0),  # a tenth in half a year annualises to ~21%
    ],
)
def test_irr_of_a_single_investment(end_value, days, expected):
    got = _pct(rs.irr([(D0, -1000.0), (_d(days), end_value)]))
    assert got == pytest.approx(expected, abs=0.3)


def test_irr_needs_both_directions():
    """Flows that all point the same way admit no rate at all."""
    assert rs.irr([(D0, -1000.0), (_d(365), -500.0)]) is None
    assert rs.irr([(D0, 1000.0), (_d(365), 500.0)]) is None


def test_irr_needs_two_dates():
    assert rs.irr([(D0, -1000.0), (D0, 1100.0)]) is None
    assert rs.irr([(D0, -1000.0)]) is None


def test_irr_counts_the_days_not_the_flows():
    """Same amounts, twice the time, roughly half the annual rate."""
    fast = _pct(rs.irr([(D0, -1000.0), (_d(365), 1200.0)]))
    slow = _pct(rs.irr([(D0, -1000.0), (_d(730), 1200.0)]))
    assert fast == pytest.approx(20.0, abs=0.3)
    assert slow == pytest.approx(9.54, abs=0.3)


# ---------------------------------------------------------------------------
# The claim the tab is built on: timing moves IRR and not TWR
# ---------------------------------------------------------------------------


def _series(values: list[float], invested: list[float]):
    """A daily series at one-day spacing, as charts.portfolio_history_series gives."""
    dates = [_d(i) for i in range(len(values))]
    return dates, invested, values


def test_the_same_investment_bought_at_different_times_gives_a_different_irr():
    """The tab's whole reason to exist, as two accounts over one year.

    Both hold the same fund through the same market: +10% in the first half,
    -10% in the second. One has its €2.000 in from the start; the other puts the
    second €1.000 in at the halfway point, right before the fall. Every
    sub-period return is identical, so their TWR is identical — and one of them
    is €90 worse off.
    """
    dates = [_d(0), _d(182), _d(365)]

    all_in_invested = [2000.0, 2000.0, 2000.0]
    all_in_values = [2000.0, 2200.0, 1980.0]

    added_late_invested = [1000.0, 2000.0, 2000.0]
    added_late_values = [1000.0, 2100.0, 1890.0]  # 1100 after the rise, +1000 in

    # Same fund, same weeks: the sub-period returns match to the cent.
    assert all_in_values[1] / all_in_values[0] == pytest.approx(1.10)
    assert (added_late_values[1] - 1000.0) / added_late_values[0] == pytest.approx(1.10)
    assert all_in_values[2] / all_in_values[1] == pytest.approx(0.90)
    assert added_late_values[2] / added_late_values[1] == pytest.approx(0.90)

    all_in = rs.irr(rs.cash_flows(dates, all_in_invested, all_in_values, 0, 2))
    added_late = rs.irr(rs.cash_flows(dates, added_late_invested, added_late_values, 0, 2))

    assert all_in is not None and added_late is not None
    assert _pct(all_in) == pytest.approx(-1.0, abs=0.3)
    assert _pct(added_late) == pytest.approx(-7.28, abs=0.3)
    # Which is the point: TWR calls these two the same, IRR does not.
    assert all_in > added_late


def test_cash_flows_signs_and_endpoints():
    dates, invested, values = _series([1000.0, 1000.0, 2100.0], [1000.0, 1000.0, 2000.0])
    flows = rs.cash_flows(dates, invested, values, 0, 2)
    assert flows[0] == (_d(0), -1000.0)  # what was already at work
    assert (_d(2), -1000.0) in flows  # the deposit, money leaving you
    assert flows[-1] == (_d(2), 2100.0)  # what liquidating would return


def test_cash_flows_reads_a_withdrawal_as_money_coming_back():
    dates, invested, values = _series([2000.0, 2000.0, 1050.0], [2000.0, 2000.0, 1000.0])
    flows = rs.cash_flows(dates, invested, values, 0, 2)
    assert (_d(2), 1000.0) in flows


def test_cash_flows_ignores_days_without_a_flow():
    dates, invested, values = _series([1000.0, 1010.0, 1020.0], [1000.0, 1000.0, 1000.0])
    # Opening value and closing value only: a price move is not a cash flow.
    assert len(rs.cash_flows(dates, invested, values, 0, 2)) == 2


# ---------------------------------------------------------------------------
# TWR over a window
# ---------------------------------------------------------------------------


def test_twr_over_is_the_ratio_of_two_index_levels():
    assert rs.twr_over([100.0, 110.0, 121.0], 0, 2) == pytest.approx(21.0)
    assert rs.twr_over([100.0, 110.0, 121.0], 1, 2) == pytest.approx(10.0)


def test_twr_over_refuses_a_zero_base():
    assert rs.twr_over([0.0, 110.0], 0, 1) is None


# ---------------------------------------------------------------------------
# What build() puts on the page
# ---------------------------------------------------------------------------


@pytest.fixture
def built(monkeypatch):
    """build() over a hand-made series, with the yfinance-backed pieces stubbed."""
    dates = [_d(i) for i in range(400)]
    invested = [1000.0] * 200 + [2000.0] * 200
    # Steady 20% over the whole stretch, with a deposit halfway.
    values = [1000.0 + i for i in range(200)] + [2200.0 + i for i in range(200)]
    divs = list(values)

    monkeypatch.setattr(rs.charts, "portfolio_history_series", lambda *a: (dates, invested, values, divs))
    monkeypatch.setattr(rs.charts, "build_portfolio_segments", lambda *a: [(dates, values, [0.0] * 400)])
    return rs.build([{"x": 1}], {}, [])


def test_build_returns_a_point_per_day(built):
    assert len(built["points"]) == 400
    assert built["points"][0]["d"] == _d(0).isoformat()


def test_build_skips_irr_on_a_window_too_short_to_annualise(built):
    """A month's return raised to the twelfth power is arithmetic, not insight."""
    short = next(r for r in built["ranges"] if r["label"] == "1M")
    assert short["days"] < rs.MIN_IRR_DAYS
    assert short["irr_pct"] is None
    # The other two are period returns, so they stay.
    assert short["twr_pct"] is not None


def test_build_reports_irr_once_the_window_is_long_enough(built):
    long = next(r for r in built["ranges"] if r["label"] == "All")
    assert long["days"] >= rs.MIN_IRR_DAYS
    assert long["irr_pct"] is not None


def test_build_always_offers_all(built):
    assert built["ranges"][-1]["label"] == "All"
    assert built["ranges"][-1]["from"] == _d(0).isoformat()


def test_build_adds_a_custom_window_dragged_out_on_the_chart(built):
    # The stubs from the fixture are still in place.
    out = rs.build([{"x": 1}], {}, [], (_d(50).isoformat(), _d(150).isoformat()))
    custom = next(r for r in out["ranges"] if r["label"] == "Custom")
    assert custom["from"] == _d(50).isoformat() and custom["days"] == 100
    # No deposit in the window: the whole rise from 1050 to 1150 is return.
    assert custom["contrib_eur"] == 0 and custom["gain_eur"] == 100
    # A window that holds fewer than two days adds nothing.
    none = rs.build([{"x": 1}], {}, [], (_d(500).isoformat(), _d(600).isoformat()))
    assert all(r["label"] != "Custom" for r in none["ranges"])


def test_custom_range_from_the_cached_series_matches_build(built):
    """The router works out a window from the cached `_series`; it must give the
    same figures as build() over that window."""
    window = (_d(50).isoformat(), _d(150).isoformat())
    direct = next(r for r in rs.build([{"x": 1}], {}, [], window)["ranges"] if r["label"] == "Custom")
    import json

    cached = json.loads(json.dumps(built["_series"]))  # as it comes back from the cache
    assert rs.custom_range(cached, window) == direct


def test_build_drops_ranges_older_than_the_portfolio(built):
    # 400 days of history: 3J and 5J would both just be "All" again.
    assert {r["label"] for r in built["ranges"]}.isdisjoint({"3Y", "5Y"})


def test_build_marks_the_stretches_the_portfolio_was_empty(monkeypatch):
    a_dates = [_d(i) for i in range(10)]
    b_dates = [_d(i) for i in range(100, 110)]
    dates = a_dates + b_dates
    values = [100.0] * 10 + [200.0] * 10
    monkeypatch.setattr(rs.charts, "portfolio_history_series", lambda *a: (dates, [100.0] * 20, values, values))
    monkeypatch.setattr(
        rs.charts,
        "build_portfolio_segments",
        lambda *a: [(a_dates, [100.0] * 10, [0.0] * 10), (b_dates, [200.0] * 10, [0.0] * 10)],
    )
    out = rs.build([{"x": 1}], {}, [])
    # TWR chains across the gap as if nothing happened, which is right for an
    # index and a caveat on this page — so the page is told where the gaps are.
    assert out["gaps"] == [{"from": _d(9).isoformat(), "to": _d(100).isoformat()}]


def test_build_survives_an_empty_portfolio(monkeypatch):
    monkeypatch.setattr(rs.charts, "portfolio_history_series", lambda *a: ([], [], [], []))
    assert rs.build([], {}, []) == {"points": [], "gaps": [], "ranges": []}


def test_the_simple_return_divides_by_a_base_that_includes_earlier_dividends(monkeypatch):
    """gain is measured on the with-dividends series, so the base has to be too.
    Dividends banked before the window opened are capital that was already at
    work; leaving them out of the denominator alone inflated the percentage."""
    import pandas as pd

    from domain.portfolio import series as charts

    dates = [datetime.date(2025, 1, 1) + datetime.timedelta(days=i) for i in range(400)]
    invested = [10000.0] * 400
    values = [10000.0 + i * 5 for i in range(400)]
    values_divs = [v + 500.0 for v in values]  # EUR 500 received before day 0

    monkeypatch.setattr(charts, "portfolio_history_series", lambda *a, **k: (dates, invested, values, values_divs))
    monkeypatch.setattr(charts, "build_portfolio_segments", lambda *a, **k: [(dates, values_divs, [0.0] * 400)])
    monkeypatch.setattr(charts, "_compute_twr_index", lambda *a, **k: pd.Series([100.0] * 400, index=pd.to_datetime(dates)))

    out = rs.build([{"date": "2025-01-01"}], {}, [])
    # Measured on 1J and not on "All": a window reaching inception has no
    # earlier point, so it has no base to put the dividends into (see the test
    # below). 1J opens on 2025-02-04, day 34 of the series.
    year = next(r for r in out["ranges"] if r["label"] == "1Y")
    assert year["gain_eur"] == 1825.0
    assert year["simple_pct"] == 17.1  # 1825 / 10670, not 1825 / 10170


def test_all_counts_the_first_purchase_as_invested_not_as_return(monkeypatch):
    """A window reaching inception measures from zero, like the dashboard.

    There is no point before the first trade, so what was paid for it is inleg
    and cannot also be return — otherwise the first day's own market move lands
    inside the percentage and the denominator becomes that day's *value* rather
    than the money put in. That is the rule frontend/lib/dashboard.ts's
    rangeBreakdown states with `base = null`, and it is what keeps both totals
    equal to the hero's "since start".
    """
    import pandas as pd

    from domain.portfolio import series as charts

    dates = [datetime.date(2025, 1, 1) + datetime.timedelta(days=i) for i in range(400)]
    invested = [1000.0] * 400
    values = [980.0 + i for i in range(400)]  # day one closed 20 below cost
    monkeypatch.setattr(charts, "portfolio_history_series", lambda *a, **k: (dates, invested, values, values))
    monkeypatch.setattr(charts, "build_portfolio_segments", lambda *a, **k: [(dates, values, [0.0] * 400)])
    monkeypatch.setattr(charts, "_compute_twr_index", lambda *a, **k: pd.Series([100.0] * 400, index=pd.to_datetime(dates)))

    everything = next(r for r in rs.build([{"date": "2025-01-01"}], {}, [])["ranges"] if r["label"] == "All")
    # 1379 on the books against 1000 put in. Measuring from day one's 980
    # instead would call it 399 (+40,7%) and quietly count the opening dip as
    # something the portfolio earned back.
    assert everything["contrib_eur"] == 1000.0
    assert everything["gain_eur"] == 379.0
    assert everything["simple_pct"] == 37.9


# ---------------------------------------------------------------------------
# The range cutoffs — the same windows the dashboard's buttons mean
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "day, months, expected",
    [
        # Ordinary months.
        ((2026, 8, 5), 1, (2026, 7, 5)),
        ((2026, 8, 5), 3, (2026, 5, 5)),
        ((2026, 8, 5), 12, (2025, 8, 5)),
        # Across a year boundary.
        ((2026, 2, 4), 3, (2025, 11, 4)),
        # Clamped rather than overflowed: "31 February" is 28 February, not 3 March.
        ((2026, 3, 31), 1, (2026, 2, 28)),
        ((2024, 3, 31), 1, (2024, 2, 29)),  # leap year
        ((2026, 5, 31), 3, (2026, 2, 28)),
        # 29 February minus twelve months is 28 February, not 1 March.
        ((2024, 2, 29), 12, (2023, 2, 28)),
        # The long ranges this tab has and the dashboard does not.
        ((2026, 8, 5), 36, (2023, 8, 5)),
        ((2026, 8, 5), 60, (2021, 8, 5)),
    ],
)
def test_months_before_matches_the_frontends_calendar_arithmetic(day, months, expected):
    assert rs._months_before(datetime.date(*day), months) == datetime.date(*expected)


def test_range_starts_are_calendar_months_not_day_counts():
    """91 days is not three months, and that gap was visible.

    The dashboard slices "3M" at three calendar months; counting 91 days here
    put the two tabs a day apart on most dates, which on a real portfolio read
    as +8,5% against +6,9% under the same button.
    """
    dates = [datetime.date(2026, 8, 5) - datetime.timedelta(days=i) for i in range(800)][::-1]
    starts = dict(rs._range_starts(dates))
    assert dates[starts["1M"]] == datetime.date(2026, 7, 5)
    assert dates[starts["3M"]] == datetime.date(2026, 5, 5)
    assert dates[starts["1Y"]] == datetime.date(2025, 8, 5)
    assert starts["All"] == 0
