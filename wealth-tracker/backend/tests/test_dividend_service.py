"""
The Dividend tab's arithmetic. Everything here runs without a network: the
service takes payments, positions and an already-merged outlook, and does sums.

`today` is injected into every test. A tab whose numbers depend on the wall
clock cannot be tested twice with the same expectations, and the two windows
that matter here — "laatste 12 maanden" and "dit jaar tot nu" — are both
defined relative to it.
"""

import datetime

from app.services import dividend_service as dv


TODAY = datetime.date(2026, 8, 4)


def _pay(date, isin="X1", name="Fund X", net=10.0, gross=None, tax=None):
    gross = net if gross is None else gross
    tax = 0.0 if tax is None else tax
    return {
        "date": date, "isin": isin, "name": name,
        "gross_eur": gross, "tax_eur": tax, "net_eur": net,
        "currency_original": "EUR", "amount_original": gross,
    }


def _pos(isin="X1", name="Fund X", invested=1000.0, value=1200.0, shares=10.0):
    return {
        "isin": isin, "name": name, "ticker": f"{isin}.AS", "shares_held": shares,
        "total_invested": invested, "current_value": value,
    }


def _outlook(upcoming=None, rest=0.0):
    return {"upcoming": upcoming or [], "rest_of_year_eur": rest}


def _summary(positions, payments, realized=0.0):
    """calculate_portfolio_summary's shape, as the router hands it over.

    The tab reads exactly three keys off it, for the one figure on the page
    that is the dashboard's rather than the payment history's: what the whole
    portfolio has made. *realized* is what earlier sells locked in — absent
    from the open positions, and the term this tab used to lose.
    """
    priced = [p for p in positions if p.get("current_value") is not None]
    unrealized = sum(p["current_value"] for p in priced) - sum(
        p["total_invested"] for p in priced
    )
    return {
        "total_gain": unrealized + realized,
        "total_dividends": sum(p["net_eur"] for p in payments),
        "prices_available": len(priced) == len(positions),
    }


def _build(payments, positions=None, transactions=None, outlook=None, summary=None):
    positions = positions if positions is not None else [_pos()]
    return dv.build(
        positions,
        transactions or [],
        payments,
        outlook or _outlook(),
        today=TODAY,
        summary=summary if summary is not None else _summary(positions, payments),
    )


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def test_a_payment_without_a_gross_or_tax_column_still_counts():
    """An older import can carry net only. Dropping the row would make the
    totals disagree with the Details tab, which sums net_eur and nothing else."""
    row = {"date": "2026-03-02", "isin": "X1", "name": "Fund X", "net_eur": 12.5}
    out = _build([row])
    assert out["totals"]["net"] == 12.5
    assert out["totals"]["gross"] == 0.0


def test_a_row_without_a_usable_date_is_skipped_rather_than_crashing():
    out = _build([_pay("2026-03-02", net=10.0), {"date": None, "isin": "X1", "net_eur": 5.0}])
    assert out["totals"]["net"] == 10.0
    assert out["totals"]["payments"] == 1


def test_negative_payments_reduce_the_totals():
    """A reversal comes through the parser as a negative row and must subtract;
    treating it as an absolute value would inflate every figure on the tab."""
    out = _build([_pay("2026-03-02", net=20.0), _pay("2026-03-09", net=-8.0)])
    assert out["totals"]["net"] == 12.0


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

def test_the_twelve_month_window_excludes_its_own_left_edge():
    """Exactly 365 days back is *outside* the window, so a payment cannot be
    counted in both the trailing year and the one before it."""
    edge = (TODAY - datetime.timedelta(days=365)).isoformat()
    just_inside = (TODAY - datetime.timedelta(days=364)).isoformat()
    out = _build([_pay(edge, net=100.0), _pay(just_inside, net=7.0)])
    assert out["totals"]["ttm_net"] == 7.0
    assert out["totals"]["prev_ttm_net"] == 100.0


