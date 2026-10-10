""""Since your last visit" against "today".

Both figures sit on the same screen and both describe a portfolio's move, so
when they disagree there is no way to tell which one is missing five euro. They
did: a visit at 22:57 stored €13.878,12 — the price cache's own reading at that
moment — while the day chip measures from `previous_close`, which for the same
session close reads €13.873,22. Two fields of one feed, €4,90 apart, and the
strip reported €74,28 under a chip saying €79,19.

A visit that sits in the gap *between* two sessions has exactly one session
behind it, so it is today, and says so. A visit from during a session, or from
further back, keeps its own snapshot: over those windows the chip is not the
answer.

Both bounds are read off the data — the previous session's last intraday bar
and the running session's first — rather than off a clock or a calendar. A
portfolio can hold Frankfurt and New York at once, a holiday has no bar at all,
and "yesterday at 22:57" and "today at 08:00, before the open" are the same
position relative to the market. That last equivalence is the one this file
grew for: the route used to align only visits from an earlier calendar day, so
the second check of a morning reported its own snapshot under a chip saying
something else.

Each test was watched fail first (rule 3): by inverting each comparison, by
dropping the timezone conversion, by aligning unconditionally, and by removing
the upper bound.
"""

import datetime

import pytest

from app.services import dashboard_service as ds


DAY = {"delta_eur": 79.19, "pct": 0.57, "complete": True}

#: The session either side of the gap these tests reason about: Wednesday's
#: close at 17:25 Amsterdam (15:25 UTC) and Thursday's open at 09:00 (07:00).
CLOSED = "2026-07-29T15:25"
OPENED = "2026-07-30T07:00"


def _diff(last_seen: str, value_then=13878.12, value_now=13952.40):
    return {
        "last_seen_at": last_seen,
        "value_then": value_then,
        "value_delta": round(value_now - value_then, 2),
    }


def _at(local_naive: str, offset_hours=0):
    """A bar's timestamp, tz-aware like the series returns it."""
    return datetime.datetime.fromisoformat(local_naive).replace(
        tzinfo=datetime.timezone(datetime.timedelta(hours=offset_hours))
    )


def _align(last_seen, closed=CLOSED, opened=OPENED, day=DAY, **kwargs):
    return ds.align_visit_with_the_day(
        _diff(last_seen, **kwargs),
        _at(closed) if closed else None,
        _at(opened) if opened else None,
        day,
    )


# ---------------------------------------------------------------------------
# When it aligns: the visit sits in the gap between two sessions
# ---------------------------------------------------------------------------

def test_a_visit_after_the_close_reports_todays_change():
    # 15:25 UTC is 17:25 in Amsterdam; the visit at 22:57 saw a shut market.
    assert _align("2026-07-29T22:57:42")["value_delta"] == 79.19


def test_a_visit_this_morning_before_the_open_reports_todays_change():
    """The case the calendar-day gate used to drop.

    Checking the app at 08:05 and again at lunch is one session apart, exactly
    like checking it last night: nothing traded in between. Reported as its own
    snapshot this said €74,28 under a chip saying €79,19.
    """
    assert _align("2026-07-30T08:05:00")["value_delta"] == 79.19


def test_aligning_moves_the_baseline_with_the_delta():
    """value_then must stay consistent: it is what the strip subtracts from."""
    out = _align("2026-07-29T22:57:42")
    # value now is unchanged, so the baseline has to absorb the whole correction.
    assert round(out["value_then"] + out["value_delta"], 2) == 13952.40
    assert out["value_then"] == 13873.21


def test_the_close_is_read_in_local_time():
    """A visit at 18:00 local is after a 15:25 UTC close — 17:25 local."""
    # Comparing 18:00 against a naive 15:25 would call this "during the session"
    # and leave the snapshot in place.
    assert _align("2026-07-29T18:00:00")["value_delta"] == 79.19


def test_the_open_is_read_in_local_time():
    """A visit at 08:30 local is before a 07:00 UTC open — 09:00 local."""
    # Comparing 08:30 against a naive 07:00 would call this "during the session".
    assert _align("2026-07-30T08:30:00")["value_delta"] == 79.19


def test_exactly_at_the_open_is_still_before_it():
    assert _align("2026-07-30T09:00:00")["value_delta"] == 79.19


