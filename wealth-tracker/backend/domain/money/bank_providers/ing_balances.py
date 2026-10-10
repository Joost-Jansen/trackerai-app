"""
The balance overview of ING savings accounts: one balance per day per account.

    "Date";"Account";"Account name";"Currency";"Book balance"

No transactions, only states. Exactly what net worth needs: where a transaction
export says what happened, this says how much there was — also on the days
nothing happened, and also for an account whose transactions you never
uploaded.
"""

from domain.money.bank_providers import base
from domain.money.bank_providers.ing_savings import account_number
from domain.i18n import tr


PROVIDER = "ing"
KIND = "balances"

COLUMNS = ("Date", "Account", "Account name", "Currency", "Book balance")

_DATE_FORMAT = "%Y-%m-%d"


def recognises(columns: list[str]) -> bool:
    return set(COLUMNS) <= set(columns)


def parse_row(row: dict) -> dict:
    currency = base.clean(row.get("Currency")).upper() or base.CURRENCY
    if currency != base.CURRENCY:
        raise base.UnreadableRule(tr("Euros only; this row is in {0}.", currency))
    number = account_number(row.get("Account"))
    if not number:
        raise base.UnreadableRule(tr("No account number."))
    return {
        "date": base.parse_date(row.get("Date"), _DATE_FORMAT),
        "account_number": number,
        "account_name": base.clean(row.get("Account name")) or "ING Spaarrekening",
        "balance": base.parse_amount(row.get("Book balance")),
    }
