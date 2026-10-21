"""
A balance that does not match the transactions: the likely cause, and
correcting what the app fetched itself.

The common case: the bank takes a card payment off your balance straight away,
but the transaction only comes in on the day it is booked. A balance from then
is exactly those payments lower than what the transactions say.
"""

import sqlite3
from uuid import uuid4

import pytest

from domain import database
from domain.money import accounts, bank_transactions, net_worth


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = database.connect("alice")
    database.init_db(c)
    yield c
    c.close()


@pytest.fixture()
def rid(conn) -> int:
    return accounts.make_bank_account(conn, kind="bank", provider="ing", name="ING", iban="NL00INGB0000000001")


def _tx(conn, rid, date, amount, name="WINKEL"):
    bank_transactions.save(
        conn,
        rid,
        [
            {
                "date": date,
                "interest_date": None,
                "amount": amount,
                "currency": "EUR",
                "name": name,
                "counterparty_iban": None,
                "description": "",
                "code": None,
                "kind": None,
                "dedup_hash": uuid4().hex,
                "raw": {},
            }
        ],
    )


def _deviations(conn):
    return net_worth.series(conn, [])["deviating_balances"]


def _balance_on(conn, rid, date):
    return next(m for m in accounts.load_balances(conn, rid) if m["date"] == date)


def _three_payments_pending(conn, rid, source_14: str):
    """Fetched on the 14th, with three card payments booked only on the 15th."""
    _tx(conn, rid, "2026-09-14", 4.0)
    accounts.set_balance(conn, rid, "2026-09-14", 305.80, source=source_14)
    for amount in (4.38, 8.5, 21.2):
        _tx(conn, rid, "2026-09-15", amount)


def test_payments_that_were_still_pending_are_recognised(conn, rid):
    _three_payments_pending(conn, rid, "sync")
    accounts.set_balance(conn, rid, "2026-09-15", 305.80)
    [a] = _deviations(conn)
    assert (a["date"], a["measured"], a["calculated"], a["source"]) == ("2026-09-14", 305.80, 339.88, "sync")
    assert a["explanation"] == {"kind": "pending", "end": "2026-09-15", "count": 3, "summed": 34.08, "whole": True}


def test_a_fetched_balance_corrects_itself(conn, rid):
    _three_payments_pending(conn, rid, "sync")
    accounts.set_balance(conn, rid, "2026-09-15", 305.80)
    assert accounts.restore_pending(conn, rid) == 1
    assert _balance_on(conn, rid, "2026-09-14") == {**_balance_on(conn, rid, "2026-09-14"), "balance": 339.88, "source": "sync"}
    assert _deviations(conn) == []
    assert accounts.restore_pending(conn, rid) == 0


def test_what_you_entered_yourself_stays(conn, rid):
    _three_payments_pending(conn, rid, "manual")
    accounts.set_balance(conn, rid, "2026-09-15", 305.80)
    assert accounts.restore_pending(conn, rid) == 0
    [a] = _deviations(conn)
    assert a["explanation"]["kind"] == "pending"
    assert _balance_on(conn, rid, "2026-09-14")["balance"] == 305.80


def test_with_a_new_payment_added_it_is_a_hint_not_proof(conn, rid):
    """Another payment on the 15th after fetching: the whole day does not explain it,
    three of the four do. Explaining yes, adjusting by itself no.
    """
    _three_payments_pending(conn, rid, "sync")
    _tx(conn, rid, "2026-09-15", 10.0)
    accounts.set_balance(conn, rid, "2026-09-15", 295.80)
    [a] = _deviations(conn)
    assert a["explanation"] == {"kind": "pending", "end": "2026-09-15", "count": 3, "summed": 34.08, "whole": False}
    assert accounts.restore_pending(conn, rid) == 0