# ---------------------------------------------------------------------------
# When it must not
# ---------------------------------------------------------------------------

def test_a_visit_during_the_session_keeps_its_own_snapshot():
    # Half a session ago is not "today", and the chip cannot describe it.
    assert _align("2026-07-30T11:00:00")["value_delta"] == 74.28


def test_a_visit_from_before_the_previous_session_keeps_its_snapshot():
    assert _align("2026-07-24T20:00:00")["value_delta"] == 74.28


def test_exactly_at_the_close_is_not_after_it():
    assert _align("2026-07-29T17:25:00")["value_delta"] == 74.28


def test_a_weekend_visit_keeps_its_snapshot():
    """Saturday holds no session, so the last one started on Friday.

    The visit lands after that start, which is what makes it "during or after
    the last session" — over a window in which nothing traded the strip must
    say what it measured (about nothing), not repeat Friday's move.
    """
    out = _align(
        "2026-08-01T10:00:00",
        closed="2026-07-30T15:25",   # Thursday's close
        opened="2026-07-31T07:00",   # Friday's open — the last session there is
    )
    assert out["value_delta"] == 74.28


def test_no_day_chip_leaves_the_diff_alone():
    assert _align("2026-07-29T22:57:42", day=None)["value_delta"] == 74.28


def test_no_previous_close_leaves_the_diff_alone():
    """A holiday, or a portfolio with no intraday bars at all."""
    assert _align("2026-07-29T22:57:42", closed=None)["value_delta"] == 74.28


def test_a_missing_open_still_aligns_on_the_close_alone():
    """One bar and no second one: the session cannot have started yet."""
    assert _align("2026-07-29T22:57:42", opened=None)["value_delta"] == 79.19


def test_an_unparseable_timestamp_leaves_the_diff_alone():
    assert _align("not a date")["value_delta"] == 74.28


# ---------------------------------------------------------------------------
# Where the two timestamps come from
# ---------------------------------------------------------------------------

_INTRADAY = {
    "points": [
        {"d": "2026-07-29T15:25+00:00", "value": 13873.22},
        {"d": "2026-07-30T07:00+00:00", "value": 13835.79},
        {"d": "2026-07-30T07:05+00:00", "value": 13840.11},
    ],
    "prev_close": 13873.22,
}


def test_previous_close_at_reads_the_first_bar():
    assert ds.previous_close_at(_INTRADAY) == _at("2026-07-29T15:25")


def test_session_start_at_reads_the_bar_after_it():
    assert ds.session_start_at(_INTRADAY) == _at("2026-07-30T07:00")


def test_previous_close_at_is_none_without_a_baseline_point():
    # No previous session in the window: the first point is today's open, and
    # taking it for a close would align every visit to a partial day.
    assert ds.previous_close_at({"points": [{"d": "2026-07-30T07:00+00:00", "value": 1.0}], "prev_close": None}) is None
    assert ds.previous_close_at({"points": [], "prev_close": None}) is None


def test_session_start_at_is_none_when_the_previous_close_is():
    """Without a known close there is no gap to bound, so no start either —
    and points[1] would then be an ordinary bar of the running session."""
    assert ds.session_start_at({"points": [{"d": "2026-07-30T07:00+00:00", "value": 1.0},
                                           {"d": "2026-07-30T07:05+00:00", "value": 2.0}],
                                "prev_close": None}) is None


def test_session_start_at_is_none_when_the_session_has_no_bar_yet():
    """Before the open the line is one point long: the previous close."""
    assert ds.session_start_at({"points": [{"d": "2026-07-29T15:25+00:00", "value": 1.0}],
                                "prev_close": 1.0}) is None


@pytest.mark.parametrize("bad", [
    {"points": [{"d": "rubbish"}], "prev_close": 1.0},
    {"points": [{}], "prev_close": 1.0},
    {},
])
def test_previous_close_at_survives_a_malformed_payload(bad):
    assert ds.previous_close_at(bad) is None


@pytest.mark.parametrize("bad", [
    {"points": [{"d": "2026-07-29T15:25+00:00"}, {"d": "rubbish"}], "prev_close": 1.0},
    {"points": [{"d": "2026-07-29T15:25+00:00"}, {}], "prev_close": 1.0},
    {},
])
def test_session_start_at_survives_a_malformed_payload(bad):
    assert ds.session_start_at(bad) is None
