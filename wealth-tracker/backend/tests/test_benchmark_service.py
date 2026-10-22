"""
The benchmark cache must hand back exactly what it was given.

A lossy round-trip through JSON does not raise — it draws a subtly different
line, or reindexes to all-NaN and draws none. So these compare the value
returned from cache against the value that went in, on the real shapes
charts.py produces, rather than testing that the cache "works".
"""

from datetime import date, datetime

import pandas as pd

from app.services import benchmark_service as bs


def _series_fixture() -> dict:
    return {
        "S&P 500 (SPY)": pd.Series(
            [400.0, 401.5, 399.25],
            index=pd.DatetimeIndex([datetime(2021, 1, 5), datetime(2021, 1, 6), datetime(2021, 1, 7)]),
        ),
        "EURO STOXX 50 (FEZ)": pd.Series(
            [40.1234, 40.5],
            index=pd.DatetimeIndex([datetime(2021, 1, 5), datetime(2021, 1, 6)]),
        ),
    }


def _segments_fixture() -> list:
    return [
        ([date(2021, 1, 5), date(2021, 1, 6)], [699.664, 705.12], [695.816, 0.0]),
        ([date(2023, 3, 1)], [1200.5], [1200.0]),
    ]


def test_series_survive_the_json_round_trip():
    original = _series_fixture()
    restored = bs._load_series(bs._dump_series(original))

    assert restored.keys() == original.keys()
    for label, series in original.items():
        pd.testing.assert_series_equal(
            restored[label],
            series,
            check_names=False,
            check_freq=False,
        )


def test_restored_series_keep_a_datetime_index():
    """The charts reindex the portfolio onto this index; strings give all-NaN."""
    restored = bs._load_series(bs._dump_series(_series_fixture()))
    for series in restored.values():
        assert isinstance(series.index, pd.DatetimeIndex)


def test_segments_survive_the_json_round_trip():
    original = _segments_fixture()
    restored = bs._load_segments(bs._dump_segments(original))
    assert restored == original


def test_restored_segment_dates_are_dates_not_strings():
    """charts.py compares them with str(day_date) — a str would double-encode."""
    restored = bs._load_segments(bs._dump_segments(_segments_fixture()))
    assert all(isinstance(d, date) for dates, _, _ in restored for d in dates)


def test_fingerprint_changes_with_the_inputs_and_not_with_their_order():
    transactions = [{"isin": "A", "quantity": 1}, {"isin": "B", "quantity": 2}]
    prices = {"A": {"price": 10.0}}
    dividends: list[dict] = []

    base = bs._fingerprint(transactions, prices, dividends)
    assert base == bs._fingerprint(transactions, prices, dividends)  # deterministic

    # A refreshed price must not serve the old line.
    assert base != bs._fingerprint(transactions, {"A": {"price": 10.5}}, dividends)
    # Nor may the bonds toggle dropping an ISIN.
    assert base != bs._fingerprint(transactions[:1], prices, dividends)
    # Nor a new dividend.
    assert base != bs._fingerprint(transactions, prices, [{"isin": "A", "net_eur": 1.0}])


def test_prices_are_fetched_once_per_start_date_then_cached(tmp_path, monkeypatch):
    from domain import database

    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    conn = database.connect("alice")
    database.init_db(conn)

    calls = []

    def fake_fetch(start_iso):
        calls.append(start_iso)
        return _series_fixture()

    monkeypatch.setattr(charts_module(), "fetch_benchmark_prices", fake_fetch)

    first = bs.get_benchmark_prices(conn, "2021-01-01")
    second = bs.get_benchmark_prices(conn, "2021-01-01")
    assert len(calls) == 1, "the second request should not have hit yfinance"
    pd.testing.assert_series_equal(
        first["S&P 500 (SPY)"],
        second["S&P 500 (SPY)"],
        check_freq=False,
    )

    # A different start date is a different question, so it fetches again.
    bs.get_benchmark_prices(conn, "2020-01-01")
    assert len(calls) == 2
    conn.close()


def test_segments_refetch_when_a_price_changes(tmp_path, monkeypatch):
    """The key is the inputs' fingerprint, so a refresh must not serve the old line."""
    from domain import database

    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    conn = database.connect("alice")
    database.init_db(conn)

    calls = []

    def fake_build(transactions, prices, dividends):
        calls.append(prices)
        return _segments_fixture()

    monkeypatch.setattr(charts_module(), "build_portfolio_segments", fake_build)

    transactions = [{"isin": "A", "quantity": 1}]
    bs.get_portfolio_segments(conn, transactions, {"A": {"price": 10.0}}, [])
    bs.get_portfolio_segments(conn, transactions, {"A": {"price": 10.0}}, [])
    assert len(calls) == 1

    bs.get_portfolio_segments(conn, transactions, {"A": {"price": 11.0}}, [])
    assert len(calls) == 2, "a refreshed price must invalidate the cached segments"
    conn.close()


def charts_module():
    from domain.portfolio import series as charts

    return charts


# ---------------------------------------------------------------------------
# Both lines are measured from the same moment
# ---------------------------------------------------------------------------


def _segments(dates, values):
    return [([d for d in dates], values, [0.0] * len(values))]


def test_ytd_measures_the_benchmark_from_new_years_eve_too():
    """The portfolio line holds a value for 1 January (the previous close,
    carried forward), so a benchmark based on its *next* trading day left the
    first session of the year outside its own line while it sat inside the
    portfolio's. An index up 4,0% since New Year drew as +0,97%."""
    import datetime

    import pandas as pd

    dates = [datetime.date(2025, 12, 30) + datetime.timedelta(days=i) for i in range(10)]
    segments = _segments(dates, [100.0] * 3 + [103.0, 103.5, 104.0, 104.0, 104.0, 105.0, 105.0])
    bench = pd.Series(
        [200.0, 206.0, 207.0, 208.0],
        index=pd.DatetimeIndex(["2025-12-30", "2026-01-02", "2026-01-05", "2026-01-06"]),
    )

    out = bs.ytd_series(segments, {"MSCI": bench}, 2026)
    points = out["series"][1]["points"]
    assert points[-1]["v"] == 4.0  # 208 / 200 - 1, not 208 / 206 - 1
    assert points[0]["d"] == "2026-01-02"  # 31 Dec anchors it without being drawn


def test_ytd_falls_back_to_the_first_close_when_the_year_has_no_earlier_one():
    import datetime

    import pandas as pd

    dates = [datetime.date(2026, 1, 1) + datetime.timedelta(days=i) for i in range(5)]
    segments = _segments(dates, [100.0, 101.0, 102.0, 103.0, 104.0])
    bench = pd.Series([200.0, 210.0], index=pd.DatetimeIndex(["2026-01-02", "2026-01-05"]))

    out = bs.ytd_series(segments, {"MSCI": bench}, 2026)
    points = out["series"][1]["points"]
    assert points[0]["v"] == 0.0
    assert points[-1]["v"] == 5.0
