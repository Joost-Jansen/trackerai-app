"""
Tests for accounts.py — the accounts and their balances.

An account here is anything holding money that does not come from a DeGiro
export: a current account, a savings account, cash in a drawer. The balances
are separate measurements on a date, not a continuous series — exactly as you
have them in real life: you look now and then, and in between you do not know.

That "in between" is the core of this file. `balance_on` fills forward: the
balance on a day is the last measurement on or before that day. Without that
rule the net worth curve would drop to zero on every day without a
measurement.

Every test points database._HERE to a temporary folder, like test_database.py,
so the real data/ folder is never touched.
"""

import sqlite3

import pytest

from domain import database
from domain.money import accounts


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


def _new_conn(username: str = "alice") -> sqlite3.Connection:
    conn = database.connect(username)
    database.init_db(conn)
    return conn


def _account(conn, **overrides) -> int:
    fields = {
        "kind": "bank",
        "provider": "ing",
        "name": "ING Betaalrekening",
        "iban": "NL00INGB0000000001",
    }
    fields.update(overrides)
    return accounts.make_bank_account(conn, **fields)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_init_db_creates_the_account_tables():
    conn = _new_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row["name"] for row in cursor.fetchall()}
    assert {"accounts", "account_balances"} <= tables
    conn.close()


def test_init_db_is_repeatable():
    """init_db runs on every request; twice must not break anything."""
    conn = _new_conn()
    account_id = _account(conn)
    database.init_db(conn)
    assert len(accounts.load_accounts(conn)) == 1
    assert accounts.load_account(conn, account_id) is not None
    conn.close()


# ---------------------------------------------------------------------------
# Creating and reading accounts
# ---------------------------------------------------------------------------


def test_account_roundtrip():
    conn = _new_conn()
    account_id = _account(conn)

    r = accounts.load_account(conn, account_id)
    assert r["name"] == "ING Betaalrekening"
    assert r["kind"] == "bank"
    assert r["provider"] == "ing"
    assert r["iban"] == "NL00INGB0000000001"
    assert r["currency"] == "EUR"
    assert r["active"] == 1
    conn.close()


def test_cash_has_no_iban():
    """Cash is an account like any other, just without a number."""
    conn = _new_conn()
    account_id = _account(conn, kind="cash", provider="manual", name="Contant", iban=None)
    assert accounts.load_account(conn, account_id)["iban"] is None
    conn.close()


def test_several_accounts_without_iban_can_coexist():
    """Two pots of cash are two accounts, not a duplicate."""
    conn = _new_conn()
    _account(conn, kind="cash", provider="manual", name="Portemonnee", iban=None)
    _account(conn, kind="cash", provider="manual", name="Kluisje", iban=None)
    assert len(accounts.load_accounts(conn)) == 2
    conn.close()


def test_the_same_iban_cannot_be_added_twice():
    """Otherwise the same bank export twice gives a second account."""
    conn = _new_conn()
    _account(conn)
    with pytest.raises(accounts.AccountExistsAlready):
        _account(conn, name="Andere naam voor dezelfde rekening")
    conn.close()


def test_iban_is_normalised_before_comparing():
    """Banks write an IBAN with spaces, in lowercase, or both."""
    conn = _new_conn()
    _account(conn, iban="NL00 INGB 0000 0000 01")
    with pytest.raises(accounts.AccountExistsAlready):
        _account(conn, iban="nl00ingb0000000001")
    assert accounts.load_accounts(conn)[0]["iban"] == "NL00INGB0000000001"
    conn.close()


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "spaarvarken"),
        ("provider", "knab"),
    ],
)
def test_an_unknown_kind_or_provider_is_refused(field, value):
    """A typo here is an account that no longer falls into any overview."""
    conn = _new_conn()
    with pytest.raises(ValueError):
        _account(conn, **{field: value})
    conn.close()


def test_an_account_without_a_name_is_refused():
    conn = _new_conn()
    with pytest.raises(ValueError):
        _account(conn, name="   ")
    conn.close()


def test_load_account_returns_none_for_an_unknown_id():
    conn = _new_conn()
    assert accounts.load_account(conn, 999) is None
    conn.close()


# ---------------------------------------------------------------------------
# Updating and deleting
# ---------------------------------------------------------------------------


def test_rename_an_account_and_set_it_inactive():
    conn = _new_conn()
    account_id = _account(conn)

    accounts.update_account(conn, account_id, name="Oude ING", active=0)

    r = accounts.load_account(conn, account_id)
    assert r["name"] == "Oude ING"
    assert r["active"] == 0
    conn.close()


def test_only_active_leaves_out_closed_accounts():
    conn = _new_conn()
    _account(conn, name="Nog in gebruik")
    shut = _account(conn, name="Opgeheven", iban="NL00BUNQ0000000002", provider="bunq")
    accounts.update_account(conn, shut, active=0)

    assert len(accounts.load_accounts(conn)) == 2
    active = accounts.load_accounts(conn, only_active=True)
    assert [r["name"] for r in active] == ["Nog in gebruik"]
    conn.close()


