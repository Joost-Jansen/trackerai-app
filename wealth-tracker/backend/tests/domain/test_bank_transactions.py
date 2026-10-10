"""
Tests for bank_transactions.py — storing what the parsers deliver.

The point of this layer is one property: **importing the same export twice
must add nothing.** Bank exports simply overlap — you download the last three
months in March and again in April — and without that property every total
grows with every import.

The flip side is just as important: two *really* identical payments on one day
must stay two rows. See bank_providers/base.py for how those two go together.
"""

import sqlite3

import pytest

from domain.money import bank_transactions
from domain import database
from domain.money import accounts


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


def _conn(username: str = "alice") -> sqlite3.Connection:
    conn = database.connect(username)
    database.init_db(conn)
    return conn


def _account(conn) -> int:
    return accounts.make_bank_account(
        conn, kind="bank", provider="ing", name="ING", iban="NL00INGB0000000001"
    )


def _rule(**overrides) -> dict:
    rule = {
        "date": "2026-02-19",
        "interest_date": None,
        "amount": 42.50,
        "currency": "EUR",
        "name": "SUPERMARKT",
        "counterparty_iban": None,
        "description": "Bon 1",
        "account_iban": "NL00INGB0000000001",
        "code": "BA",
        "kind": "Payment terminal",
        "dedup_hash": "aaaaaaaaaaaaaaaa",
        "raw": {"Date": "20260219"},
    }
    rule.update(overrides)
    return rule


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_init_db_creates_the_table():
    conn = _conn()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    assert "bank_transactions" in {row["name"] for row in cursor.fetchall()}
    conn.close()


# ---------------------------------------------------------------------------
# Storing
# ---------------------------------------------------------------------------

def test_save_and_read_back():
    conn = _conn()
    account_id = _account(conn)

    saved, skipped = bank_transactions.save(conn, account_id, [_rule()])
    assert (saved, skipped) == (1, 0)

    rows = bank_transactions.load(conn)
    assert len(rows) == 1
    assert rows[0]["amount"] == pytest.approx(42.50)
    assert rows[0]["name"] == "SUPERMARKT"
    assert rows[0]["account_id"] == account_id
    conn.close()


def test_the_same_export_twice_adds_nothing():
    """The property this whole layer revolves around."""
    conn = _conn()
    account_id = _account(conn)
    rules = [_rule(), _rule(dedup_hash="bbbbbbbbbbbbbbbb", name="ANDERE")]

    assert bank_transactions.save(conn, account_id, rules) == (2, 0)
    assert bank_transactions.save(conn, account_id, rules) == (0, 2)
    assert len(bank_transactions.load(conn)) == 2
    conn.close()


def test_an_overlapping_export_adds_only_what_is_new():
    conn = _conn()
    account_id = _account(conn)
    bank_transactions.save(conn, account_id, [_rule()])

    second_export = [_rule(), _rule(dedup_hash="cccccccccccccccc", date="2026-03-01")]
    assert bank_transactions.save(conn, account_id, second_export) == (1, 1)
    assert len(bank_transactions.load(conn)) == 2
    conn.close()


def test_raw_is_stored_as_json():
    """In case a field turns out to be missing later that the bank did send."""
    conn = _conn()
    account_id = _account(conn)
    bank_transactions.save(conn, account_id, [_rule(raw={"Code": "BA", "x": 1})])
    assert bank_transactions.load(conn)[0]["raw"]["Code"] == "BA"
    conn.close()


def test_categories_start_empty():
    """The labelling engine comes later; until then nothing is categorised, not even 'Onbekend'."""
    conn = _conn()
    account_id = _account(conn)
    bank_transactions.save(conn, account_id, [_rule()])
    row = bank_transactions.load(conn)[0]
    assert row["category_auto"] is None
    assert row["category_manual"] is None
    assert row["category"] is None
    conn.close()


