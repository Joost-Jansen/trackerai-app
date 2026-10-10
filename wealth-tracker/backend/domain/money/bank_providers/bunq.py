"""
The CSV bunq gives under "Export".

    "Date","Interest Date","Amount","Account","Counterparty","Name","Description"

Shorter than ING's, and different in two ways:

- The sign is **in the amount**: negative is money going out. That is exactly
  the opposite of the convention of these books (spending positive), so the
  sign is flipped here.
- Thousands get a dot: "-1.250,00". If you mistake that dot for a decimal,
  twelve hundred and fifty suddenly becomes one euro twenty-five, and that
  does not stand out in a yearly total. base.parse_amount catches that.

`Interest Date` is the value date and differs from the booking date for more
than a third of the rows. We store it, but calculate with `Date`: that is the
day the money actually left your account.
"""

from domain.money.bank_providers import base


PROVIDER = "bunq"

COLUMNS = ("Date", "Interest Date", "Amount", "Account", "Counterparty", "Name", "Description")

_DATE_FORMAT = "%Y-%m-%d"


def recognises(columns: list[str]) -> bool:
    return set(COLUMNS) <= set(columns)


def parse_row(row: dict) -> dict:
    interest_date = base.clean(row.get("Interest Date"))

    return {
        "date": base.parse_date(row.get("Date"), _DATE_FORMAT),
        "interest_date": base.parse_date(interest_date, _DATE_FORMAT) if interest_date else None,
        # bunq: negative = money out = expense. Us: expense positive.
        "amount": -base.parse_amount(row.get("Amount")),
        "currency": base.CURRENCY,
        "name": base.clean(row.get("Name")),
        "counterparty_iban": base.normalise_iban(row.get("Counterparty")),
        "description": base.clean(row.get("Description")),
        "account_iban": base.normalise_iban(row.get("Account")),
        "code": None,
        "kind": None,
        "raw": dict(row),
    }
