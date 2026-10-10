"""
Tests for accounts.balances_for_series: deriving an account's balance from its
transactions and one known balance.

The shape of a bank balance is fixed by the transactions — every transaction
changes it, and nothing else. Only the level is not. One known balance fixes
that, and with it the balance is known for every day. Sign convention as
everywhere: spending positive, income negative.
"""

import sqlite3
from uuid import uuid4

import pytest

from domain.money import bank_transactions
from domain import database
from domain.money import accounts
from domain.money import net_worth


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


def _conn() -> sqlite3.Connection:
    conn = database.connect("alice")
    database.init_db(conn)
    return conn


def _bank(conn, name="ING", iban="NL00INGB0000000001") -> int:
    return accounts.make_bank_account(conn, kind="bank", provider="ing", name=name, iban=iban)


def _tx(conn, account_id, date, amount):
    bank_transactions.save(conn, account_id, [{
        "date": date, "interest_date": None, "amount": amount, "currency": "EUR", "name": "X",
        "counterparty_iban": None, "description": "", "code": None, "kind": None,
        "dedup_hash": uuid4().hex, "raw": {},
    }])


def _balance(conn, rid, d):
    return accounts.balance_on(conn, rid, d)


def test_a_balance_and_the_transactions_give_every_day():
    conn = _conn()
    ing = _bank(conn)
    _tx(conn, ing, "2026-01-05", -2000.0)   # salary in
    _tx(conn, ing, "2026-01-10", 300.0)     # groceries
    _tx(conn, ing, "2026-01-20", 500.0)     # rent
    accounts.set_balance(conn, ing, "2026-01-31", 1200.0)

    assert _balance(conn, ing, "2026-01-31") == pytest.approx(1200.0)
    assert _balance(conn, ing, "2026-01-20") == pytest.approx(1200.0), "na de huur, niets meer daarna"
    assert _balance(conn, ing, "2026-01-15") == pytest.approx(1700.0), "vóór de huur"
    assert _balance(conn, ing, "2026-01-07") == pytest.approx(2000.0), "na salaris, vóór boodschappen"
    assert _balance(conn, ing, "2026-01-05") == pytest.approx(2000.0)
    conn.close()


def test_before_the_first_transaction_the_account_is_zero():
    """A salary as the first booking can give an opening balance of zero."""
    conn = _conn()
    ing = _bank(conn)
    _tx(conn, ing, "2026-01-05", -2000.0)
    accounts.set_balance(conn, ing, "2026-01-31", 2000.0)
    assert _balance(conn, ing, "2026-01-04") == 0.0
    conn.close()


def test_the_anchor_may_lie_mid_period():
    conn = _conn()
    ing = _bank(conn)
    _tx(conn, ing, "2026-01-05", 100.0)
    _tx(conn, ing, "2026-01-25", 200.0)
    accounts.set_balance(conn, ing, "2026-01-15", 1000.0)
    assert _balance(conn, ing, "2026-01-05") == pytest.approx(1000.0)
    assert _balance(conn, ing, "2026-01-25") == pytest.approx(800.0)
    conn.close()


def test_the_last_measurement_is_the_anchor_and_earlier_ones_do_not_count():
    """An earlier measurement that does not match the transactions would make the
    line jump; the last one is usually what you just saw in your banking app.
    """
    conn = _conn()
    ing = _bank(conn)
    _tx(conn, ing, "2026-01-05", 100.0)
    accounts.set_balance(conn, ing, "2026-01-01", 0.0)      # not right
    accounts.set_balance(conn, ing, "2026-01-31", 900.0)    # the anchor
    assert _balance(conn, ing, "2026-01-05") == pytest.approx(900.0)
    conn.close()


