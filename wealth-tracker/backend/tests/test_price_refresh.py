"""The background price refresh — when it runs, and that it cannot take the
process with it.

Its reason to exist is upstream of every "today" in this app: chip, 1D chart
and visit strip all measure against the price cache, so how old that cache is
is how wrong the day is. Nothing kept it current before this.

Watched fail first (rule 3): by dropping the weekend check, by letting one
account's exception out of the loop, and by starting the thread without the
environment switch.
"""

import datetime

import pytest

from app.core import price_refresh as pr


# ---------------------------------------------------------------------------
# When it bothers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("when, expected", [
    # Wednesday 5 August 2026.
    ((2026, 8, 5, 9, 30), True),      # mid-morning
    ((2026, 8, 5, 8, 55), True),      # five minutes before the Amsterdam open
    ((2026, 8, 5, 17, 45), True),     # after the close, for the closing print
    ((2026, 8, 5, 22, 20), True),     # Tradegate's last minutes
    ((2026, 8, 5, 8, 54), False),     # a minute too early
    ((2026, 8, 5, 22, 21), False),    # everything is shut
    ((2026, 8, 5, 3, 0), False),      # the night: the same close, re-fetched
    ((2026, 8, 8, 11, 0), False),     # Saturday
    ((2026, 8, 9, 11, 0), False),     # Sunday
])
def test_the_window_is_market_hours_on_weekdays(when, expected):
    assert pr.is_market_window(datetime.datetime(*when)) is expected


# ---------------------------------------------------------------------------
# Whether a stored quote has gone stale
#
# Not an age in hours, which is the obvious wrong answer: Friday's close is the
# right number to show all weekend — it is what Monday is measured from, and
# the refresh window deliberately lets it stand overnight. The question is
# whether a session has *closed* since the quote was fetched.
#
# Watched fail first by comparing against a flat 24 hours, which marks every
# Sunday stale, and by comparing against "today", which marks Monday morning
# stale before the market has opened.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("now, expected_close", [
    # Wednesday 5 August 2026, before that day's close -> Tuesday's close.
    ((2026, 8, 5, 11, 0), (2026, 8, 4, 22, 20)),
    # Wednesday evening, after it -> today's own close.
    ((2026, 8, 5, 23, 0), (2026, 8, 5, 22, 20)),
    # Saturday and Sunday both look back to Friday.
    ((2026, 8, 8, 11, 0), (2026, 8, 7, 22, 20)),
    ((2026, 8, 9, 20, 0), (2026, 8, 7, 22, 20)),
    # Monday morning, before the open -> still Friday's.
    ((2026, 8, 10, 9, 0), (2026, 8, 7, 22, 20)),
])
def test_last_close_passed(now, expected_close):
    assert pr.last_close_passed(datetime.datetime(*now)) == datetime.datetime(*expected_close)


@pytest.mark.parametrize("fetched, now, stale", [
    # Friday's closing print, read on Sunday: exactly what should be on screen.
    ("2026-08-07T22:25:00", (2026, 8, 9, 12, 0), False),
    # The same quote on Tuesday afternoon: Monday's close came and went, so two
    # refreshes have silently failed.
    ("2026-08-07T22:25:00", (2026, 8, 11, 15, 0), True),
    # Fetched this morning, read this afternoon.
    ("2026-08-05T09:10:00", (2026, 8, 5, 15, 0), False),
    # Yesterday evening, read before today's close.
    ("2026-08-04T22:25:00", (2026, 8, 5, 15, 0), False),
])
def test_is_stale_asks_whether_a_close_was_missed(fetched, now, stale):
    assert pr.is_stale(fetched, datetime.datetime(*now)) is stale


@pytest.mark.parametrize("value", [None, "", "not a timestamp"])
def test_unreadable_timestamps_count_as_stale(value):
    """A timestamp nobody can parse is not evidence of freshness."""
    assert pr.is_stale(value) is True


# ---------------------------------------------------------------------------
# What one pass does
# ---------------------------------------------------------------------------

def test_every_account_is_refreshed_in_its_own_database(monkeypatch, tmp_path):
    from domain import database

    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    monkeypatch.setattr(pr, "_usernames", lambda: ["alice", "bob"])

    seen = []
    result = pr.portfolio.RefreshResult(refreshed=1, failed=[])
    monkeypatch.setattr(pr.portfolio, "refresh_all_prices",
                        lambda conn: seen.append(conn) or result)

    assert pr.refresh_every_user() == {"alice": result, "bob": result}
    # Two connections, not one shared handle: each user's prices live in that
    # user's own file and nothing here may cross that line.
    assert len(seen) == 2
    assert seen[0] is not seen[1]


def test_one_broken_account_does_not_stop_the_others(monkeypatch, tmp_path, capsys):
    from domain import database

    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    monkeypatch.setattr(pr, "_usernames", lambda: ["alice", "bob"])

    def _refresh(conn):
        if not hasattr(_refresh, "called"):
            _refresh.called = True
            raise RuntimeError("yahoo said no")
        return pr.portfolio.RefreshResult(refreshed=2, failed=[])

    monkeypatch.setattr(pr.portfolio, "refresh_all_prices", _refresh)

    # The first account raises; the second is still refreshed, and the failure
    # is on stdout rather than in a traceback that kills the loop.
    assert pr.refresh_every_user() == {
        "bob": pr.portfolio.RefreshResult(refreshed=2, failed=[])
    }
    assert "yahoo said no" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------