def test_this_year_is_compared_with_the_same_stretch_of_last_year():
    """Not with last year's finished total: on 4 August that would report a
    collapse every single year."""
    out = _build([
        _pay("2025-03-01", net=30.0),
        _pay("2025-11-01", net=70.0),   # after 4 August: not in the YTD compare
        _pay("2026-03-01", net=40.0),
    ])
    t = out["totals"]
    assert t["this_year_net"] == 40.0
    assert t["last_year_ytd_net"] == 30.0
    assert t["last_year_net"] == 100.0


def test_growth_is_a_dash_when_there_is_no_base_to_grow_from():
    out = _build([_pay("2026-03-01", net=40.0)])
    assert out["totals"]["prev_ttm_net"] == 0.0
    assert out["totals"]["ttm_growth_pct"] is None


# ---------------------------------------------------------------------------
# Yields
# ---------------------------------------------------------------------------

def test_yield_on_cost_uses_the_trailing_year_over_what_the_position_cost():
    out = _build([_pay("2026-03-01", net=25.0)], positions=[_pos(invested=1000.0, value=1200.0)])
    assert out["totals"]["yield_on_cost_pct"] == 2.5
    assert out["totals"]["yield_on_value_pct"] == round(25.0 / 1200.0 * 100, 2)


def test_a_yield_on_nothing_is_none_not_zero():
    """An account with prices unavailable has current_value None everywhere.
    0,0% there would read as "these holdings pay nothing"."""
    position = {**_pos(), "current_value": None, "total_invested": 0.0}
    out = _build([_pay("2026-03-01", net=25.0)], positions=[position])
    assert out["totals"]["yield_on_cost_pct"] is None
    assert out["totals"]["yield_on_value_pct"] is None


def test_share_of_profit_is_omitted_when_the_portfolio_is_down():
    """"84% of your profit is dividend" is meaningless when the profit is
    negative — the ratio flips sign and reads as a win."""
    out = _build(
        [_pay("2026-03-01", net=25.0)],
        positions=[_pos(invested=1000.0, value=500.0)],
    )
    assert out["totals"]["share_of_profit_pct"] is None


def test_share_of_profit_measures_against_the_dashboards_total():
    """Including what earlier sells locked in.

    Rebuilt from the open positions alone the denominator is short by exactly
    the dashboard's "Realised" row: EUR 500 here, which turned 3,45% into
    11,11% — a share of a profit the dashboard never claimed.
    """
    payments = [_pay("2026-03-01", net=25.0)]
    positions = [_pos(invested=1000.0, value=1200.0)]
    out = _build(payments, positions=positions,
                 summary=_summary(positions, payments, realized=500.0))
    # 25 / (200 unrealized + 500 realized + 25 dividend)
    assert out["totals"]["share_of_profit_pct"] == 3.45


def test_share_of_profit_needs_a_summary_to_measure_against():
    """No summary, no line. The tab may not fall back to a profit of its own
    making — reconstructing it here is exactly how it drifted from the
    dashboard, so the absence has to be visible rather than papered over."""
    bare = dv.build([_pos()], [], [_pay("2026-03-01", net=25.0)], _outlook(), today=TODAY)
    assert bare["totals"]["share_of_profit_pct"] is None


# ---------------------------------------------------------------------------
# Per year
# ---------------------------------------------------------------------------

def test_only_the_running_year_carries_an_expected_remainder():
    out = _build(
        [_pay("2025-03-01", net=50.0), _pay("2026-03-01", net=60.0)],
        outlook=_outlook(rest=25.0),
    )
    rows = {r["year"]: r for r in out["by_year"]}
    assert rows["2025"]["expected"] == 0.0
    assert rows["2025"]["partial"] is False
    assert rows["2026"]["expected"] == 25.0
    assert rows["2026"]["partial"] is True


def test_a_year_that_has_only_a_forecast_still_gets_a_row():
    """First dividend expected in December, nothing received yet: the year must
    appear, or the chart's only bar is missing."""
    out = _build([_pay("2025-03-01", net=50.0)], outlook=_outlook(rest=30.0))
    assert [r["year"] for r in out["by_year"]] == ["2025", "2026"]
    assert out["by_year"][-1] == {
        "year": "2026", "gross": 0.0, "tax": 0.0, "net": 0.0,
        "payments": 0, "expected": 30.0, "partial": True,
    }


