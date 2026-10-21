"""
The cockpit dashboard's deterministic arithmetic: day changes, dividend
aggregation, the visit-snapshot diff, news classification, calendar filtering
and benchmark alignment. Everything here runs without a network.

Each test was watched fail first (rule 3): asserting the wrong sign, dropping
the fix, or feeding the pre-fix input.
"""

import datetime
import sqlite3

import pytest

from app.services import dashboard_service as ds
from app.services import news_service
from domain import database

# ---------------------------------------------------------------------------
# Day change
# ---------------------------------------------------------------------------


def _pos(isin="X1", name="Fund", shares=10.0, value=1100.0, ticker="X1.AS"):
    return {
        "isin": isin,
        "name": name,
        "ticker": ticker,
        "shares_held": shares,
        "current_value": value,
    }


def _price(price=110.0, prev=100.0, currency="EUR", fetched_at=None):
    """A price row. `fetched_at` defaults to now, because that is what the
    refresh writes and what the day figure is only honest about."""
    if fetched_at is None:
        fetched_at = datetime.datetime.now().isoformat(timespec="seconds")
    return {
        "price": price,
        "previous_close": prev,
        "currency": currency,
        "fetched_at": fetched_at,
    }


def test_day_change_math():
    positions = [_pos(shares=10, value=1100.0)]
    prices = {"X1": _price(price=110.0, prev=100.0)}
    day = ds.portfolio_day_change(positions, prices)
    assert day["delta_eur"] == 100.0
    assert day["pct"] == 10.0
    assert day["complete"] is True
    assert day["stale"] is False


# ---------------------------------------------------------------------------
# Staleness of the day figure
#
# The chip said "today" off whatever was in the cache, however old. These
# hold it to saying so only when it is true — and to still *showing* the
# figure when it is not, since a chip that disappears asks a question the
# screen cannot answer.
# ---------------------------------------------------------------------------


def test_day_change_is_marked_stale_when_the_cache_missed_a_close():
    week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat(timespec="seconds")
    positions = [_pos(shares=10, value=1100.0)]
    prices = {"X1": _price(price=110.0, prev=100.0, fetched_at=week_ago)}

    day = ds.portfolio_day_change(positions, prices)
    # Still reported — the number is real, it is just not about today.
    assert day["delta_eur"] == 100.0
    assert day["stale"] is True
    assert day["as_of"] == week_ago


def test_day_change_as_of_is_the_oldest_quote_not_the_newest():
    """One position refreshing while another did not must not read as fresh."""
    old = (datetime.datetime.now() - datetime.timedelta(days=5)).isoformat(timespec="seconds")
    now = datetime.datetime.now().isoformat(timespec="seconds")
    positions = [_pos(isin="X1", shares=10, value=1100.0), _pos(isin="X2", shares=10, value=1100.0)]
    prices = {"X1": _price(fetched_at=old), "X2": _price(fetched_at=now)}

    day = ds.portfolio_day_change(positions, prices)
    assert day["as_of"] == old
    assert day["stale"] is True


def test_day_change_without_a_timestamp_is_not_treated_as_fresh():
    positions = [_pos()]
    prices = {"X1": {"price": 110.0, "previous_close": 100.0, "currency": "EUR"}}
    day = ds.portfolio_day_change(positions, prices)
    assert day["as_of"] is None
    assert day["stale"] is True


def test_day_change_none_without_previous_close():
    positions = [_pos()]
    prices = {"X1": _price(prev=None)}
    assert ds.portfolio_day_change(positions, prices) is None


def test_day_change_skips_non_eur_and_flags_incomplete():
    positions = [_pos("X1", shares=10), _pos("X2", shares=5)]
    prices = {
        "X1": _price(price=102.0, prev=100.0),
        "X2": _price(price=50.0, prev=49.0, currency="USD"),
    }
    day = ds.portfolio_day_change(positions, prices)
    assert day["delta_eur"] == 20.0
    assert day["complete"] is False


