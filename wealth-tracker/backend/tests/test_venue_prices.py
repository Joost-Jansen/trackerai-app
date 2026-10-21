"""The price per position: Tradegate's last trade for a TDG row, Yahoo for the
rest — and a per-ISIN price that adds up to exactly those rows.

The invariant everything here protects: the dashboard, the day chip and the
charts compute per ISIN; the Portfolio tab computes per position. Once two
positions of one fund carry two prices, those two views only agree if the
per-ISIN price is the share-weighted blend of the two.
"""

import datetime

import pytest

from app.services import dashboard_service, tradegate_service
from app.services import holdings_service as hs
from app.services import venue_price_service as vps
from app.services.portfolio_service import PortfolioBundle
from domain import database
from domain.portfolio import positions as portfolio

ISIN = "IE00B4L5YC18"
NOW = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
LONG_AGO = "2026-01-02 12:00:00"


def _tx(kind="BUY", qty=10.0, price=50.0, date="2026-01-05", time="09:30", isin=ISIN, exchange="TDG"):
    value = -(qty * price) if kind == "BUY" else qty * price
    return {
        "isin": isin,
        "name": "iShares MSCI EM",
        "date": date,
        "time": time,
        "transaction_type": kind,
        "quantity": qty,
        "price": price,
        "value_eur": value,
        "total_eur": value - 1.0,
        "transaction_fee": -1.0,
        "autofx_cost": None,
        "exchange": exchange,
    }


def _yahoo(price=55.15, prev=56.0, fetched=NOW, ticker="EUNM.DE"):
    return {
        ISIN: {
            "isin": ISIN,
            "name": "iShares MSCI EM",
            "ticker": ticker,
            "price": price,
            "previous_close": prev,
            "currency": "EUR",
            "fetched_at": fetched,
        }
    }


def _tdg(price=55.398, prev=56.304, fetched=NOW):
    return {
        (ISIN, "TDG"): {
            "isin": ISIN,
            "venue": "TDG",
            "price": price,
            "previous_close": prev,
            "currency": "EUR",
            "source": "tradegate",
            "fetched_at": fetched,
        }
    }


def _bundle(transactions, yahoo, venue):
    prices = vps.effective_prices(transactions, yahoo, venue)
    positions = portfolio.calculate_positions(transactions, prices)
    return PortfolioBundle(
        prices=prices,
        transactions=transactions,
        dividends=[],
        dividends_by_isin={},
        positions=positions,
        summary=portfolio.calculate_portfolio_summary(positions, transactions, []),
        venue_prices=venue,
        yahoo_prices=yahoo,
    )


TWO_VENUES = [_tx(qty=10, exchange="EAM"), _tx(qty=5, exchange="TDG", date="2026-02-01")]


# ---------------------------------------------------------------------------
# Which price a position gets
# ---------------------------------------------------------------------------


def test_shares_per_venue_match_the_holdings_walk():
    txs = [
        _tx(qty=10, exchange="EAM"),
        _tx(qty=4, exchange="TDG", date="2026-02-01"),
        _tx("SELL", qty=3, exchange="EAM", date="2026-03-01"),
        _tx(qty=2, exchange=None, isin="NL0010773842"),
        _tx("SELL", qty=4, exchange="TDG", date="2026-04-01"),  # TDG closed
    ]
    expected = {key: round(b["shares"], 6) for key, b in hs.cost_breakdown_by_venue(txs).items() if b["shares"] > 0.0001}
    assert {k: round(v, 6) for k, v in vps.open_shares_by_venue(txs).items()} == expected


def test_each_position_gets_its_own_exchanges_price():
    rows = {r["exchange"]: r for r in hs.holdings_rows(_bundle(TWO_VENUES, _yahoo(), _tdg()))}

    assert rows["TDG"]["current_price"] == 55.398
    assert rows["TDG"]["price_provider"] == "tradegate"
    assert rows["TDG"]["current_value"] == round(5 * 55.398, 2)
    assert rows["TDG"]["previous_close"] == 56.304

    assert rows["EAM"]["current_price"] == 55.15
    assert rows["EAM"]["price_provider"] == "yahoo"
    # Both rows keep the Yahoo symbol the chart is drawn from.
    assert rows["TDG"]["ticker"] == rows["EAM"]["ticker"] == "EUNM.DE"


def test_the_per_isin_figures_add_up_to_the_positions():
    bundle = _bundle(TWO_VENUES, _yahoo(), _tdg())
    rows = hs.holdings_rows(bundle)

    assert bundle.positions[0]["current_value"] == pytest.approx(sum(r["current_value"] for r in rows), abs=0.011)

    chip = dashboard_service.portfolio_day_change(bundle.positions, bundle.prices)
    assert chip["delta_eur"] == pytest.approx(sum(r["day_eur"] for r in rows), abs=0.011)

    blended = bundle.prices[ISIN]
    assert blended["blended"] is True
    assert blended["price"] == pytest.approx((10 * 55.15 + 5 * 55.398) / 15)
    assert blended["ticker"] == "EUNM.DE"
    assert blended["providers"] == ["tradegate", "yahoo"]


def test_a_fund_held_only_on_tradegate_is_simply_at_tradegates_price():
    bundle = _bundle([_tx(qty=5)], _yahoo(), _tdg())
    assert bundle.prices[ISIN]["price"] == 55.398
    assert bundle.prices[ISIN]["previous_close"] == 56.304
    assert bundle.prices[ISIN]["blended"] is False
    assert bundle.positions[0]["current_value"] == round(5 * 55.398, 2)