def test_withholding_tax_is_kept_per_year_with_its_gross():
    out = _build([_pay("2026-03-01", net=8.5, gross=10.0, tax=-1.5)])
    row = out["by_year"][0]
    assert (row["gross"], row["tax"], row["net"]) == (10.0, -1.5, 8.5)
    assert out["totals"]["tax_pct"] == 15.0


# ---------------------------------------------------------------------------
# Per month
# ---------------------------------------------------------------------------

def test_months_without_a_payment_are_zero_rows_not_gaps():
    """A quarterly payer drawn only on its paydays looks like it pays every
    month — the empty months are the point of the chart."""
    out = _build([_pay("2026-03-02", net=10.0), _pay("2026-06-02", net=10.0)])
    months = [r["month"] for r in out["by_month"]]
    assert months.index("2026-06") - months.index("2026-03") == 3
    assert all(m in months for m in ("2026-04", "2026-05"))
    assert [r["net"] for r in out["by_month"] if r["month"] == "2026-04"] == [0.0]


def test_the_series_runs_up_to_the_current_month_even_after_a_dry_spell():
    out = _build([_pay("2026-02-02", net=10.0)])
    assert out["by_month"][-1]["month"] == "2026-08"
    assert out["by_month"][-1]["net"] == 0.0


def test_months_ahead_are_flagged_as_future():
    forecast = [{
        "isin": "X1", "name": "Fund X", "date": "2026-09-15", "month": "2026-09",
        "part": "mid", "expected_eur": 12.0, "cadence": "quarterly",
        "confidence": "high", "source": "estimate",
    }]
    rows = dv.by_month([{"date": "2026-06-02", "net_eur": 10.0, "isin": "X1"}], forecast, TODAY)
    september = next(r for r in rows if r["month"] == "2026-09")
    assert september["expected"] == 12.0
    assert september["future"] is True
    assert next(r for r in rows if r["month"] == "2026-08")["future"] is False


# ---------------------------------------------------------------------------
# Seasonality
# ---------------------------------------------------------------------------

def test_seasonality_has_all_twelve_months_including_the_empty_ones():
    out = _build([_pay("2025-03-02", net=10.0), _pay("2026-03-02", net=14.0)])
    season = out["seasonality"]
    assert len(season) == 12
    march = season[2]
    assert (march["label"], march["total"], march["years"]) == ("Mar", 24.0, 2)
    assert season[0]["total"] == 0.0
    assert season[0]["share_pct"] is None


# ---------------------------------------------------------------------------
# Cumulative
# ---------------------------------------------------------------------------

def test_the_cumulative_line_sums_same_day_payments_into_one_point():
    """Two rows on one date are one payday. Two points on the same x would draw
    a vertical segment the chart cannot interpolate across."""
    points = dv.cumulative(
        dv._clean([_pay("2026-03-02", net=10.0), _pay("2026-03-02", isin="X2", net=5.0)]),
        TODAY,
    )
    assert points[0] == {"d": "2026-03-02", "v": 15.0}


def test_the_cumulative_line_is_carried_forward_to_today():
    points = dv.cumulative(dv._clean([_pay("2026-03-02", net=10.0)]), TODAY)
    assert points[-1] == {"d": "2026-08-04", "v": 10.0}


# ---------------------------------------------------------------------------
# Per stock
# ---------------------------------------------------------------------------

def test_a_sold_holding_keeps_its_payments_but_gets_no_yield():
    """€300 from a position you no longer own is still €300 you received;
    dropping it would make the rows disagree with the total above them. There
    is no cost basis left to divide by, though."""
    out = _build(
        [_pay("2026-03-01", isin="GONE", name="Sold Fund", net=30.0),
         _pay("2026-03-01", isin="X1", net=10.0)],
        positions=[_pos()],
    )
    rows = {r["isin"]: r for r in out["by_stock"]}
    assert rows["GONE"]["held"] is False
    assert rows["GONE"]["net"] == 30.0
    assert rows["GONE"]["yield_on_cost_pct"] is None
    assert rows["X1"]["yield_on_cost_pct"] == 1.0
    assert sum(r["net"] for r in out["by_stock"]) == out["totals"]["net"]


