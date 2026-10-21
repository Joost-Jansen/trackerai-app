"""
The Calendar tab's arithmetic, without a network.

The tab's whole reason for existing is that its three kinds of date are not
equally well known, so most of what is tested here is the *boundary* between
fact and estimate: what earns a day cell, what is pushed down to the
month-precision strip, and what is left out entirely.

Each test was watched fail first: by asserting the opposite, by feeding the
pre-fix input, or by deleting the guard under test.
"""

import datetime
import sqlite3

import pytest

from app.services import calendar_service as cs
from domain import database

_TODAY = datetime.date(2026, 8, 8)


@pytest.fixture()
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "portfolio.db")
    c.row_factory = sqlite3.Row
    database.init_db(c)
    yield c
    c.close()


def _share(isin="NL0010773842", name="NN GROUP NV", ticker="NN.AS"):
    return {"isin": isin, "name": name, "ticker": ticker, "shares_held": 19.0}


def _tracker(isin="IE00B4L5Y983", name="ISHARES CORE MSCI WORLD UCITS ETF USD (ACC)", ticker="IWDA.AS"):
    return {"isin": isin, "name": name, "ticker": ticker, "shares_held": 8.0}


def _entry(isin="NL0010773842", name="NN GROUP NV", ticker="NN.AS", ex_date="2026-08-10", pay_date=None, earnings=("2026-08-06",)):
    return {
        "isin": isin,
        "ticker": ticker,
        "name": name,
        "ex_date": ex_date,
        "pay_date": pay_date,
        "earnings_dates": list(earnings),
    }


# ---------------------------------------------------------------------------
# Which holdings can report at all
# ---------------------------------------------------------------------------


def test_trackers_are_not_asked_for_reporting_dates():
    """A fund publishes no results of its own. An empty earnings row under
    IWDA would invent a document that does not exist."""
    shares = cs._shares([_share(), _tracker()])

    assert list(shares) == ["NL0010773842"]


# ---------------------------------------------------------------------------
# Reporting dates: day cell vs. strip
# ---------------------------------------------------------------------------


def test_a_confirmed_reporting_date_gets_a_day():
    stored = [{"isin": "NL0010773842", "date": "2026-08-06", "confirmed": True}]
    events, windows = cs.earnings_events(stored, [_entry()], cs._shares([_share()]))

    assert windows == []
    assert [(e["date"], e["type"]) for e in events] == [("2026-08-06", "earnings")]


def test_a_two_date_window_never_gets_a_day():
    """Yahoo returns two dates when the company has not pinned the date down.
    That is a guess, and the app's rule is that a guess is shown at month
    precision — so both ends stay out of the grid and one row goes to the
    strip."""
    entry = _entry(earnings=("2026-11-04", "2026-11-08"))
    stored = [
        {"isin": "NL0010773842", "date": "2026-11-04", "confirmed": False},
        {"isin": "NL0010773842", "date": "2026-11-08", "confirmed": False},
    ]

    events, windows = cs.earnings_events(stored, [entry], cs._shares([_share()]))

    assert events == []
    assert len(windows) == 1
    assert (windows[0]["from"], windows[0]["to"]) == ("2026-11-04", "2026-11-08")
    assert windows[0]["month"] == "2026-11"
    assert windows[0]["source"] == "estimate"


def test_a_date_the_sweep_has_since_confirmed_moves_into_the_grid():
    """Stored as a window, confirmed by a later sweep. The fresh view wins:
    otherwise a date the company has now announced would sit in the strip
    until the row happened to be rewritten."""
    stored = [{"isin": "NL0010773842", "date": "2026-11-04", "confirmed": False}]
    entry = _entry(earnings=("2026-11-04",))

    events, windows = cs.earnings_events(stored, [entry], cs._shares([_share()]))

    assert windows == []
    assert [e["date"] for e in events] == ["2026-11-04"]