def test_a_tradegate_price_that_missed_a_close_falls_back_to_yahoo():
    yahoo = _yahoo()
    bundle = _bundle([_tx(qty=5)], yahoo, _tdg(fetched=LONG_AGO))
    row = hs.holdings_rows(bundle)[0]
    assert row["current_price"] == 55.15 and row["price_provider"] == "yahoo"
    assert bundle.prices[ISIN] == yahoo[ISIN]


def test_a_position_on_another_exchange_ignores_a_tradegate_price():
    bundle = _bundle([_tx(qty=5, exchange="EAM")], _yahoo(), _tdg())
    assert hs.holdings_rows(bundle)[0]["price_provider"] == "yahoo"
    assert bundle.prices[ISIN]["price"] == 55.15


def test_tradegate_alone_prices_a_fund_yahoo_never_found():
    bundle = _bundle([_tx(qty=5)], {}, _tdg())
    assert bundle.positions[0]["current_value"] == round(5 * 55.398, 2)
    assert bundle.prices[ISIN]["ticker"] is None


def test_a_missing_close_on_either_side_leaves_no_blended_close():
    bundle = _bundle(TWO_VENUES, _yahoo(prev=None), _tdg())
    assert bundle.prices[ISIN]["previous_close"] is None


def test_without_venue_prices_nothing_changes():
    yahoo = _yahoo()
    assert vps.effective_prices(TWO_VENUES, yahoo, {}) is yahoo


# ---------------------------------------------------------------------------
# The detail page's source line
# ---------------------------------------------------------------------------


def test_the_detail_names_tradegate_as_the_source():
    detail = hs.position_detail(_bundle([_tx(qty=5)], _yahoo(), _tdg()), ISIN, "TDG")
    assert detail["price_source"]["provider"] == "Tradegate"
    assert detail["price_source"]["venue_fallback"] is False
    assert detail["price_fetched_at"] == NOW
    assert detail["currency"] == "EUR"
    assert detail["ticker"] == "EUNM.DE"


def test_the_detail_says_fallback_when_tradegate_is_stale():
    detail = hs.position_detail(_bundle([_tx(qty=5)], _yahoo(), _tdg(fetched=LONG_AGO)), ISIN, "TDG")
    assert detail["price_source"]["provider"] == "Yahoo Finance"
    assert detail["price_source"]["venue_fallback"] is True


# ---------------------------------------------------------------------------
# Storing and refreshing
# ---------------------------------------------------------------------------

OK_QUOTE = {
    "status": "ok",
    "isin": ISIN,
    "venue": "TDG",
    "currency": "EUR",
    "last": 55.398,
    "bid": 55.0,
    "ask": 55.5,
    "previous_close": 56.304,
    "fetched_at": "2026-09-14T19:24:25",
    "stale": False,
}


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    c = database.connect("alice")
    database.init_db(c)
    yield c
    c.close()


def test_only_a_fresh_ok_quote_with_a_last_trade_is_stored(conn):
    assert vps.save_quote(conn, OK_QUOTE)
    row = database.load_venue_prices(conn)[(ISIN, "TDG")]
    assert row["price"] == 55.398
    assert row["previous_close"] == 56.304
    assert row["fetched_at"] == "2026-09-14 19:24:25"

    assert not vps.save_quote(conn, {**OK_QUOTE, "stale": True, "last": 1.0})
    assert not vps.save_quote(conn, {**OK_QUOTE, "last": None, "bid": 2.0})  # never bid instead
    assert not vps.save_quote(conn, {"status": "unavailable", "isin": ISIN})
    assert not vps.save_quote(conn, None)
    assert database.load_venue_prices(conn)[(ISIN, "TDG")]["price"] == 55.398


def test_refresh_asks_tradegate_only_for_open_tdg_positions(conn, monkeypatch):
    txs = [
        _tx(qty=5, exchange="TDG"),
        _tx(qty=5, exchange="EAM", isin="IE00B3XXRP09"),
        _tx(qty=3, exchange="TDG", isin="NL0010773842"),
        _tx("SELL", qty=3, exchange="TDG", isin="NL0010773842", date="2026-03-01"),
    ]
    monkeypatch.setattr(database, "load_transactions", lambda c: txs)
    asked = []

    def fake_quote(isin):
        asked.append(isin)
        return {**OK_QUOTE, "isin": isin}

    monkeypatch.setattr(tradegate_service, "get_quote", fake_quote)
    assert vps.refresh(conn) == {"refreshed": 1, "failed": 0}
    assert asked == [ISIN]


def test_a_failed_tradegate_keeps_the_previous_price(conn, monkeypatch):
    vps.save_quote(conn, OK_QUOTE)
    monkeypatch.setattr(database, "load_transactions", lambda c: [_tx(qty=5)])
    monkeypatch.setattr(tradegate_service, "get_quote", lambda isin: {"status": "unavailable", "isin": isin})
    assert vps.refresh(conn) == {"refreshed": 0, "failed": 1}
    assert database.load_venue_prices(conn)[(ISIN, "TDG")]["price"] == 55.398


def test_load_venue_prices_on_an_unmigrated_database_is_empty(tmp_path):
    import sqlite3

    raw = sqlite3.connect(tmp_path / "old.db")
    raw.row_factory = sqlite3.Row
    assert database.load_venue_prices(raw) == {}
    raw.close()
