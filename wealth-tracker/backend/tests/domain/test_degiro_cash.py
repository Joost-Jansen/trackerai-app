"""
Tests for degiro_cash.py — the money that sits at DeGiro but is not invested.

The portfolio counts what your holdings are worth. The cash on your DeGiro
account — a deposit not invested yet, a dividend that was paid out — it does
not count. That is not a rounding matter: on the real data there was well over
15,000 euros in January 2026, and it was missing from net worth entirely.

DeGiro's account statement keeps a running balance itself. This file pins down
how we read it: the last EUR balance per day.

The fixtures are made up in the shape of the real export (in Dutch, the
currency in the column `Saldo` and the amount in the unnamed column after it,
newest row on top).
"""

import sqlite3

import pandas as pd
import pytest

from domain import database
from domain.imports import degiro_cash
from domain.money import accounts


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


COLUMNS = [
    "Datum",
    "Tijd",
    "Valutadatum",
    "Product",
    "ISIN",
    "Omschrijving",
    "FX",
    "Mutatie",
    "Unnamed: 8",
    "Saldo",
    "Unnamed: 10",
    "Order Id",
]


def _row(date, time, balance, currency="EUR", description="Dividend"):
    return {
        "Datum": date,
        "Tijd": time,
        "Valutadatum": date,
        "Product": "",
        "ISIN": "",
        "Omschrijving": description,
        "FX": "",
        "Mutatie": currency,
        "Unnamed: 8": 0.0,
        "Saldo": currency,
        "Unnamed: 10": balance,
        "Order Id": "",
    }


def _overview(tmp_path, *rows) -> str:
    path = tmp_path / "Account.xlsx"
    pd.DataFrame(list(rows), columns=COLUMNS).to_excel(path, index=False)
    return str(path)


def _conn() -> sqlite3.Connection:
    conn = database.connect("alice")
    database.init_db(conn)
    return conn


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_the_last_balance_of_each_day(tmp_path):
    path = _overview(
        tmp_path,
        # Newest on top, as DeGiro exports.
        _row("02-01-2026", "15:00", 1200.0),
        _row("02-01-2026", "09:00", 1100.0),
        _row("01-01-2026", "12:00", 1000.0),
    )
    assert degiro_cash.read(path) == [
        {"date": "2026-01-01", "balance": 1000.0},
        {"date": "2026-01-02", "balance": 1200.0},
    ]


def test_at_equal_time_the_top_row_wins(tmp_path):
    """DeGiro puts the newest row on top. Two bookings in the same minute can
    therefore be ordered by their place in the file.
    """
    path = _overview(
        tmp_path,
        _row("01-01-2026", "12:00", 900.0, description="Koop"),
        _row("01-01-2026", "12:00", 1000.0, description="Storting"),
    )
    assert degiro_cash.read(path) == [{"date": "2026-01-01", "balance": 900.0}]


def test_euros_only(tmp_path):
    """A USD balance is a different number in a different currency; adding them up
    would count dollars as euros.
    """
    path = _overview(
        tmp_path,
        _row("01-01-2026", "12:00", 50.0, currency="USD"),
        _row("01-01-2026", "11:00", 1000.0),
    )
    assert degiro_cash.read(path) == [{"date": "2026-01-01", "balance": 1000.0}]


def test_rows_without_balance_are_skipped(tmp_path):
    path = _overview(
        tmp_path,
        _row("01-01-2026", "12:00", None),
        _row("01-01-2026", "11:00", 1000.0),
    )
    assert degiro_cash.read(path) == [{"date": "2026-01-01", "balance": 1000.0}]


def test_a_negative_balance_stays_negative(tmp_path):
    """DeGiro is sometimes briefly negative: a purchase was debited before the
    deposit from the cash account came in. That is DeGiro's own number.
    """
    path = _overview(tmp_path, _row("19-03-2026", "12:00", -500.0))
    assert degiro_cash.read(path) == [{"date": "2026-03-19", "balance": -500.0}]