def test_a_remembered_date_survives_the_sweep_forgetting_it():
    """Yahoo carries only the *next* reporting date, so the day a company
    reports, its date starts sliding out of the feed. The whole point of the
    earnings_dates table is that the past does not empty out behind you."""
    stored = [
        {"isin": "NL0010773842", "date": "2026-05-14", "confirmed": True},
        {"isin": "NL0010773842", "date": "2026-08-06", "confirmed": True},
    ]
    sweep_only_knows_the_next_one = [_entry(earnings=("2026-08-06",))]

    events, _ = cs.earnings_events(stored, sweep_only_knows_the_next_one, cs._shares([_share()]))

    assert [e["date"] for e in events] == ["2026-05-14", "2026-08-06"]


def test_a_reporting_date_for_a_holding_that_is_gone_is_dropped():
    stored = [{"isin": "SOLD0001", "date": "2026-08-06", "confirmed": True}]

    events, _ = cs.earnings_events(stored, [], cs._shares([_share()]))

    assert events == []


# ---------------------------------------------------------------------------
# Ex-dividend and paid dividend
# ---------------------------------------------------------------------------


def test_official_ex_dividend_dates_are_kept_for_held_positions_only():
    entries = [_entry(), _entry(isin="SOLD0001", ticker="X.AS", ex_date="2026-09-01")]

    events = cs.ex_dividend_events(entries, held={"NL0010773842"})

    assert [(e["isin"], e["date"]) for e in events] == [("NL0010773842", "2026-08-10")]


def test_same_day_dividend_lines_are_one_payment():
    """DeGiro splits one payment into a gross line and a tax line. Two rows on
    one day would read as two dividends on the calendar."""
    dividends = [
        {"isin": "IE00B4L5Y983", "date": "2026-06-12", "net_eur": 14.20},
        {"isin": "IE00B4L5Y983", "date": "2026-06-12", "net_eur": -2.13},
    ]

    events = cs.dividend_paid_events(dividends, {"IE00B4L5Y983": "IWDA"})

    assert len(events) == 1
    assert events[0]["amount_eur"] == 12.07
    assert events[0]["type"] == "dividend_paid"


def test_a_payment_that_nets_to_zero_is_not_an_event():
    dividends = [
        {"isin": "IE00B4L5Y983", "date": "2026-06-12", "net_eur": 5.0},
        {"isin": "IE00B4L5Y983", "date": "2026-06-12", "net_eur": -5.0},
    ]

    assert cs.dividend_paid_events(dividends, {}) == []


# ---------------------------------------------------------------------------
# The strip
# ---------------------------------------------------------------------------


def test_an_official_date_is_not_repeated_in_the_estimate_strip():
    """merge_official_ex_dividends replaces a holding's first estimate with the
    real date and labels it "official". That row already has a day cell from
    ex_dividend_events; carrying it here too printed the same ex-dividend twice
    on one month.
    """
    outlook = {
        "upcoming": [
            {
                "isin": "NL0010773842",
                "name": "NN",
                "date": "2026-08-10",
                "month": "2026-08",
                "part": "early",
                "source": "official",
                "expected_eur": 32.0,
                "confidence": "high",
                "cadence": "semiannual",
            },
            {
                "isin": "IE00B4L5Y983",
                "name": "IWDA",
                "date": "2026-09-18",
                "month": "2026-09",
                "part": "mid",
                "source": "estimate",
                "expected_eur": 12.0,
                "confidence": "medium",
                "cadence": "quarterly",
            },
        ]
    }

    rows = cs.estimate_rows(outlook, windows=[])

    assert [r["isin"] for r in rows] == ["IE00B4L5Y983"]


