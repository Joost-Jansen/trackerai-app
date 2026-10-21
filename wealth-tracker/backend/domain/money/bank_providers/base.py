"""
What every bank parser shares: numbers, dates and the fingerprint of a row.

The normalised row every parser delivers:

    date               ISO, YYYY-MM-DD
    interest_date      ISO or None — bunq provides it, ING does not
    amount             float, **spending positive, income negative**
    currency           "EUR"
    name               the counterparty as the bank writes it
    counterparty_iban  IBAN or None (a card payment has none)
    description        everything else the bank gives; for a payment
                       processor this is where the real shop is
    account_iban       which account this row comes from
    code               the bank's code, or None (ING: BA, GT, IC, IW, …)
    kind               what the bank calls the transaction, or None
    dedup_hash         see below
    raw                the original row, in case something is missing later

The sign is the convention of the rest of the books and on purpose not the
bank's: spending adds up positive in a spending overview, so it must be
positive in the database too. ING says it in a separate column, bunq puts it
in the amount; here both end up on the same convention.
"""

import hashlib
import re
from datetime import datetime

from domain.i18n import tr

CURRENCY = "EUR"

_NOT_NUMBER = re.compile(r"[^\d,.\-]")


class UnreadableRule(Exception):
    """This row could not be read; the rest of the file could."""


def clean(value) -> str:
    return str(value).strip() if value is not None else ""


def of_none(value) -> str | None:
    """Empty text is unknown, not an empty value that matches something."""
    text = clean(value)
    return text or None


def parse_amount(text) -> float:
    """Dutch notation: the comma is the decimal, the dot separates thousands.

    Without this rule "-1.250,00" is read as one euro twenty-five, and that does
    not stand out in a yearly total.
    """
    raw = clean(text)
    if not raw:
        raise UnreadableRule(tr("Empty amount."))

    normalised = _NOT_NUMBER.sub("", raw).replace(".", "").replace(",", ".")
    try:
        return float(normalised)
    except ValueError as e:
        raise UnreadableRule(tr("Unreadable amount: {0}", repr(raw))) from e


def parse_date(text, form: str) -> str:
    """Reads a date in `form` and returns it as ISO.

    ISO because the whole codebase compares and sorts dates as text (see
    database.load_transactions' ORDER BY date); then every date must have the
    same form.
    """
    raw = clean(text)
    if not raw:
        raise UnreadableRule(tr("Empty date."))
    try:
        return datetime.strptime(raw, form).strftime("%Y-%m-%d")
    except ValueError as e:
        raise UnreadableRule(tr("Unreadable date: {0}", repr(raw))) from e


def normalise_iban(iban) -> str | None:
    text = re.sub(r"\s+", "", clean(iban)).upper()
    return text or None


def dedup_hash(date: str, amount: float, name: str, description: str, sequence_number: int, extra: str = "") -> str:
    """The fingerprint by which a second import recognises itself.

    Over date, amount, name and description — on purpose not over the rest of
    the row. If the bank ever adds a column or fills one differently, a row that
    was already imported must not suddenly look new.

    `sequence_number` is which identical occurrence this is within this file. Two
    coffees of three euros at the same place on the same day are two expenses,
    not a duplicate; without this number the second would silently disappear from
    every total. An export of the same period gives the same order and so the
    same numbers, so overlapping exports keep working.

    `extra` tells accounts apart in a file with several (ING's savings
    accounts). Empty for all others, and then the hash is exactly what it always
    was: a row that was already imported keeps recognising itself.
    """
    core = f"{date}|{amount:.2f}|{name}|{description}|{sequence_number}"
    if extra:
        core += f"|{extra}"
    return hashlib.sha1(core.encode("utf-8")).hexdigest()[:16]


def add_hashes(rows: list[dict]) -> list[dict]:
    """Numbers identical rows within one file and puts the hash on them.

    Numbered per account (through `hash_extra`), so the number does not depend
    on which other accounts happened to be in the same download.
    """
    seen: dict[tuple, int] = {}
    for row in rows:
        extra = row.get("hash_extra") or ""
        key = (row["date"], round(row["amount"], 2), row["name"], row["description"], extra)
        sequence_number = seen.get(key, 0) + 1
        seen[key] = sequence_number
        row["dedup_hash"] = dedup_hash(*key[:4], sequence_number, extra)
    return rows
