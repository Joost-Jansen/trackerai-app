"""
Tests for bank_providers/ — reading bank exports.

Two banks, two shapes, one normalised row. ING puts the direction in a
separate column and the amount always positive; bunq puts the sign in the
amount. Both end up here on the same convention as the rest of the books:
**spending positive, income negative**.

The fixtures here are made up, not real. They have exactly the columns and the
notation of the real exports (including bunq's thousands dot and ING's
YYYYMMDD), but there are no real counterparties or amounts in them — a bank
export belongs in no repo at all, not even a private one.

Whoever has the real exports at hand can still run them through:

    BANKEXPORT_ING=/path/to/ing.csv BANKEXPORT_BUNQ=/path/to/bunq.csv pytest

Without those variables those two tests skip themselves.
"""

import os

import pytest

from domain.money import bank_providers as bank
from domain.money.bank_providers import bunq, ing


ING_HEADER = ('"Date","Name / Description","Account","Counterparty","Code",'
           '"Debit/credit","Amount (EUR)","Transaction type","Notifications"')

BUNQ_HEADER = '"Date","Interest Date","Amount","Account","Counterparty","Name","Description"'


def _write(tmp_path, name: str, rules: list[str]) -> str:
    path = tmp_path / name
    path.write_text("\n".join(rules) + "\n", encoding="utf-8")
    return str(path)


def _ing(tmp_path, *rows: str) -> str:
    return _write(tmp_path, "ing.csv", [ING_HEADER, *rows])


def _bunq(tmp_path, *rows: str) -> str:
    return _write(tmp_path, "bunq.csv", [BUNQ_HEADER, *rows])


# A salary credit and a card payment: together they cover both directions, a
# filled and an empty counterparty, and both of ING's notations.
ING_SALARY = ('"20260220","WERKGEVER B.V.","NL00INGB0000000001","NL02ABNA0123456789",'
               '"OV","Credit","2500,00","Transfer",'
               '"Name: WERKGEVER B.V. Description: Salaris IBAN: NL02ABNA0123456789"')
ING_PIN = ('"20260219","SUPERMARKT AMSTERDAM","NL00INGB0000000001","",'
           '"BA","Debit","42,50","Payment terminal",'
           '"Card sequence no.: 001 19/02/2026 17:42 Transaction: W12345"')

BUNQ_RENT = ('"2026-01-02","2026-01-02","-1.250,00","NL00BUNQ0000000002",'
             '"NL11RABO0123456789","VERHUURDER","Huur januari"')
BUNQ_INTEREST = ('"2026-01-03","2026-01-03","1,50","NL00BUNQ0000000002","","bunq",'
              '"bunq Payday 2026-01-02 EUR"')


# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------

def test_ing_is_recognised_by_its_columns(tmp_path):
    provider, _ = bank.read(_ing(tmp_path, ING_PIN))
    assert provider == "ing"


def test_bunq_is_recognised_by_its_columns(tmp_path):
    provider, _ = bank.read(_bunq(tmp_path, BUNQ_INTEREST))
    assert provider == "bunq"


def test_an_unknown_file_is_refused_with_its_columns(tmp_path):
    """The message must say *what* did come in, otherwise it cannot be used."""
    path = _write(tmp_path, "raar.csv", ['"Datum","Bedrag"', '"2026-01-01","1,00"'])
    with pytest.raises(bank.UnknownFormat) as error:
        bank.read(path)
    assert "Datum" in str(error.value)


def test_an_empty_file_is_refused(tmp_path):
    with pytest.raises(bank.UnknownFormat):
        bank.read(_write(tmp_path, "empty.csv", []))


def test_an_export_without_rows_is_not_an_error(tmp_path):
    """A quiet month gives zero rows, not an exception."""
    provider, rules = bank.read(_ing(tmp_path))
    assert provider == "ing"
    assert rules == []


# ---------------------------------------------------------------------------
# ING
# ---------------------------------------------------------------------------

