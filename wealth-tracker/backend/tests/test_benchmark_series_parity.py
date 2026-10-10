"""
benchmark_service's three series functions must keep producing exactly what the
Plotly figures in charts.py drew.

This is the one step of CHART_MIGRATION_PLAN.md where arithmetic moved rather
than just rendering: the TWR index, the trailing-window return and the YTD
rebasing used to sit inside charts.benchmark_*_chart, between computing the
numbers and calling go.Scatter. A mistake made while lifting them out — a day
shifted, a base taken from the wrong row, a NaN kept — still yields a smooth,
entirely plausible line. You cannot see it; you have to compare it.

It already earned that: the service defaulted to a 90-day rolling window where
charts.py used 91.

The reference is data/benchmark_series_golden.json, generated from those figures
while they still existed (see _regenerate below). Comparing against a frozen file
rather than a live call is what let the figures themselves be deleted — the
numbers they drew are still the thing this test holds the service to.
"""

import datetime as dt
import json
import math
import pathlib

import pandas as pd
import pytest

from app.services import benchmark_service as bs

_GOLDEN = pathlib.Path(__file__).parent / "data" / "benchmark_series_golden.json"

# Fixed dates, not a window ending today: the golden file has to stay valid
# tomorrow. Spans two calendar years so the YTD case has a real stretch of 2026.
_START = dt.date(2025, 2, 1)
_DAYS = 545
_YTD_YEAR = 2026


def _segments() -> list:
    """One contiguous investment period, daily, with a few deposits in it."""
    dates, values, cashflows = [], [], []
    value = 5000.0
    for i in range(_DAYS):
        value *= 1.0 + math.sin(i / 11.0) * 0.004 + 0.0004
        cash = 0.0
        if i > 0 and i % 90 == 0:
            cash = 500.0
            value += cash
        dates.append(_START + dt.timedelta(days=i))
        values.append(round(value, 4))
        cashflows.append(cash)
    cashflows[0] = 5000.0  # the initial investment
    return [(dates, values, cashflows)]


def _benchmark_prices() -> dict:
    """Two benchmarks: one covering the whole span, one starting later."""
    idx = pd.DatetimeIndex([_START + dt.timedelta(days=i) for i in range(_DAYS)])
    spy = pd.Series(
        [400.0 * (1.0 + math.sin(i / 17.0) * 0.05 + i * 0.0006) for i in range(_DAYS)], index=idx
    )
    # Starts 200 days in, so the indexed series has to pick its own base date
    # instead of padding backwards or being dropped.
    fez_idx = idx[200:]
    fez = pd.Series(
        [40.0 * (1.0 + math.cos(i / 23.0) * 0.03 + i * 0.0004) for i in range(len(fez_idx))],
        index=fez_idx,
    )
    return {"S&P 500 (SPY)": spy, "EURO STOXX 50 (FEZ)": fez}


def _actual() -> dict:
    segments, prices = _segments(), _benchmark_prices()
    return {
        "indexed": bs.indexed_series(segments, prices),
        "rolling": bs.rolling_series(segments, prices),
        "ytd": bs.ytd_series(segments, prices, _YTD_YEAR),
    }


@pytest.fixture(scope="module")
def golden() -> dict:
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("chart", ["indexed", "rolling", "ytd"])
def test_series_match_the_figures_they_replaced(golden, chart):
    expected = golden[chart]
    actual = _actual()[chart]

    assert actual["baseline"] == expected["baseline"]
    assert [s["label"] for s in actual["series"]] == [s["label"] for s in expected["series"]]

    for got, want in zip(actual["series"], expected["series"]):
        assert got["kind"] == want["kind"]
        assert [p["d"] for p in got["points"]] == [p["d"] for p in want["points"]], (
            f"{chart}/{got['label']}: different dates"
        )
        for a, b in zip(got["points"], want["points"]):
            assert a["v"] == pytest.approx(b["v"], abs=5e-4), (
                f"{chart}/{got['label']} on {a['d']}: {a['v']} vs {b['v']}"
            )


def test_the_rolling_window_is_the_one_the_streamlit_app_used():
    """Names the constant the golden file was generated with, so changing it is a
    failure here rather than a quietly different quarter."""
    assert bs.ROLLING_WINDOW_DAYS == 91


def test_the_portfolio_line_starts_at_100(golden):
    """Guards _compute_twr_index's chaining, not just the plumbing: the indexed
    chart's portfolio line *is* the TWR index."""
    portfolio = _actual()["indexed"]["series"][0]
    assert portfolio["kind"] == "portfolio"
    assert portfolio["points"][0]["v"] == pytest.approx(100.0)


def test_a_later_starting_benchmark_keeps_its_own_start():
    """FEZ begins 200 days into the span; it must be indexed on its own first
    close rather than padded backwards or dropped."""
    chart = _actual()["indexed"]
    fez = next(s for s in chart["series"] if s["label"].startswith("EURO STOXX"))
    assert fez["points"][0]["v"] == pytest.approx(100.0)
    assert fez["points"][0]["d"] > chart["series"][0]["points"][0]["d"]


# ---------------------------------------------------------------------------
# How data/benchmark_series_golden.json was made
#
# Run against the commit *before* charts.py's benchmark_*_chart functions were
# removed (facfc58 or earlier), where the figures still existed to read:
#
#     import charts, json
#     tx = [{"date": "2025-02-01", "isin": "X", "quantity": 1,
#            "transaction_type": "BUY"}]
#     segments, prices = _segments(), _benchmark_prices()
#     out = {}
#     for name, fig in (
#         ("indexed", charts.benchmark_indexed_chart(tx, {}, prices, [], segments=segments)),
#         ("rolling", charts.benchmark_rolling_return_chart(tx, {}, prices, [], segments=segments)),
#         ("ytd",     charts.benchmark_ytd_chart(tx, {}, prices, [], segments=segments)),
#     ):
#         out[name] = {
#             "baseline": 100.0 if name == "indexed" else 0.0,
#             "series": [
#                 {"label": bs.PORTFOLIO_LABEL if i == 0 else t.name,
#                  "kind": "portfolio" if i == 0 else "benchmark",
#                  "points": [{"d": pd.Timestamp(x).strftime("%Y-%m-%d"),
#                              "v": round(float(y), 4)}
#                             for x, y in zip(t.x, t.y)]}
#                 for i, t in enumerate(fig.data)
#             ],
#         }
#     _GOLDEN.write_text(json.dumps(out, indent=1))
#
# The YTD figure reads datetime.date.today().year internally, so it was generated
# in 2026 and the test passes _YTD_YEAR explicitly to match.
# ---------------------------------------------------------------------------