def test_update_account_refuses_an_unknown_field():
    """A typo must not silently do nothing."""
    conn = _new_conn()
    account_id = _account(conn)
    with pytest.raises(ValueError):
        accounts.update_account(conn, account_id, nmae="typo")
    conn.close()


def test_deleting_an_account_takes_its_balances_along():
    """Stray balances of a deleted account would keep counting in every total."""
    conn = _new_conn()
    account_id = _account(conn)
    accounts.set_balance(conn, account_id, "2026-01-31", 1500.0)
    accounts.set_balance(conn, account_id, "2026-02-28", 1600.0)

    accounts.delete_account(conn, account_id)

    assert accounts.load_account(conn, account_id) is None
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS n FROM account_balances WHERE account_id = ?", (account_id,))
    assert cursor.fetchone()["n"] == 0
    conn.close()


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


def test_balance_roundtrip():
    conn = _new_conn()
    account_id = _account(conn)
    accounts.set_balance(conn, account_id, "2026-01-31", 1234.56)

    balances = accounts.load_balances(conn, account_id)
    assert len(balances) == 1
    assert balances[0]["date"] == "2026-01-31"
    assert balances[0]["balance"] == pytest.approx(1234.56)
    assert balances[0]["source"] == "manual"
    conn.close()


def test_a_second_measurement_on_the_same_day_replaces_the_first():
    """You correct a typo by entering it again, not by stacking."""
    conn = _new_conn()
    account_id = _account(conn)
    accounts.set_balance(conn, account_id, "2026-01-31", 1000.0)
    accounts.set_balance(conn, account_id, "2026-01-31", 1100.0)

    balances = accounts.load_balances(conn, account_id)
    assert len(balances) == 1
    assert balances[0]["balance"] == pytest.approx(1100.0)
    conn.close()


def test_balances_come_back_in_date_order():
    conn = _new_conn()
    account_id = _account(conn)
    for date in ("2026-03-31", "2026-01-31", "2026-02-28"):
        accounts.set_balance(conn, account_id, date, 100.0)

    dates = [s["date"] for s in accounts.load_balances(conn, account_id)]
    assert dates == ["2026-01-31", "2026-02-28", "2026-03-31"]
    conn.close()


def test_between_two_manual_measurements_runs_a_straight_line():
    """A manual measurement is a snapshot. A staircase that stands still for a month
    and then jumps claims that nothing happened for a month; a straight line
    claims the least.
    """
    conn = _new_conn()
    account_id = _account(conn)
    accounts.set_balance(conn, account_id, "2026-01-01", 1000.0)
    accounts.set_balance(conn, account_id, "2026-01-11", 2000.0)

    assert accounts.balance_on(conn, account_id, "2026-01-01") == pytest.approx(1000.0)
    assert accounts.balance_on(conn, account_id, "2026-01-06") == pytest.approx(1500.0)
    assert accounts.balance_on(conn, account_id, "2026-01-11") == pytest.approx(2000.0)
    assert accounts.balance_on(conn, account_id, "2027-01-01") == pytest.approx(2000.0), "na de laatste meting blijft die staan"
    conn.close()


def test_a_balance_from_an_import_stays_flat_until_the_next():
    """A balance from a statement only changes through a transaction, and that is
    then in the statement itself. A sloping line would let money trickle in that
    came in at once.
    """
    conn = _new_conn()
    account_id = _account(conn)
    accounts.set_balance(conn, account_id, "2026-01-01", 1000.0, source="sync")
    accounts.set_balance(conn, account_id, "2026-01-11", 2000.0, source="sync")
    assert accounts.balance_on(conn, account_id, "2026-01-10") == pytest.approx(1000.0)
    conn.close()


def test_before_the_first_measurement_an_account_is_zero():
    """Before the first data the source did not exist for you yet."""
    conn = _new_conn()
    account_id = _account(conn)
    accounts.set_balance(conn, account_id, "2026-01-31", 1000.0)
    assert accounts.balance_on(conn, account_id, "2025-12-31") == 0.0
    conn.close()


def test_total_balance_on_counts_only_active_accounts():
    conn = _new_conn()
    ing = _account(conn)
    bunq = _account(conn, provider="bunq", name="bunq", iban="NL00BUNQ0000000002")
    cash = _account(conn, kind="cash", provider="manual", name="Portemonnee", iban=None)
    accounts.set_balance(conn, ing, "2026-01-31", 1000.0)
    accounts.set_balance(conn, bunq, "2026-01-15", 500.0)
    accounts.set_balance(conn, cash, "2026-01-01", 50.0)

    assert accounts.total_balance_on(conn, "2026-02-01") == pytest.approx(1550.0)

    accounts.update_account(conn, bunq, active=0)
    assert accounts.total_balance_on(conn, "2026-02-01") == pytest.approx(1050.0)
    conn.close()


