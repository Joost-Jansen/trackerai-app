"""
Tests for manual input: removing a measurement, and spending or income that is
in no export — cash, a market, a refund that came by nowhere else.

Sign convention, as everywhere: spending positive, income negative.
"""

import sqlite3

import pytest

from domain import database
from domain.money import accounts, bank_transactions, categorization, net_worth


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


def _conn() -> sqlite3.Connection:
    conn = database.connect("alice")
    database.init_db(conn)
    categorization.seed(conn)
    return conn


def _account(conn, name="Contant", kind="cash") -> int:
    return accounts.make_bank_account(conn, kind=kind, provider="manual", name=name)


# ---------------------------------------------------------------------------
# Removing a measurement
# ---------------------------------------------------------------------------


def test_delete_a_measurement():
    conn = _conn()
    r = _account(conn)
    accounts.set_balance(conn, r, "2026-01-31", 100.0)
    accounts.set_balance(conn, r, "2026-02-28", 200.0)

    assert accounts.delete_balance(conn, r, "2026-02-28") is True
    assert [s["date"] for s in accounts.load_balances(conn, r)] == ["2026-01-31"]
    assert accounts.balance_on(conn, r, "2026-03-01") == pytest.approx(100.0), "daarna vult de vorige meting weer vooruit"
    conn.close()


def test_deleting_a_measurement_that_does_not_exist_says_so():
    conn = _conn()
    assert accounts.delete_balance(conn, _account(conn), "2026-01-31") is False
    conn.close()


# ---------------------------------------------------------------------------
# Manual transactions
# ---------------------------------------------------------------------------


def test_a_manual_expense():
    conn = _conn()
    r = _account(conn)
    tid = bank_transactions.add_manually(conn, account_id=r, date="2026-03-01", amount=12.5, name="Markt")
    row = next(x for x in bank_transactions.load(conn) if x["id"] == tid)
    assert row["amount"] == pytest.approx(12.5)
    assert row["source"] == "manual"
    assert row["name"] == "Markt"
    conn.close()


def test_two_identical_manual_expenses_are_two():
    """In an import an identical row is a duplicate; someone entering three euros for
    coffee twice means two coffees.
    """
    conn = _conn()
    r = _account(conn)
    for _ in range(2):
        bank_transactions.add_manually(conn, account_id=r, date="2026-03-01", amount=3.0, name="Koffie")
    assert len(bank_transactions.load(conn)) == 2
    conn.close()


@pytest.mark.parametrize(
    "fields",
    [
        {"date": "1-3-2026"},
        {"name": "  "},
        {"amount": 0.0},
        {"amount": float("nan")},
    ],
)
def test_nonsense_is_refused(fields):
    conn = _conn()
    base = {"account_id": _account(conn), "date": "2026-03-01", "amount": 5.0, "name": "Markt"}
    with pytest.raises(ValueError):
        bank_transactions.add_manually(conn, **{**base, **fields})
    conn.close()


def test_a_manual_expense_is_labelled_like_any_other():
    conn = _conn()
    bank_transactions.add_manually(conn, account_id=_account(conn), date="2026-03-01", amount=20.0, name="ALBERT HEIJN")
    categorization.relabel(conn)
    row = bank_transactions.load(conn)[0]
    assert row["category"] == "Supermarkt"
    assert row["type"] == "EXPENSE"
    conn.close()


def test_delete_a_manual_transaction():
    conn = _conn()
    tid = bank_transactions.add_manually(conn, account_id=_account(conn), date="2026-03-01", amount=5.0, name="Markt")
    assert bank_transactions.delete_manual(conn, tid) is True
    assert bank_transactions.load(conn) == []
    assert bank_transactions.delete_manual(conn, tid) is False
    conn.close()


def test_an_imported_transaction_is_not_deleted_by_hand():
    """That comes back with the next import, and then the delete seems to have worked."""
    conn = _conn()
    r = _account(conn, "Bank", "bank")
    bank_transactions.save(
        conn,
        r,
        [
            {
                "date": "2026-03-01",
                "interest_date": None,
                "amount": 5.0,
                "currency": "EUR",
                "name": "X",
                "counterparty_iban": None,
                "description": "",
                "code": None,
                "kind": None,
                "dedup_hash": "a" * 16,
                "raw": {},
            }
        ],
    )
    row = bank_transactions.load(conn)[0]
    assert row["source"] == "import"
    with pytest.raises(bank_transactions.NotManual):
        bank_transactions.delete_manual(conn, row["id"])
    conn.close()


def test_manual_rows_say_nothing_about_coverage():
    """Otherwise one cash expense makes every month around it incomplete."""
    conn = _conn()
    bank = _account(conn, "Bank", "bank")
    bank_transactions.save(
        conn,
        bank,
        [
            {
                "date": d,
                "interest_date": None,
                "amount": 5.0,
                "currency": "EUR",
                "name": "X",
                "counterparty_iban": None,
                "description": "",
                "code": None,
                "kind": None,
                "dedup_hash": h * 16,
                "raw": {},
            }
            for d, h in (("2026-03-01", "a"), ("2026-03-31", "b"))
        ],
    )
    bank_transactions.add_manually(conn, account_id=_account(conn), date="2026-03-15", amount=3.0, name="Koffie")
    categorization.relabel(conn)
    march = next(m for m in net_worth.per_month(conn) if m["month"] == "2026-03")
    assert march["complete"] is True
    assert march["spending"] == pytest.approx(13.0), "maar hij telt wel mee in het bedrag"
    conn.close()


def test_an_existing_database_gets_the_column(tmp_path):
    """Databases from before manual input have no `source`; everything in them came
    from an import, and that is exactly what the default value says.
    """
    conn = database.connect("bob")
    conn.execute("""CREATE TABLE bank_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER NOT NULL,
        date TEXT NOT NULL, interest_date TEXT, amount REAL NOT NULL,
        currency TEXT NOT NULL DEFAULT 'EUR', name TEXT NOT NULL,
        counterparty_iban TEXT, description TEXT NOT NULL DEFAULT '', code TEXT,
        kind TEXT, category_auto TEXT, category_manual TEXT, type TEXT,
        dedup_hash TEXT NOT NULL, raw TEXT, UNIQUE(dedup_hash))""")
    conn.execute(
        "INSERT INTO bank_transactions (account_id, date, amount, name, dedup_hash) VALUES (1, '2026-01-01', 5, 'X', 'aaaaaaaaaaaaaaaa')"
    )
    conn.commit()
    database.init_db(conn)
    database.init_db(conn)  # twice must not break anything
    assert conn.execute("SELECT source FROM bank_transactions").fetchone()[0] == "import"
    conn.close()
