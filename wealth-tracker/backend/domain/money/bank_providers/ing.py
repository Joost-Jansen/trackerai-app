"""
The CSV ING gives under "Download".

    "Date","Name / Description","Account","Counterparty","Code",
    "Debit/credit","Amount (EUR)","Transaction type","Notifications"

Two things that stand out when you open such a file:

- The amount is **always positive**; the direction is in `Debit/credit`. We
  turn that into one signed number (spending positive), so a sum needs no
  column next to it.
- `Counterparty` is empty for two thirds of the rows — a card payment has no
  IBAN. The real counterparty is then in `Notifications`, together with the
  card number, the terminal and the booking date. That is why that field is
  the description here and not something we throw away: the labelling rules
  read it too.
"""

from domain.money.bank_providers import base
from domain.i18n import tr


PROVIDER = "ing"

COLUMNS = (
    "Date", "Name / Description", "Account", "Counterparty", "Code",
    "Debit/credit", "Amount (EUR)", "Transaction type", "Notifications",
)

_DATE_FORMAT = "%Y%m%d"


def recognises(columns: list[str]) -> bool:
    return set(COLUMNS) <= set(columns)


def parse_row(row: dict) -> dict:
    direction = base.clean(row.get("Debit/credit")).lower()
    if direction not in ("debit", "credit"):
        raise base.UnreadableRule(
            tr("Unknown direction in Debit/credit: {0}", repr(row.get('Debit/credit')))
        )

    amount = abs(base.parse_amount(row.get("Amount (EUR)")))
    # Debit is money going out, so an expense, so positive. Credit the other way round.
    if direction == "credit":
        amount = -amount

    # Only in the semicolon download: the balance after this booking. With it the
    # current account gets its balance per day from the export itself. The comma
    # variant does not have it, and then it stays None.
    balance = base.clean(row.get("Resulting balance"))

    return {
        "balance_after": base.parse_amount(balance) if balance else None,
        "date": base.parse_date(row.get("Date"), _DATE_FORMAT),
        "interest_date": None,          # ING does not provide one
        "amount": amount,
        "currency": base.CURRENCY,
        "name": base.clean(row.get("Name / Description")),
        "counterparty_iban": base.normalise_iban(row.get("Counterparty")),
        "description": base.clean(row.get("Notifications")),
        "account_iban": base.normalise_iban(row.get("Account")),
        "code": base.of_none(row.get("Code")),
        "kind": base.of_none(row.get("Transaction type")),
        "raw": dict(row),
    }