def test_a_recognisable_rhythm_is_labelled_and_an_irregular_one_is_not():
    quarterly = [_pay(d, isin="Q1") for d in
                 ("2025-03-01", "2025-06-01", "2025-09-01", "2025-12-01", "2026-03-01")]
    once = [_pay("2026-01-15", isin="ONE", net=5.0)]
    out = _build(quarterly + once, positions=[_pos(isin="Q1"), _pos(isin="ONE")])
    rows = {r["isin"]: r for r in out["by_stock"]}
    assert rows["Q1"]["cadence"] == "quarterly"
    assert rows["ONE"]["cadence"] is None


def test_an_interim_final_payer_borrows_its_rhythm_from_the_forecast():
    """NN Group pays ~august and ~june, so its gaps alternate ~76/~275 days and
    the median matches no single cadence — detect_cadence returns None. The
    forecast's own alternating detector does recognise it, and a row reading
    "no rhythm" under an agenda that says "semi-annual" is a contradiction.
    """
    upcoming = [{
        "isin": "NN", "name": "NN Group", "date": "2026-08-20", "month": "2026-08",
        "part": "mid", "expected_eur": 21.48, "cadence": "semiannual",
        "confidence": "medium", "source": "estimate",
    }]
    # NN Group's real dates out of the portfolio this was built against: gaps of
    # 269 / 68 / 273 / 85 / 286 days, median 273 — nowhere near a cadence.
    payments = [_pay(d, isin="NN") for d in
                ("2023-09-26", "2024-06-21", "2024-08-28", "2025-05-28",
                 "2025-08-21", "2026-06-03")]
    out = _build(payments, positions=[_pos(isin="NN")], outlook=_outlook(upcoming))
    row = out["by_stock"][0]
    assert dashboard_cadence_is_none(payments)
    assert row["cadence"] == "semiannual"


def dashboard_cadence_is_none(payments) -> bool:
    """Guards the premise of the test above: if detect_cadence ever learns this
    pattern, the fallback is dead code and the test is testing nothing."""
    from app.services import dashboard_service
    dates = sorted({datetime.date.fromisoformat(p["date"]) for p in payments})
    return dashboard_service.detect_cadence(dates) is None


def test_the_next_expected_payment_comes_from_the_shared_outlook():
    """Reused, not recomputed: the tab and the dashboard card must never name a
    different next payment for the same holding."""
    upcoming = [{
        "isin": "X1", "name": "Fund X", "date": "2026-09-15", "month": "2026-09",
        "part": "mid", "expected_eur": 12.0, "cadence": "quarterly",
        "confidence": "high", "source": "official",
    }]
    out = _build([_pay("2026-03-01", net=10.0)], outlook=_outlook(upcoming))
    assert out["by_stock"][0]["next"] == {
        "date": "2026-09-15", "month": "2026-09", "part": "mid",
        "expected_eur": 12.0, "source": "official", "cadence": "quarterly",
    }


# ---------------------------------------------------------------------------
# Forward run rate
# ---------------------------------------------------------------------------

def test_the_forward_run_rate_counts_a_full_year_of_scheduled_payments():
    """Four quarters ahead, not the dashboard's six-month horizon — otherwise
    "average per month" would change with the month you opened the tab in.
    """
    payments = [_pay(d, isin="X1", net=10.0) for d in
                ("2025-05-04", "2025-08-03", "2025-11-02", "2026-02-01", "2026-05-03")]
    out = _build(payments, positions=[_pos(isin="X1", invested=1000.0)])
    assert out["totals"]["forward_12m_net"] == 40.0
    assert out["totals"]["forward_monthly_avg"] == round(40.0 / 12, 2)
    assert out["totals"]["forward_yield_on_cost_pct"] == 4.0


