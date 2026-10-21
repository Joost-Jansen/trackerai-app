"""
Tests for debt_schedule.py — interest and repayment that run on by themselves.

At every reference point *after* the last measurement: state + state × interest
/ 12 − repayment. An own measurement is the new starting point, so an extra
repayment stays just entering a balance.
"""

from datetime import date

import pytest

from domain import database
from domain.money import accounts, bank_transactions, categorization, debt_schedule, month_periods


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


@pytest.fixture()
def conn(monkeypatch):
    monkeypatch.setattr(month_periods, "today", lambda: date(2026, 4, 15))
    monkeypatch.setattr(debt_schedule, "today", lambda: "2026-04-15")
    conn = database.connect("alice")
    database.init_db(conn)
    categorization.seed(conn)
    yield conn
    conn.close()


@pytest.fixture()
def debt(conn) -> int:
    r = accounts.make_bank_account(conn, kind="debt", provider="manual", name="DUO")
    accounts.set_balance(conn, r, "2026-01-01", 20000)
    return r


def test_without_a_schedule_nothing_changes(conn, debt):
    assert accounts.balance_on(conn, debt, "2026-04-15") == -20000


def test_every_month_interest_is_added_and_repayment_subtracted(conn, debt):
    debt_schedule.put(conn, debt, interest=2.4, repayment=100, from_date="2026-01-01")
    # 1 Feb: 20000 + 40.00 − 100 = 19940.00
    # 1 Mar: 19940 + 39.88 − 100 = 19879.88
    # 1 Apr: 19879.88 + 39.76 − 100 = 19819.64
    assert accounts.balance_on(conn, debt, "2026-02-10") == pytest.approx(-19940.00)
    assert accounts.balance_on(conn, debt, "2026-04-15") == pytest.approx(-19819.64)
    calculated = [p for p in accounts.balances_for_series(conn, debt) if p["source"] == "schedule"]
    assert [p["date"] for p in calculated] == ["2026-02-01", "2026-03-01", "2026-04-01"]
    assert calculated[0]["interest"] == 40.0 and calculated[0]["repayment"] == 100.0


def test_an_own_measurement_is_the_new_starting_point(conn, debt):
    """An extra repayment: you enter the balance and the schedule runs on from there."""
    debt_schedule.put(conn, debt, interest=2.4, repayment=100, from_date="2026-01-01")
    accounts.set_balance(conn, debt, "2026-02-15", 15000)
    assert accounts.balance_on(conn, debt, "2026-02-10") == pytest.approx(-19940.00)
    assert accounts.balance_on(conn, debt, "2026-02-20") == pytest.approx(-15000.00)
    assert accounts.balance_on(conn, debt, "2026-04-15") == pytest.approx(-14859.86)


def test_on_the_day_of_a_measurement_the_schedule_does_not_calculate(conn, debt):
    debt_schedule.put(conn, debt, interest=2.4, repayment=100, from_date="2026-01-01")
    accounts.set_balance(conn, debt, "2026-03-01", 18000)
    assert accounts.balance_on(conn, debt, "2026-03-01") == pytest.approx(-18000.00)


def test_only_from_the_set_date(conn, debt):
    debt_schedule.put(conn, debt, interest=2.4, repayment=100, from_date="2026-03-01")
    assert accounts.balance_on(conn, debt, "2026-02-10") == pytest.approx(-20000.00)
    assert accounts.balance_on(conn, debt, "2026-04-15") == pytest.approx(-19879.88)


def test_not_beyond_today(conn, debt):
    debt_schedule.put(conn, debt, interest=0, repayment=100, from_date="2026-01-01")
    assert accounts.balances_for_series(conn, debt)[-1]["date"] == "2026-04-01"


def test_a_repaid_debt_stays_at_zero(conn, debt):
    accounts.set_balance(conn, debt, "2026-01-01", 150)
    debt_schedule.put(conn, debt, interest=0, repayment=100, from_date="2026-01-01")
    assert accounts.balance_on(conn, debt, "2026-04-15") == 0


def test_with_the_salary_month_on_the_day_of_the_salary(conn, debt):
    bank = accounts.make_bank_account(conn, kind="bank", provider="manual", name="Bank")
    for day in ("2026-01-21", "2026-02-20"):
        bank_transactions.save(
            conn,
            bank,
            [
                {
                    "date": day,
                    "interest_date": None,
                    "amount": -3000.0,
                    "currency": "EUR",
                    "name": "WERKGEVER",
                    "counterparty_iban": None,
                    "description": "",
                    "code": None,
                    "kind": None,
                    "dedup_hash": day,
                    "raw": {},
                }
            ],
        )
    conn.execute("UPDATE bank_transactions SET category_auto = 'Salaris'")
    conn.commit()
    month_periods.put(conn, mode="salary")
    debt_schedule.put(conn, debt, interest=0, repayment=100, from_date="2026-01-01")

    calculated = [p["date"] for p in accounts.balances_for_series(conn, debt) if p["source"] == "schedule"]
    assert calculated == ["2026-01-21", "2026-02-20", "2026-03-20"], "20 maart: de 21e is een zaterdag"


def test_without_interest_and_repayment_the_schedule_goes_away(conn, debt):
    debt_schedule.put(conn, debt, interest=2.4, repayment=100, from_date="2026-01-01")
    debt_schedule.put(conn, debt, interest=None, repayment=None, from_date="2026-01-01")
    assert debt_schedule.load(conn, debt) is None


def test_nonsense_is_refused(conn, debt):
    with pytest.raises(ValueError):
        debt_schedule.put(conn, debt, interest=-1, repayment=100, from_date="2026-01-01")
    with pytest.raises(ValueError):
        debt_schedule.put(conn, debt, interest=2, repayment=-5, from_date="2026-01-01")
    with pytest.raises(ValueError):
        debt_schedule.put(conn, debt, interest=2, repayment=5, from_date="1 januari")


def test_deleting_an_account_cleans_up_its_schedule(conn, debt):
    debt_schedule.put(conn, debt, interest=2.4, repayment=100, from_date="2026-01-01")
    accounts.delete_account(conn, debt)
    assert debt_schedule.load(conn, debt) is None