def test_a_balance_from_a_day_earlier(conn, rid):
    """Looked at on the 10th, entered on the 11th — after a debit that day."""
    _tx(conn, rid, "2026-01-11", 50.0)
    accounts.set_balance(conn, rid, "2026-01-11", 1000.0)
    accounts.set_balance(conn, rid, "2026-01-31", 950.0)
    [a] = _deviations(conn)
    assert a["explanation"] == {"kind": "other_day", "day": "2026-01-10", "occupied": False}

    assert accounts.move_balance(conn, rid, "2026-01-11", "2026-01-10")
    assert [m["date"] for m in accounts.load_balances(conn, rid)] == ["2026-01-10", "2026-01-31"]
    assert _deviations(conn) == []


def test_a_transaction_that_appears_twice(conn, rid):
    _tx(conn, rid, "2026-01-10", 20.0)
    accounts.set_balance(conn, rid, "2026-01-15", 1000.0)
    _tx(conn, rid, "2026-01-20", 7.8, name="CAFE")
    # An import keeps out duplicates; two sources together (an export and the
    # connection, each with its own reference) can still put down a second one.
    conn.execute(
        "INSERT INTO bank_transactions (account_id, date, amount, currency, name, description, dedup_hash, source) "
        "SELECT account_id, date, amount, currency, name, description, 'tweede', source "
        "FROM bank_transactions WHERE name = 'CAFE'"
    )
    conn.commit()
    accounts.set_balance(conn, rid, "2026-01-31", 992.2)
    [a] = _deviations(conn)
    assert a["explanation"] == {"kind": "duplicate", "date": "2026-01-20", "name": "CAFE", "amount": 7.8, "count": 2}


def test_moving_to_a_day_with_a_measurement_keeps_that_one(conn, rid):
    accounts.set_balance(conn, rid, "2026-01-10", 500.0, source="sync")
    accounts.set_balance(conn, rid, "2026-01-11", 600.0)
    assert accounts.move_balance(conn, rid, "2026-01-10", "2026-01-11")
    assert [(m["date"], m["balance"]) for m in accounts.load_balances(conn, rid)] == [("2026-01-11", 600.0)]
    assert accounts.move_balance(conn, rid, "2026-01-05", "2026-01-06") is False


# ---------------------------------------------------------------------------
# A balance is a snapshot: halfway through the day, and with what is already pending.
# ---------------------------------------------------------------------------


def _pending_in_last(conn):
    return net_worth.series(conn, [])["pending_in_last"]


def _day(back: int) -> str:
    """A date `back` days before today: 'pending' only applies with a recent last balance."""
    from datetime import date, timedelta

    return (date.today() - timedelta(days=back)).isoformat()


def test_fetched_before_a_booking_of_that_same_day_is_right(conn, rid):
    # Fetched at eight o'clock; that afternoon's Tikkie was not in it yet.
    _tx(conn, rid, "2026-09-10", 10.0)
    accounts.set_balance(conn, rid, "2026-09-16", 500.00, source="sync")
    _tx(conn, rid, "2026-09-16", 120.0, "TIKKIE")
    _tx(conn, rid, "2026-09-17", 30.0)
    accounts.set_balance(conn, rid, "2026-09-17", 350.00, source="sync")
    assert _deviations(conn) == []


def test_a_payment_pending_in_the_last_balance_is_reported(conn, rid):
    # Fetched every day; the last balance (today) already includes a €1.75 card
    # payment that is not booked yet. Without correction every earlier balance is off
    # by exactly €1.75.
    _tx(conn, rid, _day(6), 10.0)
    balance = 400.00
    for back, off in [(4, 20.0), (3, 15.0), (2, 40.0), (1, 5.0)]:
        accounts.set_balance(conn, rid, _day(back), balance, source="sync")
        _tx(conn, rid, _day(back - 1), off)
        balance = round(balance - off, 2)
    accounts.set_balance(conn, rid, _day(0), round(balance - 1.75, 2), source="sync")

    assert _deviations(conn) == []
    [o] = _pending_in_last(conn)
    assert o["amount"] == pytest.approx(1.75) and o["direction"] == "debits" and o["date"] == _day(0)