def test_total_balance_ignores_accounts_without_a_measurement_yet():
    """An account without a measurement counts as unknown, not as zero."""
    conn = _new_conn()
    ing = _account(conn)
    _account(conn, provider="bunq", name="bunq", iban="NL00BUNQ0000000002")
    accounts.set_balance(conn, ing, "2026-01-31", 1000.0)

    assert accounts.total_balance_on(conn, "2026-02-01") == pytest.approx(1000.0)
    conn.close()


def test_last_balance_returns_amount_and_date():
    conn = _new_conn()
    account_id = _account(conn)
    accounts.set_balance(conn, account_id, "2026-01-31", 1000.0)
    accounts.set_balance(conn, account_id, "2026-03-31", 1500.0)

    last = accounts.last_balance(conn, account_id)
    assert last["balance"] == pytest.approx(1500.0)
    assert last["date"] == "2026-03-31"
    assert last["source"] == "manual"
    conn.close()


def test_last_balance_is_none_without_measurements():
    conn = _new_conn()
    assert accounts.last_balance(conn, _account(conn)) is None
    conn.close()


def test_balance_refuses_an_unknown_source():
    conn = _new_conn()
    account_id = _account(conn)
    with pytest.raises(ValueError):
        accounts.set_balance(conn, account_id, "2026-01-31", 1.0, source="gokje")
    conn.close()


@pytest.mark.parametrize("date", ["31-01-2026", "2026-1-31", "gisteren", ""])
def test_balance_refuses_a_date_that_is_not_iso(date):
    """The whole codebase compares dates as text; then the form must be fixed."""
    conn = _new_conn()
    account_id = _account(conn)
    with pytest.raises(ValueError):
        accounts.set_balance(conn, account_id, date, 1.0)
    conn.close()


def test_a_balance_for_an_unknown_account_is_refused():
    conn = _new_conn()
    with pytest.raises(accounts.AccountUnknown):
        accounts.set_balance(conn, 999, "2026-01-31", 1.0)
    conn.close()


# ---------------------------------------------------------------------------
# Separation between users
# ---------------------------------------------------------------------------


def test_accounts_of_two_users_do_not_touch():
    """The same requirement as for transactions: not a single row leaks between databases."""
    alice = _new_conn("alice")
    bob = _new_conn("bob")

    alice_id = _account(alice, name="Alice ING")
    _account(bob, name="Bob ING", iban="NL00BUNQ0000000002", provider="bunq")
    accounts.set_balance(alice, alice_id, "2026-01-31", 1000.0)

    assert [r["name"] for r in accounts.load_accounts(alice)] == ["Alice ING"]
    assert [r["name"] for r in accounts.load_accounts(bob)] == ["Bob ING"]
    assert accounts.total_balance_on(bob, "2026-02-01") == pytest.approx(0.0)

    alice.close()
    bob.close()


def test_the_same_iban_for_two_users_is_allowed():
    """A shared account is not the same as a duplicate."""
    alice = _new_conn("alice")
    bob = _new_conn("bob")
    _account(alice)
    _account(bob)  # same IBAN, different database
    assert len(accounts.load_accounts(alice)) == 1
    assert len(accounts.load_accounts(bob)) == 1
    alice.close()
    bob.close()


# ---------------------------------------------------------------------------
# Debt
# ---------------------------------------------------------------------------


def test_a_debt_is_always_stored_negative():
    """Someone entering their student debt types "39000" and not "-39000".

    Without this rule such a debt counted as 39,000 euros of assets and shot your
    net worth 78,000 euros the wrong way — without an error, because a positive
    number is a valid balance.
    """
    conn = _new_conn()
    debt = _account(conn, kind="debt", provider="manual", name="Studieschuld", iban=None)
    accounts.set_balance(conn, debt, "2026-01-31", 39000.0)
    assert accounts.balance_on(conn, debt, "2026-01-31") == pytest.approx(-39000.0)

    accounts.set_balance(conn, debt, "2026-02-28", -38900.0)
    assert accounts.balance_on(conn, debt, "2026-02-28") == pytest.approx(-38900.0)
    conn.close()


def test_a_debt_lowers_the_total_however_you_enter_it():
    conn = _new_conn()
    bank = _account(conn)
    debt = _account(conn, kind="debt", provider="manual", name="Studieschuld", iban=None)
    accounts.set_balance(conn, bank, "2026-01-31", 10000.0)
    accounts.set_balance(conn, debt, "2026-01-31", 4000.0)

    assert accounts.total_balance_on(conn, "2026-02-01") == pytest.approx(6000.0)
    conn.close()


def test_a_bank_account_may_be_overdrawn():
    """Only a debt is flipped. A current account that is overdrawn really is
    negative, and a positive balance really is positive.
    """
    conn = _new_conn()
    bank = _account(conn)
    accounts.set_balance(conn, bank, "2026-01-31", -75.0)
    accounts.set_balance(conn, bank, "2026-02-28", 100.0)
    assert accounts.balance_on(conn, bank, "2026-01-31") == pytest.approx(-75.0)
    assert accounts.balance_on(conn, bank, "2026-02-28") == pytest.approx(100.0)
    conn.close()