def test_a_manual_category_wins_over_the_automatic_one():
    """The model from the old spreadsheet: your judgement always comes first."""
    conn = _conn()
    account_id = _account(conn)
    bank_transactions.save(conn, account_id, [_rule()])
    row_id = bank_transactions.load(conn)[0]["id"]

    bank_transactions.set_category_auto(conn, row_id, "Supermarkt")
    assert bank_transactions.load(conn)[0]["category"] == "Supermarkt"

    bank_transactions.set_category_manual(conn, row_id, "Uit eten & bezorgen")
    row = bank_transactions.load(conn)[0]
    assert row["category_auto"] == "Supermarkt"
    assert row["category"] == "Uit eten & bezorgen"
    conn.close()


def test_the_automatic_category_does_not_overwrite_the_manual_one():
    """Running a rule again must never erase anything you set."""
    conn = _conn()
    account_id = _account(conn)
    bank_transactions.save(conn, account_id, [_rule()])
    row_id = bank_transactions.load(conn)[0]["id"]

    bank_transactions.set_category_manual(conn, row_id, "Uit eten & bezorgen")
    bank_transactions.set_category_auto(conn, row_id, "Supermarkt")

    assert bank_transactions.load(conn)[0]["category"] == "Uit eten & bezorgen"
    conn.close()


# ---------------------------------------------------------------------------
# Reading and filtering
# ---------------------------------------------------------------------------

def test_loading_sorted_by_date():
    conn = _conn()
    account_id = _account(conn)
    bank_transactions.save(conn, account_id, [
        _rule(date="2026-03-01", dedup_hash="c" * 16),
        _rule(date="2026-01-01", dedup_hash="a" * 16),
        _rule(date="2026-02-01", dedup_hash="b" * 16),
    ])
    assert [r["date"] for r in bank_transactions.load(conn)] == [
        "2026-01-01", "2026-02-01", "2026-03-01"
    ]
    conn.close()


def test_filter_by_period():
    conn = _conn()
    account_id = _account(conn)
    bank_transactions.save(conn, account_id, [
        _rule(date="2026-01-15", dedup_hash="a" * 16),
        _rule(date="2026-02-15", dedup_hash="b" * 16),
        _rule(date="2026-03-15", dedup_hash="c" * 16),
    ])
    rows = bank_transactions.load(conn, start="2026-02-01", end="2026-02-28")
    assert [r["date"] for r in rows] == ["2026-02-15"]
    conn.close()


def test_filter_by_account():
    conn = _conn()
    ing = _account(conn)
    bunq = accounts.make_bank_account(conn, kind="bank", provider="bunq",
                                    name="bunq", iban="NL00BUNQ0000000002")
    bank_transactions.save(conn, ing, [_rule(dedup_hash="a" * 16)])
    bank_transactions.save(conn, bunq, [_rule(dedup_hash="b" * 16, name="BUNQ REGEL")])

    assert [r["name"] for r in bank_transactions.load(conn, account_id=bunq)] == ["BUNQ REGEL"]
    conn.close()


def test_deleting_an_account_takes_its_transactions_along():
    """Otherwise they keep counting in every overview without an account to belong to."""
    conn = _conn()
    account_id = _account(conn)
    bank_transactions.save(conn, account_id, [_rule()])

    accounts.delete_account(conn, account_id)
    assert bank_transactions.load(conn) == []
    conn.close()


# ---------------------------------------------------------------------------
# Separation between users
# ---------------------------------------------------------------------------

def test_the_same_hash_for_two_users_is_allowed():
    """Two housemates with the same rent payment are not duplicates of each other."""
    alice, bob = _conn("alice"), _conn("bob")
    a_id, b_id = _account(alice), _account(bob)

    assert bank_transactions.save(alice, a_id, [_rule()]) == (1, 0)
    assert bank_transactions.save(bob, b_id, [_rule()]) == (1, 0)

    assert len(bank_transactions.load(alice)) == 1
    assert len(bank_transactions.load(bob)) == 1
    alice.close()
    bob.close()
