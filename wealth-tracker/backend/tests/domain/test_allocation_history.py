"""
The allocation-over-time arithmetic (domain/portfolio/allocation_history.py).

Pure functions over plain data: which dates, what was held on them, how a
date's values spread over sectors, and how the series is cut down to a fixed
handful of slices with exactly one "Other".
"""

import datetime

from domain.portfolio import allocation_history as ah

D = datetime.date


def test_month_ends_then_today():
    assert ah.month_end_dates(D(2025, 11, 14), D(2026, 2, 10)) == [D(2025, 11, 30), D(2025, 12, 31), D(2026, 1, 31), D(2026, 2, 10)]


def test_a_month_end_on_today_is_today_once():
    assert ah.month_end_dates(D(2026, 1, 3), D(2026, 1, 31)) == [D(2026, 1, 31)]


def _tx(date, isin, kind, qty, total):
    return {"date": date, "isin": isin, "transaction_type": kind, "quantity": qty, "total_eur": total}


def test_holdings_follow_buys_and_sells_per_date():
    txs = [
        _tx("2025-01-10", "A", "BUY", 10, -1000),
        _tx("2025-02-05", "A", "BUY", 10, -1200),
        _tx("2025-02-20", "B", "BUY", 5, -500),
        _tx("2025-03-15", "A", "SELL", 20, 2600),
    ]
    held = ah.holdings_on(txs, [D(2025, 1, 31), D(2025, 2, 28), D(2025, 3, 31)])
    assert held[0] == {"A": (10, 100.0)}
    assert held[1]["A"] == (20, 110.0)  # weighted average cost
    assert held[1]["B"] == (5, 100.0)
    assert "A" not in held[2]  # fully sold: gone, not a zero row
    assert held[2] == {"B": (5, 100.0)}


def test_values_spread_over_each_positions_own_mix():
    totals = ah.mix_totals(
        {"FUND": 1000.0, "SHARE": 500.0},
        {"FUND": {"Tech": 0.6, "Financials": 0.4}, "SHARE": {"Tech": 1.0}},
    )
    assert totals == {"Tech": 1100.0, "Financials": 400.0}


def test_a_mix_that_does_not_add_up_to_one_is_renormalised():
    totals = ah.mix_totals({"F": 1000.0}, {"F": {"Tech": 0.5, "Energy": 0.49}})
    assert abs(sum(totals.values()) - 1000.0) < 1e-9


def test_a_position_without_a_mix_does_not_count():
    assert ah.mix_totals({"BOND": 1000.0}, {}) == {}


def test_the_issuers_other_and_the_tail_are_one_slice():
    """The double "Other": an unclassified bucket from the issuer files *and*
    the folded tail used to be two rows of the same name."""
    today = {"A": 40.0, "B": 20.0, "C": 10.0, "D": 8.0, "E": 6.0, "F": 5.0, "G": 3.0, ah.OTHER: 8.0}
    keys, rows = ah.fold([today])
    assert keys == ["A", "B", "C", "D", "E", ah.OTHER]
    assert keys.count(ah.OTHER) == 1
    assert rows[0][-1] == 8.0 + 5.0 + 3.0
    assert sum(rows[0]) == sum(today.values())


def test_slices_are_fixed_and_ranked_by_the_last_date():
    early = {"Europe": 90.0, "North America": 10.0}
    now = {"Europe": 30.0, "North America": 60.0, "Asia": 10.0}
    keys, rows = ah.fold([early, now])
    assert keys == ["North America", "Europe", "Asia"]
    assert rows[0] == [10.0, 90.0, 0.0]  # Asia not yet held: zero, same column


def test_six_named_slices_without_an_other_are_all_kept():
    keys, _ = ah.fold([{n: float(10 - i) for i, n in enumerate("ABCDEF")}])
    assert keys == list("ABCDEF")


def test_payload_has_percentages_of_each_date_and_euros():
    payload = ah.as_payload(["A", ah.OTHER], [[300.0, 100.0], [0.0, 0.0]])
    assert payload["pct"][0] == [75.0, 25.0]
    assert payload["value"][0] == [300.0, 100.0]
    assert payload["pct"][1] == [0.0, 0.0]