def test_ing_debit_is_a_positive_expense(tmp_path):
    """Spending positive, income negative — the convention of the books."""
    _, rules = bank.read(_ing(tmp_path, ING_PIN))
    assert rules[0]["amount"] == pytest.approx(42.50)


def test_ing_credit_is_a_negative_income(tmp_path):
    _, rules = bank.read(_ing(tmp_path, ING_SALARY))
    assert rules[0]["amount"] == pytest.approx(-2500.00)


def test_ing_date_becomes_iso(tmp_path):
    """YYYYMMDD happens to sort correctly, but the rest of the codebase reads ISO."""
    _, rules = bank.read(_ing(tmp_path, ING_SALARY))
    assert rules[0]["date"] == "2026-02-20"


def test_ing_fields(tmp_path):
    _, rules = bank.read(_ing(tmp_path, ING_SALARY))
    r = rules[0]
    assert r["name"] == "WERKGEVER B.V."
    assert r["counterparty_iban"] == "NL02ABNA0123456789"
    assert r["account_iban"] == "NL00INGB0000000001"
    assert r["currency"] == "EUR"
    assert r["kind"] == "Transfer"
    assert r["code"] == "OV"
    assert "Salaris" in r["description"]


def test_ing_without_counterparty_gives_none_not_empty_text(tmp_path):
    """A card payment has no IBAN; empty is unknown, not an IBAN of nothing."""
    _, rules = bank.read(_ing(tmp_path, ING_PIN))
    assert rules[0]["counterparty_iban"] is None


def test_ing_description_comes_from_notifications(tmp_path):
    """That is where the real shop or counterparty is; the rules read it too."""
    _, rules = bank.read(_ing(tmp_path, ING_PIN))
    assert "Card sequence" in rules[0]["description"]


# ---------------------------------------------------------------------------
# bunq
# ---------------------------------------------------------------------------

def test_bunq_negative_amount_becomes_a_positive_expense(tmp_path):
    """bunq puts the sign in the amount; that is exactly the opposite of our convention."""
    _, rules = bank.read(_bunq(tmp_path, BUNQ_RENT))
    assert rules[0]["amount"] == pytest.approx(1250.00)


def test_bunq_positive_amount_becomes_a_negative_income(tmp_path):
    _, rules = bank.read(_bunq(tmp_path, BUNQ_INTEREST))
    assert rules[0]["amount"] == pytest.approx(-1.50)


def test_bunq_thousands_separator_is_not_read_as_decimal(tmp_path):
    """"-1.250,00" is twelve hundred and fifty, not one euro twenty-five."""
    _, rules = bank.read(_bunq(tmp_path, BUNQ_RENT))
    assert rules[0]["amount"] == pytest.approx(1250.00)
    assert rules[0]["amount"] != pytest.approx(1.25)


def test_bunq_fields(tmp_path):
    _, rules = bank.read(_bunq(tmp_path, BUNQ_RENT))
    r = rules[0]
    assert r["date"] == "2026-01-02"
    assert r["interest_date"] == "2026-01-02"
    assert r["name"] == "VERHUURDER"
    assert r["counterparty_iban"] == "NL11RABO0123456789"
    assert r["account_iban"] == "NL00BUNQ0000000002"
    assert r["description"] == "Huur januari"


def test_bunq_without_counterparty_gives_none(tmp_path):
    _, rules = bank.read(_bunq(tmp_path, BUNQ_INTEREST))
    assert rules[0]["counterparty_iban"] is None


def test_bunq_empty_description_is_empty_text(tmp_path):
    """An empty description really is empty; the rules may simply match on it."""
    rule = '"2026-01-05","2026-01-05","-10,00","NL00BUNQ0000000002","","IEMAND",""'
    _, rules = bank.read(_bunq(tmp_path, rule))
    assert rules[0]["description"] == ""


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def test_the_same_row_gets_the_same_hash(tmp_path):
    """Overlapping exports are the normal course of things, not an exception."""
    _, first = bank.read(_ing(tmp_path, ING_SALARY, ING_PIN))
    _, second = bank.read(_ing(tmp_path, ING_PIN, ING_SALARY))
    assert {r["dedup_hash"] for r in first} == {r["dedup_hash"] for r in second}


