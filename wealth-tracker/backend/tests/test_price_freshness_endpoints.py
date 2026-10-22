"""What the API says about how current its prices are.

Two lies lived here. POST /api/prices/refresh answered with the size of the
whole price cache, so a round in which Yahoo returned nothing still came back
with a full count and the sheet went green over it. And both freshness lines
were built on max(fetched_at) — the most flattering reading available — so one
ISIN that happened to refresh made a portfolio days behind read "just now".

Watched fail first (rule 3): each assertion below passes on the pre-fix code
with exactly the number that made it wrong.
"""

import datetime

from domain import database
from domain.portfolio import positions as portfolio


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _seed(username, tmp_path, isins, fetched_at=None):
    """Put priced positions in a user's own database, bypassing the network."""
    conn = database.connect(username)
    database.init_db(conn)
    database.save_transactions(
        conn,
        [
            {
                "date": "2025-01-02",
                "time": "10:00",
                "isin": isin,
                "name": f"Fund {i}",
                "transaction_type": "BUY",
                "quantity": 10.0,
                "price": 100.0,
                "total_eur": 1000.0,
                "order_ref": f"o{i}",
                "currency": "EUR",
                "exchange": "EAM",
                "transaction_fee": 1.0,
                "autofx_cost": 0.0,
            }
            for i, isin in enumerate(isins)
        ],
    )
    for i, isin in enumerate(isins):
        conn.execute(
            "INSERT OR REPLACE INTO prices (isin, name, ticker, price, currency, fetched_at, previous_close) VALUES (?,?,?,?,?,?,?)",
            (isin, f"Fund {i}", f"T{i}.AS", 110.0, "EUR", (fetched_at or {}).get(isin, "2026-08-07 09:00:00"), 100.0),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# POST /api/prices/refresh
# ---------------------------------------------------------------------------


def test_refresh_reports_zero_when_every_fetch_failed(client, tmp_path, monkeypatch):
    _login(client)
    _seed("alice", tmp_path, ["NL0000001", "NL0000002"])

    monkeypatch.setattr(portfolio, "fetch_price_for_isin", lambda *a, **k: None)
    monkeypatch.setattr(portfolio.time, "sleep", lambda _s: None)

    body = client.post("/api/prices/refresh").json()

    # Pre-fix: updated_count was 2 — the size of the cache that did not move.
    assert body["updated_count"] == 0
    assert body["complete"] is False
    assert {f["isin"] for f in body["failed"]} == {"NL0000001", "NL0000002"}


def test_refresh_reports_a_partial_round(client, tmp_path, monkeypatch):
    _login(client)
    _seed("alice", tmp_path, ["NL0000001", "NL0000002"])

    def _fetch(conn_, isin, name, **kwargs):
        if isin == "NL0000001":
            return {"ticker": "T0.AS", "price": 120.0, "currency": "EUR", "previous_close": 100.0}
        return None

    monkeypatch.setattr(portfolio, "fetch_price_for_isin", _fetch)
    monkeypatch.setattr(portfolio.time, "sleep", lambda _s: None)

    body = client.post("/api/prices/refresh").json()

    assert body["updated_count"] == 1
    assert body["complete"] is False
    assert [f["isin"] for f in body["failed"]] == ["NL0000002"]


def test_refresh_reports_a_clean_round(client, tmp_path, monkeypatch):
    _login(client)
    _seed("alice", tmp_path, ["NL0000001"])

    monkeypatch.setattr(
        portfolio,
        "fetch_price_for_isin",
        lambda *a, **k: {"ticker": "T0.AS", "price": 120.0, "currency": "EUR", "previous_close": 100.0},
    )
    monkeypatch.setattr(portfolio.time, "sleep", lambda _s: None)

    body = client.post("/api/prices/refresh").json()

    # No position on Tradegate here, so its own counts are zero and do not
    # affect `complete`, which is Yahoo's round.
    assert body == {"updated_count": 1, "failed": [], "skipped": 0, "complete": True, "venue_refreshed": 0, "venue_failed": 0}


# ---------------------------------------------------------------------------
# The freshness lines
# ---------------------------------------------------------------------------

_OLD = "2026-08-01 09:00:00"
_NEW = "2026-08-07 09:00:00"


def test_status_reports_the_oldest_quote_beside_the_newest(client, tmp_path):
    _login(client)
    _seed("alice", tmp_path, ["NL0000001", "NL0000002"], fetched_at={"NL0000001": _OLD, "NL0000002": _NEW})

    body = client.get("/api/prices/status").json()

    # The sheet's line is built on the oldest; the newest stays available so a
    # partly-failed refresh can show the gap between the two.
    assert body["oldest_price"] == _OLD
    assert body["last_updated"] == _NEW


def test_dashboard_summary_reports_the_oldest_quote(client, tmp_path):
    _login(client)
    _seed("alice", tmp_path, ["NL0000001", "NL0000002"], fetched_at={"NL0000001": _OLD, "NL0000002": _NEW})

    body = client.get("/api/dashboard/summary").json()

    assert body["oldest_price_fetch"] == _OLD
    assert body["latest_price_fetch"] == _NEW
    # And the day chip carries the same oldest quote, so the hero cannot call a
    # week-old move "today".
    assert body["day"]["as_of"] == _OLD
    assert body["day"]["stale"] is True


def test_holdings_overview_reports_the_oldest_quote(client, tmp_path):
    _login(client)
    _seed("alice", tmp_path, ["NL0000001", "NL0000002"], fetched_at={"NL0000001": _OLD, "NL0000002": _NEW})

    body = client.get("/api/holdings/overview").json()

    assert body["oldest_price_fetch"] == _OLD
    assert body["latest_price_fetch"] == _NEW
    # The two tabs share portfolio_day_change, so they cannot disagree here.
    assert body["totals"]["day"]["stale"] is True


def test_a_current_cache_is_not_marked_stale(client, tmp_path):
    _login(client)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _seed("alice", tmp_path, ["NL0000001"], fetched_at={"NL0000001": now})

    body = client.get("/api/dashboard/summary").json()

    assert body["day"]["stale"] is False