def test_the_strip_carries_no_exact_day():
    """The app's one rule about a estimate: month precision, never a day. If an
    estimate ever reaches the frontend with a date on it, someone will render
    it in a cell.
    """
    outlook = {
        "upcoming": [
            {
                "isin": "IE00B4L5Y983",
                "name": "IWDA",
                "date": "2026-09-18",
                "month": "2026-09",
                "part": "mid",
                "source": "estimate",
                "expected_eur": 12.0,
                "confidence": "medium",
                "cadence": "quarterly",
            },
        ]
    }

    rows = cs.estimate_rows(outlook, windows=[])

    assert "date" not in rows[0]
    assert (rows[0]["month"], rows[0]["part"]) == ("2026-09", "mid")


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


def test_the_window_spans_whole_months_either_side_of_today():
    start, end = cs._window(_TODAY)

    assert start == "2025-08-01"  # a year back, from the 1st
    assert end == "2027-08-31"  # a year ahead, to the last day


def test_events_outside_the_window_are_dropped(conn, monkeypatch):
    monkeypatch.setattr(cs.filings_service, "reports_for", lambda *a, **k: {})
    dividends = [
        {"isin": "IE00B4L5Y983", "date": "2019-06-12", "net_eur": 9.0},  # too old
        {"isin": "IE00B4L5Y983", "date": "2026-06-12", "net_eur": 12.0},
    ]

    out = cs.build(conn, [_tracker()], dividends, {"upcoming": []}, [], today=_TODAY)

    assert [e["date"] for e in out["events"]] == ["2026-06-12"]


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def test_build_separates_facts_from_estimates(conn, monkeypatch):
    monkeypatch.setattr(cs.filings_service, "reports_for", lambda *a, **k: {})
    database.record_earnings_dates(conn, [{"isin": "NL0010773842", "date": "2026-08-06", "confirmed": True}])
    outlook = {
        "upcoming": [
            {
                "isin": "IE00B4L5Y983",
                "name": "IWDA",
                "date": "2026-09-18",
                "month": "2026-09",
                "part": "mid",
                "source": "estimate",
                "expected_eur": 12.0,
                "confidence": "medium",
                "cadence": "quarterly",
            },
        ],
        "rest_of_year_eur": 41.5,
    }

    out = cs.build(
        conn,
        [_share(), _tracker()],
        [{"isin": "IE00B4L5Y983", "date": "2026-06-12", "net_eur": 12.07}],
        outlook,
        [_entry()],
        today=_TODAY,
    )

    by_type = {e["type"] for e in out["events"]}
    assert by_type == {"earnings", "ex_dividend", "dividend_paid"}
    assert all("date" in e for e in out["events"])
    assert [r["isin"] for r in out["estimates"]] == ["IE00B4L5Y983"]
    assert out["share_count"] == 1
    assert out["rest_of_year_eur"] == 41.5


def test_a_portfolio_of_only_trackers_is_not_an_error(conn, monkeypatch):
    """Eleven funds and no shares is a real portfolio, not a failure. The tab
    needs share_count to say "no shares" rather than implying the reporting
    dates went missing.
    """
    monkeypatch.setattr(cs.filings_service, "reports_for", lambda *a, **k: {})

    out = cs.build(conn, [_tracker()], [], {"upcoming": []}, [], today=_TODAY)

    assert out["share_count"] == 0
    assert out["events"] == []


def test_a_past_reporting_date_carries_its_report(conn, monkeypatch):
    monkeypatch.setattr(
        cs.filings_service,
        "reports_for",
        lambda *a, **k: {
            "NL0010773842": {"kind": "site", "source": None, "url": "https://www.nn-group.com"},
        },
    )
    database.record_earnings_dates(conn, [{"isin": "NL0010773842", "date": "2026-08-06", "confirmed": True}])

    out = cs.build(conn, [_share()], [], {"upcoming": []}, [_entry()], today=_TODAY)

    earnings = [e for e in out["events"] if e["type"] == "earnings"]
    assert earnings[0]["report"] == {
        "kind": "site",
        "url": "https://www.nn-group.com",
        "label": None,
        "source": None,
    }