def test_day_movers_top_and_bottom():
    positions = [_pos("A", "Up a lot"), _pos("B", "Down"), _pos("C", "Up a bit")]
    prices = {
        "A": _price(price=104.8, prev=100.0),
        "B": _price(price=97.9, prev=100.0),
        "C": _price(price=100.5, prev=100.0),
    }
    m = ds.day_movers(positions, prices)
    assert m["top"]["isin"] == "A" and m["top"]["day_pct"] == 4.8
    assert m["bottom"]["isin"] == "B" and m["bottom"]["day_pct"] == -2.1


def test_day_movers_single_position_has_no_bottom():
    m = ds.day_movers([_pos("A")], {"A": _price()})
    assert m["top"]["isin"] == "A"
    assert m["bottom"] is None


# ---------------------------------------------------------------------------
# Dividend aggregation
# ---------------------------------------------------------------------------

_TODAY = datetime.date(2026, 7, 17)


def test_dividend_stats_month_and_year():
    dividends = [
        {"date": "2026-07-02", "net_eur": 10.0},
        {"date": "2026-07-15", "net_eur": 8.4},
        {"date": "2026-03-01", "net_eur": 50.0},
        {"date": "2025-07-17", "net_eur": 99.0},  # last year's July: year only? no — neither
        {"date": "2026-01-10", "net_eur": 1.6},
    ]
    stats = ds.dividend_stats(dividends, today=_TODAY)
    assert stats == {"this_month": 18.4, "this_year": 70.0}


def test_dividend_stats_empty():
    assert ds.dividend_stats([], today=_TODAY) == {"this_month": 0.0, "this_year": 0.0}


def test_dividends_since_is_strictly_after():
    dividends = [
        {"date": "2026-07-10", "net_eur": 5.0},
        {"date": "2026-07-14", "net_eur": 18.4},
        {"date": "2026-07-16", "net_eur": 2.0},
    ]
    since = ds.dividends_since(dividends, "2026-07-14T09:30:00")
    assert since == {"count": 1, "total_eur": 2.0}


def test_latest_dividend_by_isin_sums_same_day_rows():
    dividends = [
        {"isin": "S", "date": "2026-05-01", "net_eur": 10.0},
        {"isin": "S", "date": "2026-06-01", "net_eur": 6.0},
        {"isin": "S", "date": "2026-06-01", "net_eur": 6.9},  # gross+net split rows
        {"isin": "T", "date": "2026-04-01", "net_eur": 3.0},
    ]
    assert ds.latest_dividend_by_isin(dividends) == {"S": 12.9, "T": 3.0}


# ---------------------------------------------------------------------------
# Visit snapshots
# ---------------------------------------------------------------------------


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    database.init_db(c)
    yield c
    c.close()


def _t(hours=0, minutes=0):
    return datetime.datetime(2026, 7, 17, 10, 0, 0) + datetime.timedelta(hours=hours, minutes=minutes)


def test_first_visit_returns_none(conn):
    assert ds.record_visit(conn, 1000.0, now=_t()) is None


def test_reload_within_gap_is_same_session(conn):
    ds.record_visit(conn, 1000.0, now=_t())
    # Two quick reloads: still nothing to compare against.
    assert ds.record_visit(conn, 1001.0, now=_t(minutes=5)) is None
    assert ds.record_visit(conn, 1002.0, now=_t(minutes=10)) is None
    assert len(database.load_recent_visits(conn, 10)) == 1


def test_new_session_diffs_against_last_seen_value(conn):
    ds.record_visit(conn, 1000.0, now=_t())
    ds.record_visit(conn, 1010.0, now=_t(minutes=10))  # session 1 ends at 1010
    diff = ds.record_visit(conn, 1422.0, now=_t(hours=72))
    assert diff["value_then"] == 1010.0
    assert diff["value_delta"] == 412.0
    assert diff["last_seen_at"] == _t(minutes=10).isoformat(timespec="seconds")


def test_second_session_keeps_baseline_across_reloads(conn):
    ds.record_visit(conn, 1000.0, now=_t())
    ds.record_visit(conn, 1500.0, now=_t(hours=48))
    diff = ds.record_visit(conn, 1600.0, now=_t(hours=48, minutes=5))
    assert diff["value_then"] == 1000.0
    assert diff["value_delta"] == 600.0


