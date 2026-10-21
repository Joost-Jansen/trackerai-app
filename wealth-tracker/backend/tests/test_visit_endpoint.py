"""POST /api/dashboard/visit — the wiring, not the arithmetic.

test_visit_alignment.py pins what align_visit_with_the_day decides. This file
covers the thing only the route can get wrong, and once did: *whether it asks*.
The route used to hand the alignment only visits from an earlier calendar day,
so a second look on the same morning fell through to its own snapshot and the
strip contradicted the chip above it — a rule that held in the function and
broke in the caller, with no test between them to notice.
"""

import datetime
import io

import pandas as pd
import pytest

from app.services import dashboard_service  # also puts the repo root on sys.path

ISIN = "IE00B4L5Y983"

#: The cache the chip reads: 10 shares that closed at 100 and now stand at 110,
#: so "today" is +100,00 exactly.
PREV_CLOSE, PRICE, SHARES = 100.0, 110.0, 10
CHIP_DELTA = round((PRICE - PREV_CLOSE) * SHARES, 2)


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _upload_a_position(client):
    """One buy, so the portfolio has a position to price."""
    value = -(SHARES * 80.0)
    rows = [
        {
            "Datum": "05-01-2026",
            "Tijd": "09:30",
            "Product": "iShares Core MSCI World",
            "ISIN": ISIN,
            "Beurs": "EAM",
            "Uitvoeringsplaats": "EAM",
            "Aantal": SHARES,
            "Koers": 80.0,
            "Lokale waarde": value,
            "Waarde": value,
            "Wisselkoers": 1.0,
            "Transactiekosten": -1.0,
            "Totaal": value - 1.0,
            "Order Id": "order-1",
        }
    ]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False)
    resp = client.post(
        "/api/uploads/transactions",
        files={"files": ("tx.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text


def _seed(previous_visit_at: str, value_then: float):
    """The price cache and the visit row this test reasons about.

    Written straight to alice's database: the upload above cannot supply
    prices (refresh_all_prices needs the network) and the visit row has to
    carry a timestamp of this test's choosing.
    """
    from domain import database

    conn = database.connect("alice")
    database.init_db(conn)
    database.save_price(conn, ISIN, "iShares Core MSCI World", "IWDA.AS", PRICE, "EUR", previous_close=PREV_CLOSE)
    conn.execute("DELETE FROM visit_snapshots")
    conn.commit()
    database.insert_visit(conn, previous_visit_at, value_then)
    conn.close()


#: The moment these tests pretend it is: today, early afternoon. Every visit
#: they plant is placed relative to this, never to the real clock — see `bars`.
NOW = datetime.time(13, 0)


@pytest.fixture()
def bars(monkeypatch):
    """Yesterday's close at 17:25 and today's open at 09:00, as the series
    delivers them: tz-aware UTC, the previous close prepended as point one.

    Also stops the clock at 13:00, because these tests planted visits at fixed
    times of day and then let record_visit compare them against the real one.
    Whether a planted visit counts as a *previous* visit is exactly that
    comparison: anything under half an hour old is the same session, and has
    nothing to report. So "today at 11:00" was a previous visit after 11:30 and
    a visit from the future before it — and the suite went red every night and
    green again mid-morning, on nothing. A test that depends on the hour is
    worse than no test: the next time it is red, nobody knows whether the app
    broke or the clock did.

    record_visit is the only thing in this route that reads the time, so
    pinning its `now` is the whole fix; the route passes it positionally, hence
    the wrapper rather than a partial.
    """
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    def _fake_intraday(conn, transactions, prices, positions=None):
        return {
            "points": [
                {"d": f"{yesterday.isoformat()}T15:25+00:00", "value": 1000.0},
                {"d": f"{today.isoformat()}T07:00+00:00", "value": 1005.0},
                {"d": f"{today.isoformat()}T07:05+00:00", "value": 1010.0},
            ],
            "prev_close": 1000.0,
        }

    record_visit = dashboard_service.record_visit
    monkeypatch.setattr(
        dashboard_service,
        "record_visit",
        lambda conn, total_value, **kw: record_visit(conn, total_value, now=datetime.datetime.combine(today, NOW), **kw),
    )
    monkeypatch.setattr(dashboard_service, "get_intraday", _fake_intraday)
    return today, yesterday


def _visit(client):
    resp = client.post("/api/dashboard/visit")
    assert resp.status_code == 200, resp.text
    return resp.json()["since"]


def test_a_visit_earlier_this_morning_follows_the_chip(client, bars):
    """The regression: 08:05 and back at lunch is one session apart.

    08:05 is before the 09:00 open, so this visit saw a shut market."""
    today, _ = bars
    _login(client)
    _upload_a_position(client)
    # The snapshot the cache had at 08:05 — the documented €4,90 away from the
    # chip's own baseline, which is what made the two figures disagree.
    _seed(f"{today.isoformat()}T08:05:00", value_then=1095.10)

    assert _visit(client)["value_delta"] == CHIP_DELTA


def test_a_visit_last_night_follows_the_chip(client, bars):
    """Unchanged behaviour, and the reason the calendar gate looked right."""
    _, yesterday = bars
    _login(client)
    _upload_a_position(client)
    _seed(f"{yesterday.isoformat()}T22:57:42", value_then=1095.10)

    assert _visit(client)["value_delta"] == CHIP_DELTA


def test_a_visit_from_during_the_session_keeps_its_own_snapshot(client, bars):
    """Half a session is not a day: here the strip must report what it saw.

    11:00 is after the 09:00 open and two hours before NOW — a previous visit
    by any measure, and one with only half a session behind it."""
    today, _ = bars
    _login(client)
    _upload_a_position(client)
    _seed(f"{today.isoformat()}T11:00:00", value_then=1095.10)

    # 10 x 110 = 1100 now, against the 1095,10 the strip recorded at 11:00.
    assert _visit(client)["value_delta"] == 4.90


def test_the_first_ever_visit_has_nothing_to_diff(client, bars):
    _login(client)
    _upload_a_position(client)
    assert _visit(client) is None
