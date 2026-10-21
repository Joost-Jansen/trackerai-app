"""
frontend/lib/dashboard.ts's range slicing and the figures the value card prints
from it, driven through node — the real module runs, against expectations
computed independently here.

This is the seam two of this app's return bugs lived in. Both functions were
pure, tested-looking code that nothing tested: the file used to drive
sliceRange() and rebase(), the two helpers of a dashboard card that no longer
exists, while rangeBreakdown — which prints the euro and the percentage on the
card that does — was covered by nothing at all.

Two rules it pins, both of them shared with the backend:

  * a period label means the same window here and in
    returns_service._range_starts (calendar months, clamped), so "3M" on the
    dashboard and "3M" on the Returns tab are the same three months;
  * the return percentage divides by the with-dividends base, exactly as
    returns_service.build does.

Watched fail first (rule 3): by putting `value` back in rangeBreakdown's
denominator, and by reverting addMonths to setMonth's overflow.
"""

import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_DASHBOARD_TS = os.path.join(_REPO_ROOT, "frontend", "lib", "dashboard.ts")
# Resolves "@/…" and extensionless imports in the app's modules, as Next does.
_TS_RESOLVE = pathlib.Path(_REPO_ROOT, "frontend", "scripts", "ts-resolve.mjs").as_uri()
sys.path.insert(0, os.path.join(_REPO_ROOT, "backend"))

_DRIVER = """
import { sliceByRange, rangeBreakdown, splitChange } from %(dashboard_ts)s;
import { readFileSync } from "node:fs";
const { points, ranges } = JSON.parse(readFileSync(%(cases)s, "utf8"));
const out = {};
for (const r of ranges) {
  const sliced = sliceByRange(points, r);
  const a = sliced[0], b = sliced[sliced.length - 1];
  out[r] = { first: a.d, last: b.d, n: sliced.length,
             breakdown: rangeBreakdown(points, sliced),
             span: splitChange(a, b) };
}
console.log(JSON.stringify(out));
"""

needs_node = pytest.mark.skipif(
    shutil.which("node") is None or not os.path.exists(_DASHBOARD_TS),
    reason="needs node and frontend/lib/dashboard.ts",
)

RANGES = ["1D", "1W", "1M", "3M", "YTD", "1Y", "3Y", "5Y", "All"]