def test_none_value_never_erases_known_value(conn):
    ds.record_visit(conn, 1000.0, now=_t())
    ds.record_visit(conn, None, now=_t(minutes=5))  # prices unavailable mid-session
    diff = ds.record_visit(conn, 1200.0, now=_t(hours=48))
    assert diff["value_then"] == 1000.0


def test_visit_without_prices_gives_no_diff(conn):
    ds.record_visit(conn, 1000.0, now=_t())
    assert ds.record_visit(conn, None, now=_t(hours=48)) is None


# ---------------------------------------------------------------------------
# News classification
# ---------------------------------------------------------------------------


# Classification now lives in news_service (shared by the dashboard teaser and
# the News tab); the dashboard delegates to it.
@pytest.mark.parametrize(
    "title,label",
    [
        ("ASML beats expectations as bookings jump 24% on AI demand", "Earnings"),
        ("Shell raises quarterly dividend by 4%, starts new buyback", "Dividend"),
        ("Morgan Stanley upgrades Microsoft to Overweight, price target $480", "Analyst"),
        ("Novo Nordisk acquires Catalent site to expand capacity", "M&A"),
        ("Israel and Iran agree ceasefire after two weeks of war", "World"),
        ("ECB holds rates steady, points to cooling inflation", "Macro"),
        ("Trump announces new tariffs on EU steel imports", "Macro"),
        ("Something entirely unclassifiable happened", "Macro"),
    ],
)
def test_classify_news(title, label):
    assert news_service.classify_news(title) == label


def test_classify_news_reads_the_summary_too():
    # A terse headline, the signal in the body.
    assert news_service.classify_news("ASML Q2", "raises full-year dividend") == "Dividend"


# ---------------------------------------------------------------------------
# Ex-dividend calendar
# ---------------------------------------------------------------------------


def test_upcoming_ex_dividends_filters_and_sorts():
    entries = [
        {"isin": "A", "ticker": "A.AS", "name": "A", "ex_date": "2026-07-10", "pay_date": None},
        {"isin": "B", "ticker": "B.AS", "name": "B", "ex_date": "2026-08-14", "pay_date": "2026-09-01"},
        {"isin": "C", "ticker": "C.AS", "name": "C", "ex_date": "2026-07-21", "pay_date": None},
    ]
    out = ds.upcoming_ex_dividends(entries, {"B": 12.9}, today=_TODAY)
    assert [e["isin"] for e in out] == ["C", "B"]  # past A dropped, sorted
    assert out[1]["estimate_eur"] == 12.9
    assert out[0]["estimate_eur"] is None


# ---------------------------------------------------------------------------
# Dividend forecast (estimate from payment history)
# ---------------------------------------------------------------------------


def _series(start: datetime.date, step_days: int, amounts: list[float], jitter: list[int] | None = None):
    """Synthetic payment rows for one ISIN: dates step_days apart (+ optional
    per-payment jitter in days)."""
    rows = []
    day = start
    for i, amt in enumerate(amounts):
        j = jitter[i] if jitter else 0
        rows.append({"isin": "F1", "date": (day + datetime.timedelta(days=j)).isoformat(), "net_eur": amt})
        day += datetime.timedelta(days=step_days)
    return rows


@pytest.mark.parametrize(
    "step,expected",
    [
        (30, "monthly"),
        (91, "quarterly"),
        (182, "semiannual"),
        (365, "annual"),
    ],
)
def test_detect_cadence_snaps_to_known_rhythms(step, expected):
    dates = [datetime.date(2025, 1, 1) + datetime.timedelta(days=step * i) for i in range(4)]
    cadence = ds.detect_cadence(dates)
    assert cadence is not None and cadence[2] == expected


def test_detect_cadence_tolerates_jitter():
    # Quarterly with realistic wobble: 85, 96, 89-day gaps.
    dates = [datetime.date(2025, 1, 10), datetime.date(2025, 4, 5), datetime.date(2025, 7, 10), datetime.date(2025, 10, 7)]
    cadence = ds.detect_cadence(dates)
    assert cadence is not None and cadence[0] == "quarterly"


