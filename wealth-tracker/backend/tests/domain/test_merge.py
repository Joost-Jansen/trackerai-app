"""
Merging two sources for the same account without duplicates.

An export and the bank connection describe the same debit with a different
name and description, so with a different fingerprint. bank_transactions.save
therefore also recognises a booking by date and amount — one to one, so two
equal coffees on one day stay two.
"""

import pytest

from domain.money import bank_transactions
from domain import database
from domain.money import accounts
from domain.money.bank_providers import base


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


@pytest.fixture()
def conn():
    conn = database.connect("alice")
    database.init_db(conn)
    yield conn
    conn.close()


@pytest.fixture()
def account(conn):
    return accounts.make_bank_account(conn, kind="bank", provider="manual", name="Bank")


def _rules(*rows, source="csv"):
    return base.add_hashes([{"date": d, "amount": b, "name": f"{n} ({source})", "description": source,
                                  "currency": "EUR"} for d, b, n in rows])


def test_the_same_booking_from_another_source_is_not_added(conn, account):
    bank_transactions.save(conn, account, _rules(("2026-09-01", 10.0, "WINKEL"), source="export"))
    assert bank_transactions.save(conn, account, _rules(("2026-09-01", 10.0, "WINKEL"), source="connection")) == (0, 1)


def test_two_equal_bookings_stay_two(conn, account):
    assert bank_transactions.save(conn, account, _rules(("2026-09-01", 3.0, "KOFFIE"),
                                                          ("2026-09-01", 3.0, "KOFFIE"))) == (2, 0)


def test_a_third_equal_one_from_another_source_is_added(conn, account):
    bank_transactions.save(conn, account, _rules(("2026-09-01", 3.0, "KOFFIE"), ("2026-09-01", 3.0, "KOFFIE")))
    saved, skipped = bank_transactions.save(conn, account, _rules(
        ("2026-09-01", 3.0, "KOFFIE"), ("2026-09-01", 3.0, "KOFFIE"), ("2026-09-01", 3.0, "KOFFIE"), source="b"))
    assert (saved, skipped) == (1, 2)


def test_the_same_file_again_changes_nothing(conn, account):
    rules = _rules(("2026-09-01", 3.0, "KOFFIE"), ("2026-09-01", 3.0, "KOFFIE"), ("2026-09-02", 8.0, "WINKEL"))
    bank_transactions.save(conn, account, rules)
    assert bank_transactions.save(conn, account, _rules(("2026-09-01", 3.0, "KOFFIE"), ("2026-09-01", 3.0, "KOFFIE"),
                                                          ("2026-09-02", 8.0, "WINKEL"))) == (0, 3)


def test_another_account_does_not_count(conn, account):
    other = accounts.make_bank_account(conn, kind="bank", provider="manual", name="Andere")
    bank_transactions.save(conn, other, _rules(("2026-09-01", 10.0, "WINKEL"), source="x"))
    assert bank_transactions.save(conn, account, _rules(("2026-09-01", 10.0, "WINKEL"), source="y")) == (1, 0)


def test_another_amount_or_another_day_is_another_booking(conn, account):
    bank_transactions.save(conn, account, _rules(("2026-09-01", 10.0, "WINKEL"), source="x"))
    assert bank_transactions.save(conn, account, _rules(("2026-09-01", 10.5, "WINKEL"),
                                                          ("2026-09-02", 10.0, "WINKEL"), source="y")) == (2, 0)
