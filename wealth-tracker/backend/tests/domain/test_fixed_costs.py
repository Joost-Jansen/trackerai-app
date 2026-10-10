"""
Tests for fixed_costs.py — what comes back every month.

The pattern is the proof: in at least three months, roughly monthly, roughly
the same amount. Nothing per shop.
"""

from datetime import date

import pytest

from domain.money import bank_transactions
from domain.money import categorization
from domain import database
from domain.money import accounts
from domain.money import fixed_costs

PRESENT_DAY = date(2026, 9, 14)


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


@pytest.fixture()
def conn():
    conn = database.connect("alice")
    database.init_db(conn)
    categorization.seed(conn)
    yield conn
    conn.close()


@pytest.fixture()
def account(conn):
    return accounts.make_bank_account(conn, kind="bank", provider="manual", name="Bank")


def _tx(conn, account_id, date, amount, name):
    bank_transactions.save(conn, account_id, [{
        "date": date, "interest_date": None, "amount": amount, "currency": "EUR", "name": name,
        "counterparty_iban": None, "description": "", "code": None, "kind": None,
        "dedup_hash": f"{account_id}{date}{amount}{name}"[:40], "raw": {},
    }])


def _labels(conn):
    categorization.relabel(conn, everything=True)


def _names(conn, **kw):
    return [v["name"] for v in fixed_costs.find(conn, present_day=PRESENT_DAY, **kw)]


def test_a_monthly_subscription_is_a_fixed_cost(conn, account):
    for month in ("04", "05", "06", "07", "08", "09"):
        _tx(conn, account, f"2026-{month}-03", 12.99, "NETFLIX.COM")
    _labels(conn)
    [netflix] = fixed_costs.find(conn, present_day=PRESENT_DAY)
    assert netflix["name"] == "NETFLIX.COM" and netflix["amount"] == 12.99
    assert netflix["category"] == "Media & software"
    assert not netflix["stopped"]


def test_the_weekly_supermarket_is_not_a_fixed_cost(conn, account):
    for month in ("06", "07", "08"):
        for day in ("02", "09", "16", "23"):
            _tx(conn, account, f"2026-{month}-{day}", 40.0, "ALBERT HEIJN")
    _labels(conn)
    assert _names(conn) == []


def test_a_web_shop_with_varying_amounts_is_not(conn, account):
    for month, amount in (("06", 12.0), ("07", 80.0), ("08", 35.0), ("09", 150.0)):
        _tx(conn, account, f"2026-{month}-10", amount, "BOL.COM")
    _labels(conn)
    assert _names(conn) == []


def test_a_card_number_in_the_name_does_not_make_it_different(conn, account):
    for i, month in enumerate(("06", "07", "08", "09")):
        _tx(conn, account, f"2026-{month}-05", 29.5, f"SPORTCITY 00{i}23")
    _labels(conn)
    assert len(_names(conn)) == 1


def test_new_and_stopped(conn, account):
    for month in ("06", "07", "08", "09"):
        _tx(conn, account, f"2026-{month}-01", 9.99, "SPOTIFY")
    for month in ("01", "02", "03", "04"):
        _tx(conn, account, f"2026-{month}-01", 30.0, "BASIC-FIT")
    _labels(conn)
    charges = {v["name"]: v for v in fixed_costs.find(conn, present_day=PRESENT_DAY)}
    assert charges["SPOTIFY"]["is_new"] and not charges["SPOTIFY"]["stopped"]
    assert charges["BASIC-FIT"]["stopped"]


def test_only_the_chosen_account(conn, account):
    other = accounts.make_bank_account(conn, kind="bank", provider="manual", name="Andere")
    for month in ("06", "07", "08", "09"):
        _tx(conn, other, f"2026-{month}-01", 9.99, "SPOTIFY")
    _labels(conn)
    assert _names(conn, account_ids={account}) == []
    assert _names(conn, account_ids={other}) == ["SPOTIFY"]


def test_internal_money_is_not_a_fixed_cost(conn, account):
    for month in ("06", "07", "08", "09"):
        _tx(conn, account, f"2026-{month}-25", 500.0, "ORANJE SPAARREKENING")
    _labels(conn)
    assert _names(conn) == []



def test_not_fixed_wins_over_the_pattern(conn, account):
    for month in ("04", "05", "06", "07", "08", "09"):
        _tx(conn, account, f"2026-{month}-03", 25.0, "Cafe De Kroeg")
    _labels(conn)
    assert _names(conn) == ["Cafe De Kroeg"]
    fixed_costs.set_choice(conn, "Cafe De Kroeg", False)
    assert _names(conn) == []
    b = fixed_costs.admin(conn, present_day=PRESENT_DAY)
    assert [v["name"] for v in b["excluded"]] == ["Cafe De Kroeg"]
    assert b["candidates"] == []


def test_fixed_wins_over_the_pattern(conn, account):
    # A varying amount *and* a varying day: the detection skips it.
    for day, amount in [("2026-06-02", 40.0), ("2026-07-19", 95.0), ("2026-08-08", 60.0)]:
        _tx(conn, account, day, amount, "Energieleverancier")
    _labels(conn)
    assert _names(conn) == []
    assert "Energieleverancier" in [v["name"] for v in fixed_costs.admin(conn, present_day=PRESENT_DAY)["candidates"]]

    fixed_costs.set_choice(conn, "Energieleverancier", True)
    [v] = fixed_costs.find(conn, present_day=PRESENT_DAY)
    assert v["name"] == "Energieleverancier" and v["manual"] is True
    assert v["amount"] == 60.0

    fixed_costs.set_choice(conn, "Energieleverancier", None)
    assert _names(conn) == []


def test_the_choice_applies_to_the_name_without_numbers(conn, account):
    for month in ("04", "05", "06", "07"):
        _tx(conn, account, f"2026-{month}-03", 10.0, f"Kroeg {month}")
    _labels(conn)
    fixed_costs.set_choice(conn, "Kroeg 99", False)
    assert _names(conn) == []


def test_groceries_are_not_a_suggestion(conn, account):
    for month in ("06", "07", "08"):
        for day in ("02", "09", "16", "23"):
            _tx(conn, account, f"2026-{month}-{day}", 30.0, "Supermarkt")
    _labels(conn)
    assert fixed_costs.admin(conn, present_day=PRESENT_DAY)["candidates"] == []