def test_detect_cadence_rejects_irregular_and_single():
    # A 50-day median matches no known rhythm.
    dates = [datetime.date(2025, 1, 1) + datetime.timedelta(days=50 * i) for i in range(4)]
    assert ds.detect_cadence(dates) is None
    assert ds.detect_cadence([datetime.date(2025, 1, 1)]) is None


def test_forecast_rolls_past_dates_forward_to_today():
    # Last real payment 2026-03-25, quarterly: next lands ~24 jun — already
    # past on 17 jul — so the forecast must skip to ~sep, never emit the past.
    dividends = _series(datetime.date(2025, 6, 25), 91, [10.0, 10.0, 10.0, 10.0])
    positions = [_pos("F1", "Fund One", shares=10)]
    fc = ds.forecast_dividends(positions, dividends, today=_TODAY)
    assert fc["upcoming"], "expected a forecast"
    first = fc["upcoming"][0]
    assert first["date"] >= _TODAY.isoformat()
    assert first["month"] == "2026-09"
    assert first["part"] == "late"
    assert first["source"] == "estimate"
    assert first["cadence"] == "quarterly"


def test_forecast_amount_is_median_of_recent_payments():
    # 8.0, 8.4, 8.6, 9.0 -> median of last four = 8.5; the 99 outlier is
    # outside the window entirely.
    dividends = _series(datetime.date(2025, 3, 1), 91, [99.0, 8.0, 8.4, 8.6, 9.0])
    positions = [_pos("F1", "Fund One", shares=10)]
    fc = ds.forecast_dividends(positions, dividends, today=_TODAY)
    assert fc["upcoming"][0]["expected_eur"] == 8.5


def test_forecast_scales_per_share_when_position_grew():
    # 10 shares paid €8 each quarter; the user then doubled to 20 shares —
    # the raw history says €8, the per-share scaling says €16.
    dividends = _series(datetime.date(2025, 9, 1), 91, [8.0, 8.0, 8.0])
    transactions = [
        {"isin": "F1", "date": "2025-01-01", "transaction_type": "BUY", "quantity": 10},
        {"isin": "F1", "date": "2026-04-01", "transaction_type": "BUY", "quantity": 10},
    ]
    positions = [_pos("F1", "Fund One", shares=20)]
    fc = ds.forecast_dividends(positions, dividends, transactions=transactions, today=_TODAY)
    assert fc["upcoming"][0]["expected_eur"] == 16.0


def test_forecast_omits_sold_out_single_payment_and_accumulating():
    dividends = (
        _series(datetime.date(2025, 6, 1), 91, [5.0, 5.0, 5.0])  # F1: sold out
        + [{"isin": "F2", "date": "2026-05-01", "net_eur": 7.0}]  # F2: one payment
    )
    positions = [_pos("F2", "Single", shares=5), _pos("F3", "Accumulating", shares=5)]
    fc = ds.forecast_dividends(positions, dividends, today=_TODAY)
    assert fc["upcoming"] == []
    assert fc["rest_of_year_eur"] == 0.0


def test_forecast_monthly_emits_every_month_and_year_total():
    # Monthly payer (30-day steps), last paid 30 jun: 30 jul, 29 aug, 28 sep,
    # 28 okt, 27 nov and 27 dec remain in 2026 -> 6 * 2.0 = 12.0.
    dividends = _series(datetime.date(2026, 1, 1), 30, [2.0] * 7)
    positions = [_pos("F1", "Monthly", shares=10)]
    fc = ds.forecast_dividends(positions, dividends, today=_TODAY)
    months = [e["month"] for e in fc["upcoming"]]
    assert len(months) >= 6 and len(months) == len(set(months))
    assert fc["rest_of_year_eur"] == 12.0


def _nn_like_dividends():
    """NN Group's real shape: interim (~aug/sep) + final (~may/jun), gaps
    alternating ~270/~75 days — the median matches no single cadence."""
    rows = [
        ("2023-09-26", 9.52),
        ("2024-06-21", 17.68),
        ("2024-08-28", 10.88),
        ("2025-05-28", 18.40),
        ("2025-08-21", 17.59),
        ("2026-06-03", 40.37),
    ]
    return [{"isin": "NN", "date": d, "net_eur": v} for d, v in rows]


