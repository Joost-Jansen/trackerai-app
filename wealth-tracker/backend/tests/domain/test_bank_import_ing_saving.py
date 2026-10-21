"""
Tests for the ING savings exports and the semicolon download of the current account.

ING gives three kinds of files that count for net worth:

  * the transactions of the current account — with commas (without balance) or
    with semicolons (with the balance after each booking);
  * the transactions of all savings accounts together, with the balance after
    each booking;
  * the balance overview of the savings accounts: one state per day.

The fixtures are made up in the shape of the real downloads; there are no real
account numbers or amounts in them.
"""

from domain.money import bank_providers as bank
from domain.money.bank_providers import base

PAY_COMMA_HEADER = (
    '"Date","Name / Description","Account","Counterparty","Code","Debit/credit","Amount (EUR)","Transaction type","Notifications"'
)
PAY_SEMICOLON_HEADER = (
    '"Date";"Name / Description";"Account";"Counterparty";"Code";'
    '"Debit/credit";"Amount (EUR)";"Transaction type";"Notifications";'
    '"Resulting balance";"Tag"'
)
SAVINGS_HEADER = (
    '"Date";"Description";"Account";"Account name";"Counterparty";"Debit/credit";'
    '"Amount";"Currency";"Transaction type";"Notifications";"Resulting balance"'
)
BALANCE_HEADER = '"Date";"Account";"Account name";"Currency";"Book balance"'

IBAN = "NL00INGB0000000001"


def _write(tmp_path, name, header, *rows):
    path = tmp_path / name
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return str(path)


def _savings(date, number, direction, amount, balance, kind="Deposit", counterparty=IBAN, oms=None):
    oms = oms or ("Interest" if kind == "Interest" else f"Transfer from current account {IBAN}")
    return f'"{date}";"{oms}";"{number}";"savings account";"{counterparty}";"{direction}";"{amount}";"EUR";"{kind}";"";"{balance}"'


# ---------------------------------------------------------------------------
# Recognising
# ---------------------------------------------------------------------------


def test_three_kinds_of_files_are_recognised(tmp_path):
    pay = _write(
        tmp_path,
        "b.csv",
        PAY_SEMICOLON_HEADER,
        f'"20260220";"SUPERMARKT";"{IBAN}";"";"BA";"Debit";"42,50";"Payment terminal";"x";"500,00";""',
    )
    savings = _write(tmp_path, "s.csv", SAVINGS_HEADER, _savings("2026-08-25", "A 111-22233", "Credit", "350,00", "1.350,00"))
    balance = _write(tmp_path, "o.csv", BALANCE_HEADER, '"2026-09-03";"A11122233";"Oranje Spaarrekening";"EUR";"1.350,00"')

    assert bank.read_export(pay)["kind"] == "transactions"
    assert bank.read_export(savings)["kind"] == "transactions"
    assert bank.read_export(balance)["kind"] == "balances"
    assert {bank.read_export(p)["provider"] for p in (pay, savings, balance)} == {"ing"}


def test_the_semicolon_download_gives_the_balance_after_each_booking(tmp_path):
    path = _write(
        tmp_path,
        "b.csv",
        PAY_SEMICOLON_HEADER,
        f'"20260220";"WERKGEVER B.V.";"{IBAN}";"NL02ABNA0123456789";"OV";"Credit";"2500,00";"Online Banking";"Salaris";"3.000,00";""',
    )
    row = bank.read_export(path)["rows"][0]
    assert row["amount"] == -2500.0
    assert row["balance_after"] == 3000.0
    assert row["account_iban"] == IBAN


def test_the_comma_variant_has_no_balance(tmp_path):
    path = _write(tmp_path, "b.csv", PAY_COMMA_HEADER, f'"20260220","SUPERMARKT","{IBAN}","","BA","Debit","42,50","Payment terminal","x"')
    assert bank.read_export(path)["rows"][0]["balance_after"] is None


def test_comma_and_semicolon_give_the_same_fingerprint(tmp_path):
    """Whoever switches to the download with balance gets no duplicate transactions."""
    comma = _write(
        tmp_path, "k.csv", PAY_COMMA_HEADER, f'"20260220","SUPERMARKT","{IBAN}","","BA","Debit","42,50","Payment terminal","Card 001"'
    )
    point = _write(
        tmp_path,
        "p.csv",
        PAY_SEMICOLON_HEADER,
        f'"20260220";"SUPERMARKT";"{IBAN}";"";"BA";"Debit";"42,50";"Payment terminal";"Card 001";"500,00";""',
    )
    assert bank.read_export(comma)["rows"][0]["dedup_hash"] == bank.read_export(point)["rows"][0]["dedup_hash"]


