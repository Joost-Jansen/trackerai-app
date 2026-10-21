"""
dashboard_service.pin_to_total — the value card ends on the hero's total.

On 2026-09-24 the hero said EUR 15.429,33 (+34,8%) and the card's "All"
EUR 15.496,96 (+35,3%): same inleg, same dividends, two price sources. The card
now takes the hero's total for today's point, and its return with it.
"""

import datetime

import pytest

from app.services import dashboard_service as ds

TODAY = datetime.date.today().isoformat()
YESTERDAY = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


def _history(last_day=TODAY):
    return {
        "points": [
            {"d": YESTERDAY, "invested": 11701.36, "value": 15400.00, "value_divs": 15738.82},
            {"d": last_day, "invested": 11701.36, "value": 15496.96, "value_divs": 15835.78},
        ],
        "estimated": [],
    }


def _positions(*values):
    return [{"isin": f"X{i}", "current_value": v} for i, v in enumerate(values)]


def test_todays_point_becomes_the_hero_total_and_keeps_its_dividends():
    pinned = ds.pin_to_total(_history(), _positions(10000.00, 5429.33), 15429.33)

    last = pinned["points"][-1]
    assert last["value"] == pytest.approx(15429.33)
    assert last["value_divs"] - last["value"] == pytest.approx(338.82)
    # The card's return is then the hero's: 15.429,33 + 338,82 - 11.701,36.
    assert last["value_divs"] - last["invested"] == pytest.approx(4066.79)


def test_earlier_points_are_left_alone():
    pinned = ds.pin_to_total(_history(), _positions(15429.33), 15429.33)

    assert pinned["points"][0] == _history()["points"][0]
    assert pinned["estimated"] == []


def test_an_unpriced_position_leaves_the_series_as_it_is():
    """The hero leaves it out, the series carries it at cost: pinning would
    drop the line by that whole position on the last day."""
    history = _history()

    assert ds.pin_to_total(history, _positions(15429.33, None), 15429.33) == history


def test_a_last_point_from_another_day_is_not_pinned():
    history = _history(last_day=YESTERDAY)

    assert ds.pin_to_total(history, _positions(15429.33), 15429.33) == history


def test_an_empty_history_stays_empty():
    empty = {"points": [], "estimated": []}

    assert ds.pin_to_total(empty, _positions(1.0), 1.0) == empty
