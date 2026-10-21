"""
Gifts, donations and inheritances: yours, but not income.

A tax-free gift from your parents comes from a person, and therefore fell
under "Ontvangen van vrienden" — income. Now there is a category of its own,
internal: not as income, but in your net worth. An existing user gets it once,
and their history is then relabelled.
"""

import pytest

from domain import database
from domain.money import accounts, bank_transactions, categorization


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


@pytest.fixture()
def conn():
    conn = database.connect("alice")
    database.init_db(conn)
    yield conn
    conn.close()


def _tx(conn, account_id, date, amount, name, description=""):
    bank_transactions.save(
        conn,
        account_id,
        [
            {
                "date": date,
                "interest_date": None,
                "amount": amount,
                "currency": "EUR",
                "name": name,
                "counterparty_iban": None,
                "description": description,
                "code": None,
                "kind": None,
                "dedup_hash": f"{date}{amount}{name}"[:40],
                "raw": {},
            }
        ],
    )


def _category(conn, name):
    return conn.execute("SELECT category_effective, type_effective FROM bank_transactions_typed WHERE name = ?", (name,)).fetchone()[:]


@pytest.fixture()
def account(conn):
    return accounts.make_bank_account(conn, kind="bank", provider="manual", name="Bank")


def test_a_gift_from_your_parents_is_not_income(conn, account):
    categorization.seed(conn)
    _tx(conn, account, "2026-04-15", -6908.0, "GH DEKKER CJ", "Storting belastingvrije donatie 2026")
    categorization.relabel(conn)
    assert _category(conn, "GH DEKKER CJ") == (categorization.GIFTS, "INTERNAL")


def test_an_inheritance_neither(conn, account):
    categorization.seed(conn)
    _tx(conn, account, "2023-06-07", -25000.0, "Erven mw EF Dekker")
    categorization.relabel(conn)
    assert _category(conn, "Erven mw EF Dekker") == (categorization.GIFTS, "INTERNAL")


def test_money_from_a_friend_stays_received_from_friends(conn, account):
    categorization.seed(conn)
    # Without a purpose in the description; "Tikkie etentje" counts under eating out.
    _tx(conn, account, "2026-05-18", -40.0, "G.H. Dekker", "Tikkie terugbetaling")
    categorization.relabel(conn)
    assert _category(conn, "G.H. Dekker")[0] == "Ontvangen van vrienden"


def test_a_gift_you_give_is_not_a_gift_you_get(conn, account):
    """Only credits: a gift you make is an expense."""
    categorization.seed(conn)
    _tx(conn, account, "2026-05-18", 500.0, "Neefje", "Schenking verjaardag")
    categorization.relabel(conn)
    assert _category(conn, "Neefje")[0] != categorization.GIFTS


def test_an_existing_user_gets_it_and_their_history_is_updated(conn, account):
    """From version 3: last year's gift was received from friends."""
    categorization.seed(conn)
    conn.execute("DELETE FROM rules WHERE category = ?", (categorization.GIFTS,))
    conn.execute("DELETE FROM categories WHERE name = ?", (categorization.GIFTS,))
    conn.execute("UPDATE settings SET value = '3' WHERE key = 'default_rules_version'")
    conn.commit()
    _tx(conn, account, "2025-10-26", -6713.0, "GH DEKKER CJ", "Belastingvrije storting 2025")
    categorization.relabel(conn)
    assert _category(conn, "GH DEKKER CJ")[0] == "Ontvangen van vrienden"

    categorization.seed(conn)
    assert _category(conn, "GH DEKKER CJ") == (categorization.GIFTS, "INTERNAL")


def test_what_you_set_by_hand_stays(conn, account):
    categorization.seed(conn)
    conn.execute("UPDATE settings SET value = '3' WHERE key = 'default_rules_version'")
    conn.execute("DELETE FROM rules WHERE category = ?", (categorization.GIFTS,))
    conn.commit()
    _tx(conn, account, "2025-10-26", -6713.0, "GH DEKKER CJ", "Belastingvrije storting 2025")
    conn.execute("UPDATE bank_transactions SET category_manual = 'Overige inkomsten'")
    conn.commit()
    categorization.seed(conn)
    assert _category(conn, "GH DEKKER CJ")[0] == "Overige inkomsten"