def test_alternating_semiannual_payer_is_forecast():
    positions = [_pos("NN", "NN Group", shares=19)]
    fc = ds.forecast_dividends(positions, _nn_like_dividends(), today=_TODAY)
    assert fc["upcoming"], "interim/final payer must not be omitted"
    first = fc["upcoming"][0]
    # Last final 3 jun + the ~76-day interim gap -> mid/late August.
    assert first["month"] == "2026-08"
    assert first["cadence"] == "semiannual"
    assert first["confidence"] == "medium"
    # The amount comes from the *interim* phase (10.88, 17.59 -> median
    # 14.235, rounds to 14.23), never from the fat final that was just paid.
    assert first["expected_eur"] == 14.23
    # The next occurrence after that is the ~may/jun final — next year, so
    # the 2026 rest-of-year total is the interim alone.
    assert fc["rest_of_year_eur"] == 14.23


def test_alternating_detector_needs_at_least_three_gaps():
    # Two gaps cannot show alternation; the detector itself declines, and the
    # holding falls back to the median path (269 & 68 -> median 168.5, within
    # tolerance of semi-annual) — forecast at "medium", not silence.
    events = [(datetime.date.fromisoformat(r["date"]), r["net_eur"]) for r in _nn_like_dividends()[:3]]
    assert ds._detect_alternating(events) is None
    positions = [_pos("NN", "NN Group", shares=19)]
    fc = ds.forecast_dividends(positions, _nn_like_dividends()[:3], today=_TODAY)
    assert fc["upcoming"] and fc["upcoming"][0]["cadence"] == "semiannual"


def test_alternating_rejects_regular_rhythm():
    # Plain quarterly must never be classified as alternating (it is handled
    # by detect_cadence first, and its equal phases fail the >45d split).
    dates = [datetime.date(2025, 1, 1) + datetime.timedelta(days=91 * i) for i in range(5)]
    events = [(d, 5.0) for d in dates]
    assert ds._detect_alternating(events) is None


def test_official_ex_div_overrides_first_estimate_only():
    dividends = _series(datetime.date(2025, 9, 25), 91, [8.0, 8.0, 8.0, 8.0])
    positions = [_pos("F1", "Fund One", shares=10)]
    fc = ds.forecast_dividends(positions, dividends, today=_TODAY)
    assert len(fc["upcoming"]) >= 2
    official = [{"isin": "F1", "name": "Fund One", "ex_date": "2026-08-04", "estimate_eur": None}]
    merged = ds.merge_official_ex_dividends(fc, official)
    first = merged["upcoming"][0]
    assert first["source"] == "official"
    assert first["date"] == "2026-08-04" and first["part"] == "early"
    assert first["expected_eur"] == 8.0  # amount still from history
    assert merged["upcoming"][1]["source"] == "estimate"


def test_official_without_history_still_appears():
    official = [{"isin": "S1", "name": "Stock", "ex_date": "2026-07-30", "estimate_eur": 3.5}]
    merged = ds.merge_official_ex_dividends({"upcoming": [], "rest_of_year_eur": 0.0}, official)
    assert merged["upcoming"][0]["source"] == "official"
    assert merged["upcoming"][0]["expected_eur"] == 3.5


def test_payment_events_sums_same_day_rows():
    rows = [
        {"isin": "F1", "date": "2026-06-01", "net_eur": 6.0},
        {"isin": "F1", "date": "2026-06-01", "net_eur": 6.9},
        {"isin": "F1", "date": "2026-03-01", "net_eur": 5.0},
    ]
    events = ds.payment_events(rows)
    assert events["F1"] == [(datetime.date(2026, 3, 1), 5.0), (datetime.date(2026, 6, 1), 12.9)]


# ---------------------------------------------------------------------------
# Sparkline
# ---------------------------------------------------------------------------
#
# The benchmark-alignment tests next to these went with the dashboard's
# portfolio-vs-MSCI-World card: TWR belongs on the Returns tab, so the
# endpoint that served an index for this screen was deleted rather than left
# lying next to a dashboard that must not grow one.


