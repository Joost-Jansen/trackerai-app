"""
Recognising transfers by their counterpart: the same amount out and in.

On real data a withdrawal at DeGiro came in at the bank under the user's own
name, from a German IBAN. The rule for private persons turned it into
"received from friends": €69,209 and seven times €10,000 of income that was no
income. DeGiro's account statement names those withdrawals with amount and
date; that is how they can be recognised, without code having to know anything
about DeGiro or the bank.

Everything here is made up.
"""

import pytest

from domain import database
from domain.money import accounts, bank_transactions, categorization
from domain.money.bank_providers import base


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


@pytest.fixture()
def conn():
    conn = database.connect("alice")
    database.init_db(conn)
    categorization.seed(conn)
    yield conn
    conn.close()


@pytest.fixture()
def bank(conn):
    return accounts.make_bank_account(conn, kind="bank", provider="bunq", name="Bank", iban="NL00BUNQ0000000009")


@pytest.fixture()
def broker(conn):
    return accounts.make_bank_account(conn, kind="broker", provider="degiro", name="Broker cash")


ELSEWHERE = "DE00999999990000000001"


def _bank(conn, account, *rules):
    """(date, amount, name) — amount in the sign convention: income negative."""
    rows = [{"date": d, "amount": b, "name": n, "description": "", "currency": "EUR", "counterparty_iban": ELSEWHERE} for d, b, n in rules]
    bank_transactions.save(conn, account, base.add_hashes(rows))


def _entries(conn, account, *rules):
    """(date, amount) — positive is money the broker receives."""
    return accounts.save_entries(
        conn, account, [{"date": d, "amount": b, "description": "", "key": f"{d}|{b}|{i}"} for i, (d, b) in enumerate(rules)]
    )


def _categories(conn) -> list[tuple]:
    categorization.relabel(conn)
    return [
        (r["date"], r["amount"], r["category"], r["type"]) for r in sorted(bank_transactions.load(conn), key=lambda r: (r["date"], r["id"]))
    ]


def test_a_withdrawal_arriving_at_the_bank_is_internal(conn, bank, broker):
    _entries(conn, broker, ("2025-11-07", -69209.08))
    _bank(conn, bank, ("2025-11-07", -69209.08, "A. B. VOORBEELD"))
    assert _categories(conn) == [("2025-11-07", -69209.08, "Naar beleggen", "INTERNAL")]


def test_a_deposit_from_the_bank_is_internal(conn, bank, broker):
    _entries(conn, broker, ("2025-11-11", 50000.0))
    _bank(conn, bank, ("2025-11-10", 50000.0, "WILLEKEURIGE NAAM 1"))
    assert _categories(conn)[0][2:] == ("Naar beleggen", "INTERNAL")


def test_seven_withdrawals_are_seven_pairs(conn, bank, broker):
    _entries(conn, broker, *[("2025-11-14", -10000.0)] * 7)
    _bank(conn, bank, *[("2025-11-14", -10000.0, "A. B. VOORBEELD")] * 7)
    assert all(c[3] == "INTERNAL" for c in _categories(conn))


def test_a_movement_pairs_with_at_most_one_bank_row(conn, bank, broker):
    _entries(conn, broker, ("2025-11-14", -10000.0))
    _bank(conn, bank, ("2025-11-14", -10000.0, "A. B. VOORBEELD"), ("2025-11-15", -10000.0, "A. B. VOORBEELD"))
    types = [c[3] for c in _categories(conn)]
    assert types == ["INTERNAL", "INCOME"]


def test_a_reversed_reservation_is_not_a_withdrawal(conn, bank, broker):
    """+X reserved, −X reversed, +X really deposited. Only the last one is a movement:
    the payment to the broker pairs, money that came in from someone else that day
    does not.
    """
    _entries(conn, broker, ("2025-11-19", 15000.0), ("2025-11-20", -15000.0), ("2025-11-20", 15000.0))
    _bank(
        conn,
        bank,
        ("2025-11-19", -15000.0, "A. B. VOORBEELD"),  # in, from elsewhere
        ("2025-11-19", 15000.0, "WILLEKEURIGE NAAM 2"),
    )  # out, to the broker
    off = {c[1]: c[3] for c in _categories(conn)}
    assert off == {-15000.0: "INCOME", 15000.0: "INTERNAL"}


def test_too_far_apart_is_not_a_pair(conn, bank, broker):
    _entries(conn, broker, ("2025-11-01", -5000.0))
    _bank(conn, bank, ("2025-11-07", -5000.0, "A. B. VOORBEELD"))
    assert _categories(conn)[0][3] == "INCOME"


def test_small_amounts_do_not_pair(conn, bank, broker):
    """A €3.90 transaction fee and a €3.90 Tikkie are a coincidence."""
    _entries(conn, broker, ("2025-11-07", -3.90))
    _bank(conn, bank, ("2025-11-08", -3.90, "A. B. VOORBEELD"))
    assert _categories(conn)[0][3] == "INCOME"


def test_a_manual_row_does_not_pair(conn, bank, broker):
    _entries(conn, broker, ("2025-11-07", -500.0))
    bank_transactions.add_manually(conn, account_id=bank, date="2025-11-07", amount=-500.0, name="A. B. VOORBEELD")
    assert _categories(conn)[0][3] == "INCOME"


def test_a_category_you_set_yourself_stays(conn, bank, broker):
    _entries(conn, broker, ("2025-11-07", -1000.0))
    _bank(conn, bank, ("2025-11-07", -1000.0, "A. B. VOORBEELD"))
    tid = bank_transactions.load(conn)[0]["id"]
    bank_transactions.set_category_manual(conn, tid, "Salaris")
    assert _categories(conn)[0][2:] == ("Salaris", "INCOME")


def test_the_same_overview_twice_gives_no_duplicate_movements(conn, broker):
    assert _entries(conn, broker, ("2025-11-07", -69209.08)) == 1
    assert _entries(conn, broker, ("2025-11-07", -69209.08)) == 0