def test_pending_and_an_early_balance_together(conn, rid):
    _tx(conn, rid, _day(6), 10.0)
    accounts.set_balance(conn, rid, _day(3), 300.00, source="sync")
    _tx(conn, rid, _day(2), 20.0)
    accounts.set_balance(conn, rid, _day(2), 280.00, source="sync")
    # Fetched early yesterday: the €50 credit came later that day.
    accounts.set_balance(conn, rid, _day(1), 280.00, source="sync")
    _tx(conn, rid, _day(1), -50.0, "SAVINGS_ACCOUNT")
    accounts.set_balance(conn, rid, _day(0), round(330.00 - 2.46, 2), source="sync")
    assert _deviations(conn) == []
    assert [o["amount"] for o in _pending_in_last(conn)] == [pytest.approx(2.46)]


def test_a_difference_that_stays_is_no_longer_pending(conn, rid):
    # The same pattern, but the last balance is already a week old: what was pending
    # then should have been booked long ago. Then something is missing.
    _tx(conn, rid, "2026-01-05", 10.0)
    accounts.set_balance(conn, rid, "2026-01-11", 300.00, source="sync")
    _tx(conn, rid, "2026-01-12", 20.0)
    accounts.set_balance(conn, rid, "2026-01-12", 280.00, source="sync")
    accounts.set_balance(conn, rid, "2026-01-14", round(260.00 - 63.21, 2), source="sync")
    _tx(conn, rid, "2026-01-13", 20.0)
    assert len(_deviations(conn)) == 2
    assert _pending_in_last(conn) == []


def test_an_early_balance_you_entered_yourself_is_not_a_snapshot(conn, rid):
    _tx(conn, rid, "2026-01-05", 10.0)
    accounts.set_balance(conn, rid, "2026-01-16", 500.00, source="manual")
    _tx(conn, rid, "2026-01-16", 120.0)
    accounts.set_balance(conn, rid, "2026-01-20", 380.00, source="sync")
    [a] = _deviations(conn)
    assert a["explanation"]["kind"] == "other_day"


def test_an_early_fetched_balance_becomes_the_end_of_day_balance(conn, rid):
    _tx(conn, rid, "2026-01-05", 10.0)
    accounts.set_balance(conn, rid, "2026-01-16", 500.00, source="sync")
    _tx(conn, rid, "2026-01-16", 120.0, "TIKKIE")
    _tx(conn, rid, "2026-01-17", 30.0)
    accounts.set_balance(conn, rid, "2026-01-17", 350.00, source="sync")
    assert accounts.restore_pending(conn, rid) == 1
    assert _balance_on(conn, rid, "2026-01-16")["balance"] == 380.00


def test_correcting_counts_what_is_pending_in_the_last_balance(conn, rid):
    _tx(conn, rid, _day(6), 10.0)
    accounts.set_balance(conn, rid, _day(3), 300.00, source="sync")
    _tx(conn, rid, _day(2), 20.0)
    accounts.set_balance(conn, rid, _day(2), 280.00, source="sync")
    accounts.set_balance(conn, rid, _day(1), 280.00, source="sync")
    _tx(conn, rid, _day(1), -50.0, "SAVINGS_ACCOUNT")
    accounts.set_balance(conn, rid, _day(0), round(330.00 - 2.46, 2), source="sync")
    assert accounts.restore_pending(conn, rid) == 1
    # The end of yesterday: 330, not 330 − 2.46.
    assert _balance_on(conn, rid, _day(1))["balance"] == 330.00


def test_a_balance_of_today_is_not_corrected(conn, rid):
    # The day is not over yet: more can still be booked.
    _tx(conn, rid, _day(3), 10.0)
    accounts.set_balance(conn, rid, _day(0), 500.00, source="sync")
    _tx(conn, rid, _day(0), 120.0)
    assert accounts.restore_pending(conn, rid) == 0