def test_an_existing_comma_export_keeps_its_old_fingerprint(tmp_path):
    """The hash has not changed for what was already imported."""
    path = _write(
        tmp_path, "k.csv", PAY_COMMA_HEADER, f'"20260220","SUPERMARKT","{IBAN}","","BA","Debit","42,50","Payment terminal","Card 001"'
    )
    row = bank.read_export(path)["rows"][0]
    assert row["dedup_hash"] == base.dedup_hash("2026-02-20", 42.5, "SUPERMARKT", "Card 001", 1)


# ---------------------------------------------------------------------------
# Savings accounts
# ---------------------------------------------------------------------------


def test_the_account_number_is_the_same_in_both_downloads(tmp_path):
    savings = _write(tmp_path, "s.csv", SAVINGS_HEADER, _savings("2026-08-25", "A 111-22233", "Credit", "350,00", "1.350,00"))
    balance = _write(tmp_path, "o.csv", BALANCE_HEADER, '"2026-09-03";"A11122233";"Oranje Spaarrekening";"EUR";"1.350,00"')
    assert bank.read_export(savings)["rows"][0]["account_number"] == "A11122233"
    assert bank.read_export(balance)["rows"][0]["account_number"] == "A11122233"


def test_savings_transactions_follow_the_sign_convention(tmp_path):
    path = _write(
        tmp_path,
        "s.csv",
        SAVINGS_HEADER,
        _savings("2026-08-25", "A 111-22233", "Credit", "350,00", "1.350,00"),
        _savings("2026-08-24", "A 111-22233", "Debit", "100,00", "1.000,00", kind="Withdrawal"),
    )
    at, af = bank.read_export(path)["rows"]
    assert at["amount"] == -350.0 and af["amount"] == 100.0
    assert at["counterparty_iban"] == IBAN
    assert at["account_iban"] is None


def test_the_same_transfer_on_two_savings_accounts_is_not_a_duplicate(tmp_path):
    path = _write(
        tmp_path,
        "s.csv",
        SAVINGS_HEADER,
        _savings("2026-08-25", "A 111-22233", "Credit", "50,00", "50,00"),
        _savings("2026-08-25", "B 444-55566", "Credit", "50,00", "50,00"),
    )
    a, b = bank.read_export(path)["rows"]
    assert a["dedup_hash"] != b["dedup_hash"]


def test_the_fingerprint_does_not_depend_on_the_other_accounts_in_the_download(tmp_path):
    """First everything together, later one account separately: the same rows recognise themselves."""
    together = _write(
        tmp_path,
        "together.csv",
        SAVINGS_HEADER,
        _savings("2026-08-25", "B 444-55566", "Credit", "50,00", "50,00"),
        _savings("2026-08-25", "A 111-22233", "Credit", "50,00", "50,00"),
    )
    only_a = _write(tmp_path, "a.csv", SAVINGS_HEADER, _savings("2026-08-25", "A 111-22233", "Credit", "50,00", "50,00"))
    from_together = next(r for r in bank.read_export(together)["rows"] if r["account_number"] == "A11122233")
    assert from_together["dedup_hash"] == bank.read_export(only_a)["rows"][0]["dedup_hash"]


def test_another_currency_is_skipped_and_reported(tmp_path):
    row = _savings("2026-08-25", "A 111-22233", "Credit", "50,00", "50,00").replace('"EUR"', '"USD"')
    skipped = []
    assert bank.read_export(_write(tmp_path, "s.csv", SAVINGS_HEADER, row), skipped)["rows"] == []
    assert "USD" in skipped[0]["reason"]


def test_read_refuses_a_balance_overview(tmp_path):
    """The old entry point gives transactions; an overview with states does not belong there."""
    import pytest

    path = _write(tmp_path, "o.csv", BALANCE_HEADER, '"2026-09-03";"A11122233";"Oranje Spaarrekening";"EUR";"1,00"')
    with pytest.raises(bank.UnknownFormat):
        bank.read(path)