def test_different_rows_get_different_hashes(tmp_path):
    _, rules = bank.read(_ing(tmp_path, ING_SALARY, ING_PIN))
    assert len({r["dedup_hash"] for r in rules}) == 2


def test_two_identical_payments_on_one_day_stay_two_rows(tmp_path):
    """Two coffees of 3 euros at the same place are two expenses, not a duplicate.

    That is why the hash counts which occurrence within the file it is. Without
    that the second coffee silently disappears from every total.
    """
    coffee = ('"20260219","KOFFIEZAAK","NL00INGB0000000001","","BA","Debit","3,00",'
              '"Payment terminal","Card sequence no.: 001"')
    _, rules = bank.read(_ing(tmp_path, coffee, coffee))
    assert len(rules) == 2
    assert rules[0]["dedup_hash"] != rules[1]["dedup_hash"]


def test_hash_does_not_change_when_another_field_changes(tmp_path):
    """The hash is over date, amount, name and description — not over the rest.

    That is on purpose: if the bank ever adds a column or fills one differently, a
    row that was already imported must not suddenly look new.
    """
    a = ('"20260219","WINKEL","NL00INGB0000000001","","BA","Debit","5,00",'
         '"Payment terminal","Bon 1"')
    b = ('"20260219","WINKEL","NL00INGB0000000001","","GT","Debit","5,00",'
         '"Online Banking","Bon 1"')
    _, ra = bank.read(_ing(tmp_path, a))
    _, rb = bank.read(_ing(tmp_path, b))
    assert ra[0]["dedup_hash"] == rb[0]["dedup_hash"]


# ---------------------------------------------------------------------------
# Bad rows
# ---------------------------------------------------------------------------

def test_an_unreadable_row_does_not_cost_the_whole_file(tmp_path):
    """The same lesson as with the DeGiro upload: one odd row threw away 124 good ones."""
    broken = ('"nogeenszo","WINKEL","NL00INGB0000000001","","BA","Debit","5,00",'
             '"Payment terminal","x"')
    skipped: list[dict] = []
    _, rules = bank.read(_ing(tmp_path, ING_SALARY, broken, ING_PIN),
                          skipped=skipped)
    assert len(rules) == 2
    assert len(skipped) == 1
    assert skipped[0]["line_number"] == 3


def test_skipped_rows_say_why(tmp_path):
    broken = ('"20260219","WINKEL","NL00INGB0000000001","","BA","Debit","geen bedrag",'
             '"Payment terminal","x"')
    skipped: list[dict] = []
    bank.read(_ing(tmp_path, broken), skipped=skipped)
    assert "bedrag" in skipped[0]["reason"].lower()


# ---------------------------------------------------------------------------
# The real exports — only if they are there
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("variable_part,provider,expected", [
    ("BANKEXPORT_ING", "ing", 153),
    ("BANKEXPORT_BUNQ", "bunq", 73),
])
def test_the_real_export_is_read_completely(variable_part, provider, expected):
    """Every row counts: a parser that silently drops a few is worse than one that
    falls over, because the total then still looks plausible.
    """
    path = os.environ.get(variable_part)
    if not path or not os.path.exists(path):
        pytest.skip(f"{variable_part} niet gezet — zie de moduledocstring")

    skipped: list[dict] = []
    found, rules = bank.read(path, skipped=skipped)
    assert found == provider
    assert skipped == []
    assert len(rules) == expected
    assert len({r["dedup_hash"] for r in rules}) == expected, "geen enkele hash mag botsen"
    assert all(r["date"][:2] == "20" for r in rules), "elke datum is ISO"