def test_an_accumulating_portfolio_forecasts_nothing_rather_than_guessing():
    out = _build([], positions=[_pos()])
    assert out["totals"]["forward_12m_net"] == 0.0
    assert out["by_stock"] == []
    assert out["cumulative"] == []


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------

def test_an_empty_portfolio_still_gets_a_well_formed_payload():
    """The tab must render its own empty state, not an error page."""
    out = dv.build([], [], [], _outlook(), today=TODAY)
    assert out["totals"]["net"] == 0.0
    assert out["totals"]["first_payment"] is None
    assert out["by_year"] == []
    assert len(out["seasonality"]) == 12
    assert out["payments"] == []


def test_the_payment_log_is_newest_first():
    out = _build([_pay("2025-03-01"), _pay("2026-03-01"), _pay("2024-03-01")])
    assert [p["date"] for p in out["payments"]] == ["2026-03-01", "2025-03-01", "2024-03-01"]


# ---------------------------------------------------------------------------
# Yields measure one number of shares above the line and below it
# ---------------------------------------------------------------------------

def _tx(date, isin="X1", kind="BUY", qty=10.0, total=1000.0):
    return {
        "isin": isin, "name": "Fund X", "date": date, "time": "09:00",
        "exchange": "EAM", "transaction_type": kind, "quantity": qty,
        "total_eur": total, "value_eur": total,
        "transaction_fee": 0.0, "autofx_cost": 0.0,
    }


def test_a_yield_is_not_inflated_by_selling_most_of_the_position():
    """The bug this guards: 1.000 shares earned EUR 800 over the year, 900 were
    sold last month, and the remaining EUR 1.000 of cost basis was handed the
    whole EUR 800 — printing 80% where the position yielded 8%."""
    payments = [_pay(d, net=200.0) for d in
                ("2025-09-04", "2025-12-04", "2026-03-04", "2026-06-04")]
    transactions = [
        _tx("2020-01-01", qty=1000.0, total=10000.0),
        _tx("2026-07-05", kind="SELL", qty=900.0, total=13500.0),
    ]
    out = _build(payments, positions=[_pos(invested=1000.0, shares=100.0)],
                 transactions=transactions)
    row = out["by_stock"][0]
    assert row["ttm_net"] == 800.0            # what actually arrived, unchanged
    assert row["yield_on_cost_pct"] == 8.0    # restated onto the 100 shares left
    assert out["totals"]["yield_on_cost_pct"] == 8.0


def test_a_position_that_was_never_resized_yields_exactly_what_it_did_before():
    payments = [_pay("2026-03-04", net=25.0)]
    transactions = [_tx("2020-01-01", qty=10.0, total=1000.0)]
    out = _build(payments, positions=[_pos(invested=1000.0, shares=10.0)],
                 transactions=transactions)
    assert out["by_stock"][0]["yield_on_cost_pct"] == 2.5


def test_a_missing_price_takes_the_value_based_figures_out_rather_than_halving_them():
    """A position with no price contributed nothing to the portfolio value and
    its whole cost to the inleg, so the yield on value came out roughly double
    and the portfolio read as being at a loss."""
    positions = [_pos(isin="X1", invested=10000.0, value=12000.0),
                 _pos(isin="X2", invested=10000.0, value=None)]
    payments = [_pay(f"2026-0{m}-04", net=85.0) for m in range(1, 8)]
    out = _build(payments, positions=positions)
    t = out["totals"]
    assert t["yield_on_cost_pct"] is not None   # cost basis is known for both
    assert t["yield_on_value_pct"] is None      # value is not
    assert t["share_of_profit_pct"] is None


def test_the_value_based_figures_come_back_once_every_price_is_in():
    positions = [_pos(isin="X1", invested=10000.0, value=12000.0),
                 _pos(isin="X2", invested=10000.0, value=11000.0)]
    out = _build([_pay("2026-03-04", net=230.0)], positions=positions)
    assert out["totals"]["yield_on_value_pct"] == 1.0    # 230 / 23000
