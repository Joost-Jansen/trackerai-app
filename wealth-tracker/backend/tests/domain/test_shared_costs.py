"""Your own share of a "Niet meetellen" pot counts as spending where you choose."""

import pytest

from domain import database, preferences
from domain.money import accounts, bank_transactions, categorization, shared_costs


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


def _conn():
    conn = database.connect("alice")
    database.init_db(conn)
    categorization.seed(conn)
    return conn


def _pot(conn, account, rows):
    """rows: [(date, amount)], saved in one import, all in "Niet meetellen"."""
    bank_transactions.save(conn, account, [{
        "date": d, "interest_date": None, "amount": a, "currency": "EUR",
        "name": "X", "counterparty_iban": None, "description": "",
        "code": None, "kind": None, "dedup_hash": f"{n:016d}", "raw": {},
    } for n, (d, a) in enumerate(rows)])
    conn.execute("UPDATE bank_transactions SET category_auto = ?", (categorization.EXCLUDE,))
    conn.commit()


def _trip(conn):
    """You organise a trip for four at 400 each: three friends pay you 400 ahead,
    you pay the boat 1600, and later refund 50 of deposit to each friend."""
    r = accounts.make_bank_account(conn, kind="bank", provider="manual", name="bunq")
    accounts.set_balance(conn, r, "2026-01-01", 5000.0)
    _pot(conn, r, [("2026-02-01", -400.0)] * 3      # friends pay ahead
                  + [("2026-03-01", 1600.0)]          # you pay the boat
                  + [("2026-04-01", 50.0)] * 3)       # their deposit back
    return r


def test_your_share_becomes_spending_in_the_default_category():
    conn = _conn()
    _trip(conn)
    rows = shared_costs.own_share_rows(conn)
    # Friends' money is held (no share yet); the boat makes your share 400;
    # paying back their deposits is their money too, so your share rises by 150.
    assert [(r["date"], r["amount"]) for r in rows] == [("2026-03-01", 400.0), ("2026-04-01", 150.0)]
    assert all(r["category"] == shared_costs.DEFAULT_CATEGORY and r["type"] == "EXPENSE" for r in rows)
    assert all(r["id"] < 0 and r["source"] == "derived" for r in rows)
    conn.close()


def test_the_setting_chooses_the_category_or_nowhere():
    conn = _conn()
    _trip(conn)
    preferences.put(conn, shared_costs.PREFERENCE, {"category": "Uit eten & bezorgen"})
    assert shared_costs.category(conn) == "Uit eten & bezorgen"
    assert {r["category"] for r in shared_costs.own_share_rows(conn)} == {"Uit eten & bezorgen"}

    preferences.put(conn, shared_costs.PREFERENCE, {"category": None})
    assert shared_costs.category(conn) is None
    assert shared_costs.own_share_rows(conn) == []

    # A category that no longer exists counts as nowhere, not as a guess.
    preferences.put(conn, shared_costs.PREFERENCE, {"category": "Does not exist"})
    assert shared_costs.category(conn) is None
    conn.close()


def test_without_a_balance_the_account_is_not_in_net_worth_and_has_no_share():
    conn = _conn()
    r = accounts.make_bank_account(conn, kind="bank", provider="manual", name="bunq")
    _pot(conn, r, [("2026-03-01", 1600.0)])
    assert shared_costs.own_share_rows(conn) == []
    conn.close()