def test_sparkline_takes_tail_of_last_segment_only():
    old = ([datetime.date(2026, 1, 1)], [500.0], [500.0])
    recent_dates = [datetime.date(2026, 7, d) for d in range(1, 17)]
    recent = (recent_dates, [1000.0 + i for i in range(16)], [0.0] * 16)
    pts = ds.sparkline_points([old, recent], days=31, today=_TODAY)
    assert len(pts) == 16
    assert pts[0]["d"] == "2026-07-01"
    assert pts[-1]["v"] == 1015.0


# ---------------------------------------------------------------------------
# Value history (own portfolio in EUR, feeds the dashboard value card)
# ---------------------------------------------------------------------------


def test_value_history_builds_three_series_without_network():
    # No ticker on the price -> portfolio_history_series never calls yfinance and
    # values every day at the cached price, so this stays deterministic offline.
    # The currency is not decoration: the series only takes EUR-quoted prices
    # now (a quote in another currency used to be summed into a euro total as
    # if it were one), and a stored price row always carries the column.
    txns = [
        {"date": "2026-07-01", "isin": "X1", "quantity": 10.0, "transaction_type": "BUY", "total_eur": 1000.0},
    ]
    prices = {"X1": {"price": 110.0, "currency": "EUR"}}
    out = ds._build_value_history(txns, prices, [{"date": "2026-07-01", "net_eur": 50.0}])
    pts = out["points"]
    assert pts, "expected at least the purchase day onward"
    assert pts[0]["d"] == "2026-07-01"
    assert pts[0]["invested"] == 1000.0
    assert pts[0]["value"] == 1100.0  # 10 shares * €110
    assert pts[0]["value_divs"] == 1150.0  # value + €50 cumulative dividend
    # And it says so: every day of this line is the cached price standing in for
    # a close that was never fetched, which is exactly what the card must not
    # present as measured.
    assert out["estimated"] == [{"isin": "X1", "name": "X1", "base": "huidige koers"}]


def test_value_history_empty_without_transactions():
    assert ds.get_value_history(None, [], {}, []) == {"points": [], "estimated": []}


