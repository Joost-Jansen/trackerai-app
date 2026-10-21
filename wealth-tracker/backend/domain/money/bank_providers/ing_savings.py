"""
The transactions of ING savings accounts.

    "Date";"Description";"Account";"Account name";"Counterparty";"Debit/credit";
    "Amount";"Currency";"Transaction type";"Notifications";"Resulting balance"

Different from the current account export:

- **Semicolons**, and the date as YYYY-MM-DD.
- **Several accounts in one file.** "All savings accounts" is one download.
  A savings account has no IBAN but a number like "C 575-83172"; that number
  is the key of the account here (see bank_service).
- **The balance after each booking** is included. With it a savings account
  gets its balance per day from the import itself, without anyone having to
  type it in.

What comes in here is mostly money between your own accounts — the
counterparty is your current account, which the labelling engine recognises
by its IBAN — plus the interest, and that *is* income.
"""

import re

from domain.i18n import tr
from domain.money.bank_providers import base

PROVIDER = "ing"

COLUMNS = (
    "Date",
    "Description",
    "Account",
    "Account name",
    "Counterparty",
    "Debit/credit",
    "Amount",
    "Currency",
    "Transaction type",
    "Resulting balance",
)

_DATE_FORMAT = "%Y-%m-%d"


def recognises(columns: list[str]) -> bool:
    # "Name / Description" is the current account; bank_providers/ing.py reads that.
    return set(COLUMNS) <= set(columns) and "Name / Description" not in columns


def account_number(text) -> str | None:
    """'C 575-83172' and 'C57583172' are the same account; the two ING downloads
    each write it in their own way.
    """
    number = re.sub(r"[\s-]+", "", base.clean(text)).upper()
    return number or None


def parse_row(row: dict) -> dict:
    currency = base.clean(row.get("Currency")).upper() or base.CURRENCY
    if currency != base.CURRENCY:
        raise base.UnreadableRule(tr("Euros only; this row is in {0}.", currency))

    direction = base.clean(row.get("Debit/credit")).lower()
    if direction not in ("debit", "credit"):
        raise base.UnreadableRule(tr("Unknown direction in Debit/credit: {0}", repr(row.get("Debit/credit"))))
    amount = abs(base.parse_amount(row.get("Amount")))
    if direction == "credit":
        amount = -amount

    number = account_number(row.get("Account"))
    if not number:
        raise base.UnreadableRule(tr("No account number."))

    balance = base.clean(row.get("Resulting balance"))
    return {
        "date": base.parse_date(row.get("Date"), _DATE_FORMAT),
        "interest_date": None,
        "amount": amount,
        "currency": base.CURRENCY,
        "name": base.clean(row.get("Description")),
        "counterparty_iban": base.normalise_iban(row.get("Counterparty")),
        "description": base.clean(row.get("Notifications")),
        "account_iban": None,
        "account_number": number,
        "account_name": "ING Spaarrekening",
        "code": None,
        "kind": base.of_none(row.get("Transaction type")),
        "balance_after": base.parse_amount(balance) if balance else None,
        # Two savings accounts with the same transfer on the same day are two rows, not
        # a duplicate.
        "hash_extra": number,
        "raw": dict(row),
    }
