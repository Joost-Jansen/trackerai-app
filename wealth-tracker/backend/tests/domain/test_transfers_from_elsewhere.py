"""
A savings account you cannot connect runs on with your current account.

After an account's last own data (an export, a balance) its balance follows
the bookings on your other accounts that name it: through its IBAN as
counterparty account, or through its account number in the description (ING:
"To Oranje spaarrekening H12284579"). Nothing per bank; only what the account
itself has in numbers.
"""

import pytest

from app.services import account_service
from domain import database
from domain.money import accounts, bank_transactions, net_worth


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


@pytest.fixture()
def conn():
    conn = database.connect("alice")
    database.init_db(conn)
    yield conn
    conn.close()


PAY = "NL00BANK0000000001"


@pytest.fixture()
def pay(conn) -> int:
    return accounts.make_bank_account(conn, kind="bank", provider="ing", name="Betaalrekening", iban=PAY)


@pytest.fixture()
def savings(conn) -> int:
    r = accounts.make_bank_account(conn, kind="bank", provider="ing", name="Oranje spaarrekening", external_id="H12284579")
    accounts.set_balance(conn, r, "2026-01-31", 1000.0, source="sync")
    return r


def _tx(conn, account_id, date, amount, description="", counterparty=None, name="X"):
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
                "counterparty_iban": counterparty,
                "description": description,
                "code": None,
                "kind": None,
                "dedup_hash": f"{account_id}{date}{amount}{description}"[:40],
                "raw": {},
            }
        ],
    )


def test_to_and_from_the_savings_account_after_the_last_export(conn, pay, savings):
    _tx(conn, pay, "2026-02-05", 200.0, "To Oranje spaarrekening H12284579")
    _tx(conn, pay, "2026-02-20", -50.0, "From Oranje spaarrekening H12284579")
    assert accounts.balance_on(conn, savings, "2026-02-04") == 1000.0
    assert accounts.balance_on(conn, savings, "2026-02-05") == 1200.0
    assert accounts.balance_on(conn, savings, "2026-03-01") == 1150.0


def test_what_happened_before_the_last_export_is_already_included(conn, pay, savings):
    _tx(conn, pay, "2026-01-15", 300.0, "To Oranje spaarrekening H12284579")
    assert accounts.balance_on(conn, savings, "2026-02-15") == 1000.0


def test_a_new_balance_takes_over_again(conn, pay, savings):
    _tx(conn, pay, "2026-02-05", 200.0, "To Oranje spaarrekening H12284579")
    _tx(conn, pay, "2026-02-20", -50.0, "From Oranje spaarrekening H12284579")
    accounts.set_balance(conn, savings, "2026-02-10", 5000.0, source="sync")
    assert accounts.balance_on(conn, savings, "2026-03-01") == 4950.0


def test_recognised_by_the_counterparty_iban(conn, pay):
    bunq = accounts.make_bank_account(conn, kind="bank", provider="bunq", name="bunq sparen", iban="NL18BUNQ0000000018")
    accounts.set_balance(conn, bunq, "2026-01-31", 100.0)
    _tx(conn, pay, "2026-02-05", 75.0, "Sparen", counterparty="NL18 BUNQ 0000 0000 18")
    assert accounts.balance_on(conn, bunq, "2026-03-01") == 175.0


def test_a_number_inside_another_number_does_not_count(conn, pay, savings):
    _tx(conn, pay, "2026-02-05", 200.0, "Kenmerk XH122845790")
    assert accounts.balance_on(conn, savings, "2026-03-01") == 1000.0


def test_a_broker_does_not_move_along(conn, pay):
    broker = accounts.make_bank_account(conn, kind="broker", provider="manual", name="Broker", iban="DE00123456780000000020")
    accounts.set_balance(conn, broker, "2026-01-31", 100.0)
    _tx(conn, pay, "2026-02-05", 500.0, "Storting", counterparty="DE00123456780000000020")
    assert accounts.balance_on(conn, broker, "2026-03-01") == 100.0


def test_the_overview_shows_the_carried_forward_balance(conn, pay, savings):
    _tx(conn, pay, "2026-02-05", 200.0, "To Oranje spaarrekening H12284579")
    account = next(r for r in account_service.overview(conn) if r["id"] == savings)
    assert account["balance"] == 1200.0
    assert account["balance_source"] == "transfer" and account["balance_date"] == "2026-02-05"


def test_saving_does_not_lower_net_worth(conn, pay, savings):
    """From your current account to your savings account: you are just as rich."""
    _tx(conn, pay, "2026-02-05", 200.0, "To Oranje spaarrekening H12284579")
    accounts.set_balance(conn, pay, "2026-03-01", 800.0)
    series = {p["d"]: p["net"] for p in net_worth.series(conn, [])["points"]}
    assert series["2026-02-04"] == series["2026-02-06"] == 2000.0


def test_a_current_account_does_not_move_along_with_your_savings_account(conn, pay):
    """The export of your current account stops in February; your savings account
    shows deposits until August. The current account stays at its last state: only
    the deposits, without salary and groceries, is half a picture.
    """
    _tx(conn, pay, "2026-02-01", 42.5, "Boodschappen", name="SUPERMARKT")
    accounts.set_balance(conn, pay, "2026-02-20", 3000.0, source="sync")
    savings = accounts.make_bank_account(conn, kind="bank", provider="ing", name="Spaar", external_id="A11122233")
    _tx(conn, savings, "2026-08-25", -350.0, "Transfer from current account", counterparty=PAY)
    assert accounts.balance_on(conn, pay, "2026-09-01") == 3000.0


def test_a_savings_account_with_its_own_bookings_does_move_along(conn, pay):
    """Also a savings account whose transactions you uploaded: it only moves money
    with your own accounts, so your current account tells the rest.
    """
    from domain.money import categorization

    categorization.seed(conn)
    savings = accounts.make_bank_account(conn, kind="bank", provider="ing", name="Spaar", external_id="H12284579")
    _tx(conn, savings, "2026-01-10", -500.0, "Transfer from current account", counterparty=PAY)
    conn.execute("UPDATE bank_transactions SET category_auto = 'Naar spaarrekening' WHERE account_id = ?", (savings,))
    conn.commit()
    accounts.set_balance(conn, savings, "2026-01-31", 1000.0, source="sync")
    _tx(conn, pay, "2026-02-05", 200.0, "To Oranje spaarrekening H12284579")
    assert accounts.balance_on(conn, savings, "2026-03-01") == 1200.0