# ---------------------------------------------------------------------------
# The forward schedule steps in calendar months, not in 30-day blocks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "step,months,expected",
    [
        (30, 1, 12),  # a 30-day step fitted 13 payments into a year
        (91, 3, 4),
        (365, 12, 1),
    ],
)
def test_a_year_of_forecast_holds_a_year_of_payments(step, months, expected):
    """Twelve 30-day steps are 360 days, and the five days left over used to
    take a thirteenth payment — so "next 12 months" read EUR 130 for a fund
    paying EUR 10 a month, and only on some days of the month, which made the
    figure move on its own between two visits.
    """
    today = datetime.date(2026, 8, 4)
    for since in range(0, step, max(step // 12, 1)):
        last = today - datetime.timedelta(days=since)
        divs = [{"isin": "X", "date": (last - datetime.timedelta(days=step * i)).isoformat(), "net_eur": 10.0} for i in range(6)]
        out = ds.forecast_dividends(
            [{"isin": "X", "name": "X", "shares_held": 1.0}],
            divs,
            None,
            today=today,
            horizon_days=365,
        )
        assert len(out["upcoming"]) == expected, f"{months}-month cadence, {since} days on"


def test_an_estimate_keeps_the_day_of_the_month_the_fund_pays_on():
    """A 30-day step walked a payer of the 31st five days earlier every year."""
    today = datetime.date(2026, 8, 4)
    divs = [{"isin": "X", "date": d, "net_eur": 10.0} for d in ("2026-04-30", "2026-05-31", "2026-06-30", "2026-07-31")]
    out = ds.forecast_dividends(
        [{"isin": "X", "name": "X", "shares_held": 1.0}],
        divs,
        None,
        today=today,
        horizon_days=200,
    )
    # The 200-day horizon ends 2027-02-20, so January is the last one in.
    assert [e["date"] for e in out["upcoming"]] == [
        "2026-08-31",
        "2026-09-30",
        "2026-10-31",
        "2026-11-30",
        "2026-12-31",
        "2027-01-31",
    ]


def test_add_months_clamps_to_the_length_of_the_month():
    assert ds._add_months(datetime.date(2026, 1, 31), 1) == datetime.date(2026, 2, 28)
    assert ds._add_months(datetime.date(2024, 1, 31), 1) == datetime.date(2024, 2, 29)
    assert ds._add_months(datetime.date(2026, 12, 31), 1) == datetime.date(2027, 1, 31)
    assert ds._add_months(datetime.date(2026, 11, 30), 1) == datetime.date(2026, 12, 30)


# ---------------------------------------------------------------------------
# The ex-dividend calendar sweep
#
# A serial loop over every position, on the request thread of
# /api/dashboard/dividends, calling yf.Ticker().calendar — which takes ~30s to
# give up when the network stalls, because yfinance's cookie bootstrap ignores
# the timeout it is handed. Twenty holdings was ten minutes of a spinning tab
# for a card that is usually empty anyway (Yahoo carries no forward data for
# UCITS ETFs, which is why the estimate exists).
#
# Watched fail first (rule 3): the budget test passes on the pre-fix loop only
# by running the full ten minutes, and the raise test passes there with a
# twelve-hour cached emptiness — the outage outliving itself.
# ---------------------------------------------------------------------------


def test_the_calendar_sweep_stops_at_its_budget(monkeypatch):
    import time as _time

    real_sleep = _time.sleep
    seen = []

    class _SlowTicker:
        def __init__(self, symbol):
            seen.append(symbol)
            real_sleep(0.03)

        @property
        def calendar(self):
            return {"Ex-Dividend Date": datetime.date(2026, 9, 1)}

    monkeypatch.setattr("yfinance.Ticker", _SlowTicker)
    meta = {f"T{i}.AS": (f"NL{i}", f"Fund {i}") for i in range(6)}

    entries = ds._fetch_calendar(meta, budget_seconds=0.05)

    assert len(seen) < 6  # cut off rather than run to the end
    assert len(entries) == len(seen)  # and what it did find is kept


def test_a_cut_off_sweep_that_found_nothing_still_raises(monkeypatch):
    """So get_or_fetch cannot pin an empty calendar for twelve hours.

    The guard used to compare the error count against the size of the whole
    dict. With a budget in front of it that no longer holds — a stalled network
    gets through one ticker before the cut-off — so an empty list would have
    been cached as a real answer.
    """

    class _DeadTicker:
        def __init__(self, symbol):
            raise RuntimeError("no route to host")

    monkeypatch.setattr("yfinance.Ticker", _DeadTicker)
    meta = {f"T{i}.AS": (f"NL{i}", f"Fund {i}") for i in range(6)}

    with pytest.raises(RuntimeError):
        ds._fetch_calendar(meta, budget_seconds=0.0)


def test_a_sweep_that_found_something_does_not_raise(monkeypatch):
    class _Ticker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def calendar(self):
            if self.symbol == "T0.AS":
                return {"Ex-Dividend Date": datetime.date(2026, 9, 1)}
            raise RuntimeError("no route to host")

    monkeypatch.setattr("yfinance.Ticker", _Ticker)
    meta = {"T0.AS": ("NL0", "Fund 0"), "T1.AS": ("NL1", "Fund 1")}

    assert len(ds._fetch_calendar(meta)) == 1


def test_a_sweep_that_found_no_dates_is_a_real_answer(monkeypatch):
    """Nothing *found* is cacheable; nothing *attempted* is not.

    Almost every UCITS ETF has no forward calendar on Yahoo, so an empty list
    is the normal answer here and must not be mistaken for a failure.
    """

    class _EmptyTicker:
        def __init__(self, symbol):
            pass

        @property
        def calendar(self):
            return {}

    monkeypatch.setattr("yfinance.Ticker", _EmptyTicker)
    meta = {"T0.AS": ("NL0", "Fund 0"), "T1.AS": ("NL1", "Fund 1")}

    assert ds._fetch_calendar(meta) == []
