"""
When a month is complete — with savings accounts included.

On real data (a current account and eight savings accounts) every month since
February became incomplete: a savings account books little, and after its
last transfer it counted as "missing", even though its balance overview ran
until today. And a savings account opened in 2025 made every month before it
incomplete.
"""

import pytest

from domain import database
from domain.money import accounts, bank_transactions, net_worth
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


def _account(conn, name):
    return accounts.make_bank_account(conn, kind="bank", provider="manual", name=name)


def _import(conn, account_id, *dates):
    """Imported rows (manual ones do not count for coverage)."""
    rules = [
        {"date": d, "amount": 10.0, "name": f"WINKEL {account_id}-{i}", "description": "", "currency": "EUR"} for i, d in enumerate(dates)
    ]
    bank_transactions.save(conn, account_id, base.add_hashes(rules))


def _months(conn):
    return {m["month"]: m for m in net_worth.per_month(conn)}


def _current_account_jan_until_march(conn):
    pay = _account(conn, "Betaal")
    _import(conn, pay, "2026-01-01", "2026-01-31", "2026-02-01", "2026-02-28", "2026-03-01", "2026-03-31")
    return pay


def test_a_savings_account_with_a_balance_until_today_is_not_missing(conn):
    _current_account_jan_until_march(conn)
    savings = _account(conn, "Spaar")
    _import(conn, savings, "2026-01-10")  # one transfer
    accounts.set_balances(conn, savings, [("2026-01-10", 100.0), ("2026-03-31", 100.0)], source="sync")

    months = _months(conn)
    assert all(months[m]["complete"] for m in ("2026-01", "2026-02", "2026-03"))


def test_without_a_balance_it_is_missing_after_its_last_transaction(conn):
    """The original case: an export that stops halfway."""
    _current_account_jan_until_march(conn)
    short = _account(conn, "Kort")
    _import(conn, short, "2026-01-01", "2026-02-10")

    months = _months(conn)
    assert months["2026-01"]["complete"]
    assert months["2026-02"]["missing"] == ["Kort"]
    assert months["2026-03"]["missing"] == ["Kort"]


def test_a_manual_balance_does_not_extend_coverage(conn):
    """A balance you type in yourself says nothing about which transactions there are."""
    _current_account_jan_until_march(conn)
    short = _account(conn, "Kort")
    _import(conn, short, "2026-01-01", "2026-02-10")
    accounts.set_balance(conn, short, "2026-03-31", 50.0)
    assert _months(conn)["2026-03"]["missing"] == ["Kort"]


def test_before_its_first_data_an_account_misses_nothing(conn):
    """An export that starts on the 5th makes that month incomplete, not the months before it."""
    _current_account_jan_until_march(conn)
    new = _account(conn, "Nieuw")
    _import(conn, new, "2026-03-05", "2026-03-31")

    months = _months(conn)
    assert months["2026-01"]["complete"]
    assert months["2026-02"]["complete"]
    assert months["2026-03"]["missing"] == ["Nieuw"]


def test_an_account_opened_that_day_does_not_miss_the_start(conn):
    """A savings account's balance overview starts on the day it was opened: then the
    rest of the month before is not a gap.
    """
    _current_account_jan_until_march(conn)
    savings = _account(conn, "Spaar")
    _import(conn, savings, "2026-02-14")
    accounts.set_balances(conn, savings, [("2026-02-14", 0.0), ("2026-03-31", 250.0)], source="sync")

    months = _months(conn)
    assert all(months[m]["complete"] for m in ("2026-01", "2026-02", "2026-03"))
