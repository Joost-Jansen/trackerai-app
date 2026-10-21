"""
Tests for month_periods.py — a month from salary to salary.

The salary days are recognised from the transactions in the salary category; a
month without salary gets a predicted date: the usual day, or in a weekend or
on a holiday the working day before (or after, if your history says so). There
is no salary day in the code.
"""

import sqlite3
from datetime import date

import pytest

from domain import database
from domain.money import accounts, bank_transactions, categorization, month_periods, net_worth


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


@pytest.fixture()
def conn(monkeypatch):
    monkeypatch.setattr(month_periods, "today", lambda: date(2026, 5, 10))
    conn = database.connect("alice")
    database.init_db(conn)
    categorization.seed(conn)
    yield conn
    conn.close()


@pytest.fixture()
def account(conn) -> int:
    return accounts.make_bank_account(conn, kind="bank", provider="manual", name="Bank")


def _tx(conn, account_id, date, amount, category):
    hash_ = f"{date}{amount}{category}"[:40]
    bank_transactions.save(
        conn,
        account_id,
        [
            {
                "date": date,
                "interest_date": None,
                "amount": amount,
                "currency": "EUR",
                "name": "X",
                "counterparty_iban": None,
                "description": "",
                "code": None,
                "kind": None,
                "dedup_hash": hash_,
                "raw": {},
            }
        ],
    )
    conn.execute("UPDATE bank_transactions SET category_auto = ? WHERE dedup_hash = ?", (category, hash_))
    conn.commit()


def _salary(conn, account_id, *dates, amount=-3000.0):
    for d in dates:
        _tx(conn, account_id, d, amount, "Salaris")


# ---------------------------------------------------------------------------
# Working days and predicting
# ---------------------------------------------------------------------------


def test_easter_and_the_holidays_that_depend_on_it():
    assert month_periods._easter(2025) == date(2025, 4, 20)
    assert month_periods._easter(2026) == date(2026, 4, 5)
    days = month_periods.holidays(2026)
    assert date(2026, 4, 3) in days, "Goede Vrijdag"
    assert date(2026, 4, 6) in days, "Tweede Paasdag"
    assert date(2026, 5, 14) in days, "Hemelvaart"
    assert date(2026, 5, 25) in days, "Tweede Pinksterdag"


def test_a_day_in_the_weekend_moves_to_the_friday_before():
    assert month_periods.predict(2026, 2, 21) == date(2026, 2, 20)  # Sat → Fri
    assert month_periods.predict(2026, 6, 21) == date(2026, 6, 19)  # Sun → Fri
    assert month_periods.predict(2026, 4, 21) == date(2026, 4, 21)  # di


def test_a_holiday_also_moves_and_a_weekend_before_it_too():
    """21 April 2025 is Easter Monday; the 20th a Sunday, the 19th a Saturday, the
    18th Good Friday. Then it becomes Thursday the 17th.
    """
    assert month_periods.predict(2025, 4, 21) == date(2025, 4, 17)


def test_paying_later_moves_to_the_monday():
    assert month_periods.predict(2026, 2, 21, "later") == date(2026, 2, 23)


def test_a_shift_does_not_leave_the_month():
    """31 January 2026 is a Saturday; paying later would become 2 February."""
    assert month_periods.predict(2026, 1, 31, "later") == date(2026, 1, 30)


# ---------------------------------------------------------------------------
# Recognising
# ---------------------------------------------------------------------------


def test_recognises_the_salary_day_and_earlier_payment(conn, account):
    _salary(conn, account, "2026-01-21", "2026-02-20", "2026-03-20", "2026-04-21")
    recognised = month_periods.recognise(conn, "Salaris")
    assert recognised.day == 21
    assert recognised.shift == "earlier"


def test_also_recognises_an_employer_that_pays_later(conn, account):
    _salary(conn, account, "2026-01-21", "2026-02-23", "2026-03-23", "2026-04-21")
    assert month_periods.recognise(conn, "Salaris").shift == "later"


def test_another_day_than_the_21st_is_recognised_too(conn, account):
    _salary(conn, account, "2026-01-26", "2026-02-25", "2026-03-25", "2026-04-24")
    assert month_periods.recognise(conn, "Salaris").day == 25


def test_a_small_credit_in_salary_is_not_a_reference_point(conn, account):
    _salary(conn, account, "2026-01-21", "2026-02-20", "2026-03-20")
    _tx(conn, account, "2026-03-03", -30.0, "Salaris")
    assert month_periods.recognise(conn, "Salaris").payments["2026-03"] == date(2026, 3, 20)


def test_holiday_pay_in_the_same_month_does_not_move_the_reference_point(conn, account):
    _salary(conn, account, "2026-03-20", "2026-04-21", "2026-05-21")
    _tx(conn, account, "2026-05-29", -3500.0, "Salaris")
    assert month_periods.recognise(conn, "Salaris").payments["2026-05"] == date(2026, 5, 21)