def test_an_amount_as_text_with_a_comma_is_read(tmp_path):
    path = _overview(tmp_path, _row("01-01-2026", "12:00", "1.234,56"))
    assert degiro_cash.read(path) == [{"date": "2026-01-01", "balance": 1234.56}]


# ---------------------------------------------------------------------------
# Geldbewegingen
# ---------------------------------------------------------------------------


def _movement(date, time, entry, balance, description="x"):
    """A row with an EUR change; mutation=None is a row without an amount."""
    return {
        "Datum": date,
        "Tijd": time,
        "Valutadatum": date,
        "Product": "",
        "ISIN": "",
        "Omschrijving": description,
        "FX": "",
        "Mutatie": "EUR" if entry is not None else "",
        "Unnamed: 8": entry,
        "Saldo": "EUR",
        "Unnamed: 10": balance,
        "Order Id": "",
    }


def test_a_shift_within_the_broker_is_not_a_movement(tmp_path):
    """Deposit +24,000; the broker passes it on (−24,000) and counts it in the
    balance again in the same minute, with a row without an amount. Only the
    deposit is money that came in.
    """
    path = _overview(
        tmp_path,
        # Newest on top, as DeGiro exports.
        _movement("18-07-2025", "03:22", None, 24212.52),
        _movement("18-07-2025", "03:22", -24000.0, 212.52),
        _movement("17-07-2025", "23:37", 24000.0, 24212.52),
    )
    assert [(m["date"], m["amount"]) for m in degiro_cash.read_entries(path)] == [("2025-07-17", 24000.0)]


def test_a_real_withdrawal_stays_a_movement(tmp_path):
    """No restore in the balance after it: then the money really went out."""
    path = _overview(
        tmp_path,
        _movement("07-11-2025", "22:47", -69209.08, 0.0),
        _movement("05-11-2025", "10:00", 69209.08, 69209.08),
    )
    assert sorted(m["amount"] for m in degiro_cash.read_entries(path)) == [-69209.08, 69209.08]


# ---------------------------------------------------------------------------
# Storing
# ---------------------------------------------------------------------------


def test_importing_creates_an_account_on_the_investments_stack(tmp_path):
    """Cash at your broker belongs with your investments, as in the old bookkeeping,
    where "DeGiro inleg" already included the uninvested deposit.
    """
    conn = _conn()
    path = _overview(tmp_path, _row("02-01-2026", "12:00", 1200.0), _row("01-01-2026", "12:00", 1000.0))

    report = degiro_cash.import_file(conn, path)

    assert report["days"] == 2
    account = accounts.load_account(conn, report["account"]["id"])
    assert account["kind"] == "broker"
    assert account["provider"] == "degiro"
    assert accounts.balance_on(conn, account["id"], "2026-01-15") == pytest.approx(1200.0)
    assert {s["source"] for s in accounts.load_balances(conn, account["id"])} == {"sync"}
    conn.close()


def test_importing_twice_creates_no_second_account(tmp_path):
    conn = _conn()
    path = _overview(tmp_path, _row("01-01-2026", "12:00", 1000.0))
    degiro_cash.import_file(conn, path)
    degiro_cash.import_file(conn, path)

    cash = [r for r in accounts.load_accounts(conn) if r["provider"] == "degiro"]
    assert len(cash) == 1
    assert len(accounts.load_balances(conn, cash[0]["id"])) == 1
    conn.close()


def test_an_overview_without_a_euro_balance_creates_nothing(tmp_path):
    """No number is not zero: then no account with a zero balance is created either."""
    conn = _conn()
    path = _overview(tmp_path, _row("01-01-2026", "12:00", 50.0, currency="USD"))
    assert degiro_cash.import_file(conn, path)["days"] == 0
    assert accounts.load_accounts(conn) == []
    conn.close()