def _run_node(payload, tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps(payload), encoding="utf-8")
    driver = tmp_path / "driver.mjs"
    driver.write_text(
        # as_uri(), not the bare path: an ESM import specifier must be a
        # file:// URL, and a Windows path ("C:\\...") makes Node read the drive
        # letter as an unsupported protocol. On POSIX this is the same path with
        # a file:// prefix, so one form works on both.
        _DRIVER
        % {
            "dashboard_ts": json.dumps(pathlib.Path(_DASHBOARD_TS).as_uri()),
            "cases": json.dumps(str(cases_path)),
        },
        encoding="utf-8",
    )
    proc = subprocess.run(
        [shutil.which("node"), "--import", _TS_RESOLVE, str(driver)],
        capture_output=True,
        text=True,
        # Explicit: text=True would otherwise decode with the platform locale
        # (cp1252 on Windows). This driver's output is ASCII today, but the
        # sibling format-parity test broke on exactly that.
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _value_points(start: datetime.date, end: datetime.date):
    """A daily series with one deposit and one dividend, both far enough back to
    fall inside every range but 1D and 1W.

    value rises a euro a day; `invested` steps by EUR 500 on day 200; EUR 100 of
    dividend lands on day 50, which is what makes the with-dividends base
    visible in the percentages below.
    """
    points = []
    day, i = start, 0
    while day <= end:
        value = 1000.0 + i
        points.append(
            {
                "d": day.isoformat(),
                "invested": 1000.0 if i < 200 else 1500.0,
                "value": value,
                "value_divs": value + (100.0 if i >= 50 else 0.0),
            }
        )
        day += datetime.timedelta(days=1)
        i += 1
    return points


# ---------------------------------------------------------------------------
# One label, one window — here and on the Returns tab
# ---------------------------------------------------------------------------


@needs_node
def test_the_ranges_start_where_the_calendar_says(tmp_path):
    points = _value_points(datetime.date(2025, 3, 1), datetime.date(2026, 7, 17))
    out = _run_node({"points": points, "ranges": RANGES}, tmp_path)

    assert out["All"]["first"] == "2025-03-01" and out["All"]["n"] == len(points)
    assert out["YTD"]["first"] == "2026-01-01"
    assert out["1M"]["first"] == "2026-06-17"
    assert out["3M"]["first"] == "2026-04-17"
    assert out["1Y"]["first"] == "2025-07-17"
    assert out["1W"]["first"] == "2026-07-10"
    assert out["1D"]["n"] == 2 and out["1D"]["first"] == "2026-07-16"
    for r in out.values():
        assert r["last"] == "2026-07-17"
    # This series is 16 months long, so 3J and 5J reach past its start and slice
    # to the whole thing. sliceByRange is right to do that; it is availableRanges
    # (below) that keeps those two buttons off the screen, because three buttons
    # drawing one line reads as a broken button.
    assert out["3Y"] == out["All"] and out["5Y"] == out["All"]


_AVAILABLE_DRIVER = """
import { availableRanges } from %(dashboard_ts)s;
import { readFileSync } from "node:fs";
const { series } = JSON.parse(readFileSync(%(cases)s, "utf8"));
console.log(JSON.stringify(series.map((points) => availableRanges(points))));
"""


def _available(series, tmp_path):
    """availableRanges for each series, through the real module."""
    cases_path = tmp_path / "available.json"
    cases_path.write_text(json.dumps({"series": series}), encoding="utf-8")
    driver = tmp_path / "available.mjs"
    driver.write_text(
        _AVAILABLE_DRIVER
        % {
            "dashboard_ts": json.dumps(pathlib.Path(_DASHBOARD_TS).as_uri()),
            "cases": json.dumps(str(cases_path)),
        },
        encoding="utf-8",
    )
    proc = subprocess.run(
        [shutil.which("node"), "--import", _TS_RESOLVE, str(driver)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@needs_node
def test_a_period_older_than_the_portfolio_is_not_offered(tmp_path):
    """A window starting before the first day draws exactly the "All" line.

    Same rule as returns_service._range_starts, which skips such a window rather
    than repeating it under another name — and the reason adding 3J and 5J did
    not give every young portfolio three identical buttons.
    """
    end = datetime.date(2026, 7, 17)
    eight_years = _value_points(end - datetime.timedelta(days=2920), end)
    sixteen_months = _value_points(datetime.date(2025, 3, 1), end)
    four_days = _value_points(end - datetime.timedelta(days=3), end)

    long_, medium, short = _available([eight_years, sixteen_months, four_days], tmp_path)

    assert long_ == ["1D", "1W", "1M", "3M", "YTD", "1Y", "3Y", "5Y", "All"]
    assert medium == ["1D", "1W", "1M", "3M", "YTD", "1Y", "All"]
    # Four days: only yesterday is inside the series. A week already reaches
    # past its first day, and so does everything longer.
    assert short == ["1D", "All"]


@needs_node
def test_the_one_range_that_always_survives_is_all(tmp_path):
    """Two points is the least a line can be drawn from, and one point is fewer
    than that — but the period buttons still need something to be pressed, and
    "All" is the only label that cannot be wrong about its own window.
    """
    single = [{"d": "2026-07-17", "invested": 1000.0, "value": 1000.0, "value_divs": 1000.0}]
    empty, one = _available([[], single], tmp_path)

    assert empty == ["All"]
    assert one == ["All"]


@needs_node
@pytest.mark.parametrize("last", ["2026-07-17", "2026-03-31", "2026-05-31", "2024-02-29"])
def test_the_windows_match_the_backends_to_the_day(tmp_path, last):
    """The dates that used to differ: month ends, where setMonth overflowed, and
    leap day. A "3M" the two tabs disagree about is two answers to one button —
    it read +8,5% against +6,9% on the same portfolio.

    3J and 5J are in here for the same reason: they existed on the Returns tab
    long before the dashboard offered them, so the day they appeared on both is
    the day they could start disagreeing. The series runs eight years back, far
    enough that even the 60-month window has an earlier point to start on.
    """
    from app.services import returns_service as rs

    end = datetime.date.fromisoformat(last)
    points = _value_points(end - datetime.timedelta(days=2920), end)
    out = _run_node({"points": points, "ranges": ["1M", "3M", "1Y", "3Y", "5Y"]}, tmp_path)

    for label, months in (("1M", 1), ("3M", 3), ("1Y", 12), ("3Y", 36), ("5Y", 60)):
        assert out[label]["first"] == rs._months_before(end, months).isoformat(), label


# ---------------------------------------------------------------------------
# What the card's header prints
# ---------------------------------------------------------------------------


@needs_node
def test_the_percentage_divides_by_the_base_including_earlier_dividends(tmp_path):
    """The gain is measured on the with-dividends series, so the base is too.

    The EUR 100 paid out on day 50 is inside the base of every window that opens
    after it. Leaving it out — dividing a with-dividends gain by a value-only
    base — inflated the percentage: on the real portfolio YTD read 16,5% where
    the same window is 16,2%.
    """
    points = _value_points(datetime.date(2025, 3, 1), datetime.date(2026, 7, 17))
    by_date = {p["d"]: p for p in points}
    out = _run_node({"points": points, "ranges": ["1M", "3M", "1Y"]}, tmp_path)
    end = points[-1]

    for label, res in out.items():
        base = by_date[res["first"]]
        contrib = end["invested"] - base["invested"]
        gain = end["value_divs"] - base["value_divs"] - contrib
        b = res["breakdown"]

        assert b["gain"] == pytest.approx(gain), label
        assert b["contrib"] == pytest.approx(contrib), label
        assert b["pct"] == pytest.approx(gain / (base["value_divs"] + max(contrib, 0.0)) * 100.0), label
        # And demonstrably not the old base, which is EUR 100 smaller.
        assert b["pct"] != pytest.approx(gain / (base["value"] + max(contrib, 0.0)) * 100.0), label


@needs_node
def test_a_window_reaching_inception_counts_the_first_purchase_as_invested(tmp_path):
    """No earlier point, so there is no baseline: what was paid is inleg, and
    the percentage is measured over it. Same rule as returns_service's "All",
    and what keeps both equal to the hero's "since start".
    """
    points = _value_points(datetime.date(2025, 3, 1), datetime.date(2026, 7, 17))
    out = _run_node({"points": points, "ranges": ["All"]}, tmp_path)
    b = out["All"]["breakdown"]
    end = points[-1]

    assert b["contrib"] == pytest.approx(end["invested"])  # 1500, all of it
    assert b["gain"] == pytest.approx(end["value_divs"] - end["invested"])
    assert b["pct"] == pytest.approx(b["gain"] / end["invested"] * 100.0)


@needs_node
def test_the_two_finger_measurement_measures_its_own_line(tmp_path):
    """splitChange reads the value line, dividends deliberately outside it — so
    its base stays on `value` where the header's is on `value_divs`. One rule,
    two numerators; mixing them is what inflates a percentage."""
    points = _value_points(datetime.date(2025, 3, 1), datetime.date(2026, 7, 17))
    by_date = {p["d"]: p for p in points}
    out = _run_node({"points": points, "ranges": ["3M"]}, tmp_path)
    span, res = out["3M"]["span"], out["3M"]
    a, b = by_date[res["first"]], by_date[res["last"]]

    contrib = b["invested"] - a["invested"]
    market = (b["value"] - a["value"]) - contrib
    assert span["market"] == pytest.approx(market)
    assert span["pct"] == pytest.approx(market / (a["value"] + max(contrib, 0.0)) * 100.0)
    # The dividend is reported beside the split, never inside it.
    assert span["dividends"] == pytest.approx((b["value_divs"] - b["value"]) - (a["value_divs"] - a["value"]))


# ---------------------------------------------------------------------------
# The value series only sums euros
# ---------------------------------------------------------------------------


def test_a_non_eur_quote_is_not_summed_into_the_euro_value_series():
    """A quote in another currency used to go into the euro total unconverted:
    a holding worth $110 a share counted as EUR 110 a share, drawing the value
    line ~9% high — while the Portfolio tab, correctly, refused to value the
    same position at all. The cost basis stands in instead, as the TWR series
    already did.
    """
    from domain.portfolio import positions as portfolio
    from domain.portfolio import series as charts

    txns = [
        {
            "isin": "US1",
            "name": "A US stock",
            "date": "2026-07-01",
            "time": "09:00",
            "exchange": "NDQ",
            "transaction_type": "BUY",
            "quantity": 100.0,
            "total_eur": 9000.0,
            "value_eur": 9000.0,
            "transaction_fee": 0.0,
            "autofx_cost": 0.0,
        }
    ]
    prices = {"US1": {"isin": "US1", "ticker": None, "price": 110.0, "currency": "USD", "previous_close": 109.0}}

    assert portfolio.calculate_positions(txns, prices)[0]["current_value"] is None

    _dates, invested, values, _vd = charts.portfolio_history_series(txns, prices, [])
    assert values, "the chart must still be drawable, not blanked"
    assert values[-1] == 9000.0  # cost basis, not 100 x 110
    assert invested[-1] == 9000.0


def test_a_eur_quote_still_prices_the_series_at_the_price():
    from domain.portfolio import series as charts

    txns = [
        {
            "isin": "NL1",
            "name": "ASML",
            "date": "2026-07-01",
            "time": "09:00",
            "exchange": "EAM",
            "transaction_type": "BUY",
            "quantity": 10.0,
            "total_eur": 7000.0,
            "value_eur": 7000.0,
            "transaction_fee": 0.0,
            "autofx_cost": 0.0,
        }
    ]
    prices = {"NL1": {"isin": "NL1", "ticker": None, "price": 750.0, "currency": "EUR", "previous_close": 740.0}}
    _dates, invested, values, _vd = charts.portfolio_history_series(txns, prices, [])
    assert values[-1] == 7500.0
    assert invested[-1] == 7000.0


def test_the_total_return_percentage_is_none_once_more_came_out_than_went_in():
    """net_investment goes negative when you have cashed out more than you ever
    put in, and dividing by it flipped the sign: a +EUR 3.500 profit read as
    -116,67%."""
    from domain.portfolio import positions as portfolio

    txns = [
        {
            "isin": "A",
            "name": "A",
            "date": "2020-01-01",
            "time": "09:00",
            "transaction_type": "BUY",
            "quantity": 100.0,
            "total_eur": 1000.0,
            "value_eur": 1000.0,
            "transaction_fee": 0.0,
            "autofx_cost": 0.0,
        },
        {
            "isin": "A",
            "name": "A",
            "date": "2024-01-01",
            "time": "09:00",
            "transaction_type": "SELL",
            "quantity": 90.0,
            "total_eur": 4000.0,
            "value_eur": 4000.0,
            "transaction_fee": 0.0,
            "autofx_cost": 0.0,
        },
    ]
    prices = {"A": {"isin": "A", "currency": "EUR", "price": 50.0, "ticker": "A.AS", "previous_close": 49.0}}
    positions = portfolio.calculate_positions(txns, prices)
    summary = portfolio.calculate_portfolio_summary(positions, txns, [])

    assert summary["net_investment"] == -3000.0
    assert summary["total_gain"] == 3500.0
    assert summary["total_return_pct"] is None


def test_the_total_return_percentage_is_still_a_number_in_the_normal_case():
    from domain.portfolio import positions as portfolio

    txns = [
        {
            "isin": "A",
            "name": "A",
            "date": "2020-01-01",
            "time": "09:00",
            "transaction_type": "BUY",
            "quantity": 10.0,
            "total_eur": 1000.0,
            "value_eur": 1000.0,
            "transaction_fee": 0.0,
            "autofx_cost": 0.0,
        }
    ]
    prices = {"A": {"isin": "A", "currency": "EUR", "price": 110.0, "ticker": "A.AS", "previous_close": 109.0}}
    positions = portfolio.calculate_positions(txns, prices)
    summary = portfolio.calculate_portfolio_summary(positions, txns, [])
    assert summary["total_return_pct"] == 10.0