# ---------------------------------------------------------------------------
# The layout
# ---------------------------------------------------------------------------


def test_calendar_month_by_default(conn, account):
    _salary(conn, account, "2026-01-21", "2026-02-20")
    layout = month_periods.layout(conn)
    assert layout.mode == "calendar"
    assert layout.key("2026-02-19") == "2026-02"
    assert layout.period("2026-02") == ("2026-02-01", "2026-02-28")


def test_with_salary_a_month_runs_from_salary_to_salary(conn, account):
    _salary(conn, account, "2026-01-21", "2026-02-20", "2026-03-20", "2026-04-21")
    month_periods.put(conn, mode="salary")
    layout = month_periods.layout(conn)
    assert layout.mode == "salary"
    assert {"2026-01-21", "2026-02-20", "2026-03-20", "2026-04-21"} <= set(layout.boundaries)
    # Predicted for the months still to come.
    assert {"2026-05-21", "2026-06-19"} <= set(layout.boundaries)

    assert layout.key("2026-02-19") == "2026-01", "de dag vóór het salaris hoort bij de vorige maand"
    assert layout.key("2026-02-20") == "2026-02"
    assert layout.period("2026-02") == ("2026-02-20", "2026-03-19")
    assert layout.start_of("2026-05-10") == "2026-04-21"


def test_without_salary_salary_falls_back_to_the_calendar(conn, account):
    month_periods.put(conn, mode="salary")
    assert month_periods.layout(conn).mode == "calendar"
    assert month_periods.details(conn)["active"] == "calendar"


def test_a_set_day_works_without_a_recognised_salary(conn, account):
    month_periods.put(conn, mode="salary", day=25)
    layout = month_periods.layout(conn)
    assert layout.mode == "salary"
    assert "2026-04-24" in layout.boundaries, "25 april 2026 is een zaterdag"


def test_a_stray_payment_far_from_the_salary_day_is_not_a_boundary(conn, account):
    """One salary on the 3rd does not make a month of two weeks."""
    _salary(conn, account, "2026-01-21", "2026-02-20", "2026-03-03", "2026-04-21")
    month_periods.put(conn, mode="salary")
    boundaries = month_periods.layout(conn).boundaries
    assert "2026-03-03" not in boundaries and "2026-03-20" in boundaries


def test_the_description_says_what_was_recognised(conn, account):
    _salary(conn, account, "2026-01-21", "2026-02-20", "2026-03-20", "2026-04-21")
    month_periods.put(conn, mode="salary")
    b = month_periods.details(conn)
    assert b["recognised"] == {"day": 21, "count": 4, "last": "2026-04-21"}
    assert b["current"] == {"start": "2026-04-21", "end": "2026-05-20"}


def test_invalid_settings_are_refused(conn):
    with pytest.raises(ValueError):
        month_periods.put(conn, mode="week")
    with pytest.raises(ValueError):
        month_periods.put(conn, day=32)
    with pytest.raises(ValueError):
        month_periods.put(conn, category="Bestaat niet")


# ---------------------------------------------------------------------------
# What calculates with it
# ---------------------------------------------------------------------------


def test_month_totals_follow_the_salary_month(conn, account):
    _salary(conn, account, "2026-01-21", "2026-02-20")
    _tx(conn, account, "2026-02-05", 100.0, "Supermarkt")
    _tx(conn, account, "2026-02-19", 50.0, "Supermarkt")
    _tx(conn, account, "2026-02-25", 20.0, "Supermarkt")

    calendar = {m["month"]: m for m in net_worth.per_month(conn)}
    assert calendar["2026-02"]["spending"] == pytest.approx(170.0)

    month_periods.put(conn, mode="salary")
    salary = {m["month"]: m for m in net_worth.per_month(conn)}
    assert salary["2026-01"]["spending"] == pytest.approx(150.0)
    assert salary["2026-01"]["income"] == pytest.approx(3000.0)
    assert salary["2026-02"]["spending"] == pytest.approx(20.0)
    assert net_worth.spending_per_month_per_group(conn)["2026-01"]


def test_a_salary_month_is_complete_when_the_export_covers_it_fully(conn, account):
    """The month from 21 January to 19 February is complete with an export up to and
    including 19 February, even though the calendar month February is not.
    """
    _salary(conn, account, "2026-01-21")
    _tx(conn, account, "2026-01-02", 10.0, "Supermarkt")
    _tx(conn, account, "2026-02-19", 10.0, "Supermarkt")
    month_periods.put(conn, mode="salary", day=21)
    months = {m["month"]: m for m in net_worth.per_month(conn)}
    assert months["2026-01"]["complete"] is True