def test_without_a_balance_an_account_with_transactions_has_no_level():
    conn = _conn()
    ing = _bank(conn)
    _tx(conn, ing, "2026-01-05", 100.0)
    assert accounts.balances_for_series(conn, ing) == []
    series = net_worth.series(conn, [{"d": "2026-01-05", "invested": 0, "value": 10.0, "value_divs": 10.0}])
    assert series["without_balance"] == ["ING"], "de pagina moet kunnen zeggen welke"
    conn.close()


def test_a_manual_transaction_counts_too():
    conn = _conn()
    ing = _bank(conn)
    bank_transactions.add_manually(conn, account_id=ing, date="2026-01-10", amount=50.0, name="Markt")
    accounts.set_balance(conn, ing, "2026-01-31", 950.0)
    assert _balance(conn, ing, "2026-01-09") == pytest.approx(1000.0)
    conn.close()


def test_an_account_without_transactions_keeps_following_its_measurements():
    conn = _conn()
    bunq = _bank(conn, "bunq", "NL00BUNQ0000000002")
    accounts.set_balance(conn, bunq, "2026-01-01", 100.0)
    accounts.set_balance(conn, bunq, "2026-01-11", 200.0)
    assert _balance(conn, bunq, "2026-01-06") == pytest.approx(150.0), "rechte lijn, zoals altijd"
    conn.close()


def test_a_transfer_between_own_accounts_leaves_net_worth_unchanged():
    """The goal: money going from the bank to the broker is on the same day on both
    sides, instead of being lost for a month between two measurements.
    """
    conn = _conn()
    ing = _bank(conn)
    cash = accounts.make_bank_account(conn, kind="broker", provider="degiro", name="DeGiro cash")
    _tx(conn, ing, "2026-01-10", 5000.0)                     # to DeGiro
    accounts.set_balance(conn, ing, "2026-01-31", 1000.0)
    accounts.set_balance(conn, cash, "2026-01-01", 0.0, source="sync")
    accounts.set_balance(conn, cash, "2026-01-10", 5000.0, source="sync")

    series = net_worth.series(conn, [{"d": "2026-01-01", "invested": 0, "value": 0.0, "value_divs": 0.0}])
    net = {p["d"]: p["net"] for p in series["points"]}
    assert net["2026-01-09"] == pytest.approx(6000.0)
    assert net["2026-01-10"] == pytest.approx(6000.0)
    assert net["2026-01-20"] == pytest.approx(6000.0)
    conn.close()


def test_dots_only_on_own_measurements():
    """A balance from a statement or from transactions is not a measurement."""
    conn = _conn()
    ing = _bank(conn)
    for d in ("2026-01-05", "2026-01-06", "2026-01-07"):
        _tx(conn, ing, d, 10.0)
    accounts.set_balance(conn, ing, "2026-01-31", 1000.0)
    series = net_worth.series(conn, [])
    assert series["measurements"] == 1
    conn.close()


def test_opening_balance_is_only_the_day_before_the_first_booking():
    conn = _conn()
    rid = _bank(conn)
    _tx(conn, rid, "2026-01-10", 50.0)
    accounts.set_balance(conn, rid, "2026-01-31", 950.0)
    assert _balance(conn, rid, "2026-01-08") == 0.0
    assert _balance(conn, rid, "2026-01-09") == 1000.0
    assert _balance(conn, rid, "2026-01-10") == 950.0
    conn.close()


def test_a_deviating_measurement_is_reported():
    conn = _conn()
    rid = _bank(conn)
    _tx(conn, rid, "2026-01-10", 50.0)
    accounts.set_balance(conn, rid, "2026-01-15", 800.0)
    accounts.set_balance(conn, rid, "2026-01-31", 950.0)
    result = net_worth.series(conn, [])
    [deviation] = result["deviating_balances"]
    assert {k: deviation[k] for k in ("account", "date", "measured", "calculated", "anchor")} == {
        "account": "ING", "date": "2026-01-15", "measured": 800.0, "calculated": 950.0, "anchor": "2026-01-31"}
    assert deviation["explanation"] == {"kind": "missing", "direction": "credits", "amount": 150.0}
    conn.close()