def test_it_stays_off_unless_the_environment_asks_for_it(monkeypatch):
    monkeypatch.delenv("PRICE_REFRESH", raising=False)
    assert pr.start() is False
    assert pr._thread is None or not pr._thread.is_alive()


def test_it_starts_once_and_stops_cleanly(monkeypatch):
    monkeypatch.setenv("PRICE_REFRESH", "on")
    monkeypatch.setattr(pr, "is_market_window", lambda now=None: False)
    try:
        assert pr.start() is True
        assert pr.start() is False       # already running, not a second thread
        assert pr._thread.daemon         # never keeps the process alive
    finally:
        pr.stop()
        pr._thread.join(timeout=5)
    assert not pr._thread.is_alive()


# ---------------------------------------------------------------------------
# Reporting a position that cannot be priced
# ---------------------------------------------------------------------------
#
# The failure this exists for is silent by construction: an unpriced holding
# shows "—", sits out every total, and says so only in grey text on its owner's
# own screen. Nobody who can fix it is looking at that screen.

def _buy(isin="X1", name="Fund X", qty=10.0, price=100.0):
    return {
        "isin": isin, "name": name, "date": "2026-01-05", "time": "09:30",
        "transaction_type": "BUY", "quantity": qty, "price": price,
        "value_eur": -qty * price, "total_eur": -qty * price - 2.0,
        "transaction_fee": -2.0, "autofx_cost": None, "exchange": "NSY",
    }


@pytest.fixture()
def user_conn(tmp_path, monkeypatch):
    from domain import database

    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    conn = database.connect("rene")
    database.init_db(conn)
    yield conn
    conn.close()


def test_a_holding_without_a_price_is_reported(user_conn, monkeypatch):
    from domain import database

    database.save_transactions(user_conn, [_buy()])
    monkeypatch.setenv("NTFY_TOPIC_URL", "https://ntfy.example/topic")
    pushed = []
    monkeypatch.setattr(pr.notify, "push", lambda title, message, **k: pushed.append((title, message)) or True)

    assert pr._alert_unpriced(user_conn, "rene") == 1
    title, message = pushed[0]
    assert "without a price" in title
    assert "X1" in message and "rene" in message


def test_a_priced_holding_is_not_reported(user_conn, monkeypatch):
    from domain import database

    database.save_transactions(user_conn, [_buy()])
    database.save_price(user_conn, isin="X1", name="Fund X", ticker="X1.AS",
                        price=110.0, currency="EUR")
    monkeypatch.setenv("NTFY_TOPIC_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(pr.notify, "push", lambda *a, **k: True)

    assert pr._alert_unpriced(user_conn, "rene") == 0


def test_a_price_in_the_wrong_currency_counts_as_unpriced(user_conn, monkeypatch):
    """A USD price cannot be added to a EUR cost basis, so the position still
    sits out the totals — the user sees the same "—" either way."""
    from domain import database

    database.save_transactions(user_conn, [_buy()])
    database.save_price(user_conn, isin="X1", name="Fund X", ticker="X1",
                        price=110.0, currency="USD")
    monkeypatch.setenv("NTFY_TOPIC_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(pr.notify, "push", lambda *a, **k: True)

    assert pr._alert_unpriced(user_conn, "rene") == 1


def test_the_same_position_is_not_reported_every_five_minutes(user_conn, monkeypatch):
    from domain import database

    database.save_transactions(user_conn, [_buy()])
    monkeypatch.setenv("NTFY_TOPIC_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(pr.notify, "push", lambda *a, **k: True)

    assert pr._alert_unpriced(user_conn, "rene") == 1
    assert pr._alert_unpriced(user_conn, "rene") == 0    # still broken, still quiet


def test_a_failed_push_postpones_the_warning_instead_of_losing_it(user_conn, monkeypatch):
    from domain import database

    database.save_transactions(user_conn, [_buy()])
    monkeypatch.setenv("NTFY_TOPIC_URL", "https://ntfy.example/topic")
    monkeypatch.setattr(pr.notify, "push", lambda *a, **k: False)

    assert pr._alert_unpriced(user_conn, "rene") == 0
    # Marking it sent on a failed push would bury it for a week.
    monkeypatch.setattr(pr.notify, "push", lambda *a, **k: True)
    assert pr._alert_unpriced(user_conn, "rene") == 1


def test_no_topic_configured_means_no_work_at_all(user_conn, monkeypatch):
    from domain import database

    database.save_transactions(user_conn, [_buy()])
    monkeypatch.delenv("NTFY_TOPIC_URL", raising=False)
    monkeypatch.setattr(pr.notify, "push", lambda *a, **k: pytest.fail("must not push"))

    assert pr._alert_unpriced(user_conn, "rene") == 0
