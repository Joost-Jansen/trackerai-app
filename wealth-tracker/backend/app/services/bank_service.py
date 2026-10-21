"""
Importing a bank export: from file to stored rows and balances.

What this layer adds on top of bank_providers/ and bank_transactions.py is
the answer to "which account does this belong to?". The user does not have
to say — the export names its own account on every row — so we look it up
and create it if it does not exist yet.

Two kinds of keys:

  * **IBAN** (current account, bunq). A file with *two* IBANs in it is
    refused rather than guessed: a wrong guess silently spreads your
    transactions over the wrong accounts, and that is harder to fix
    afterwards than exporting again.
  * **Account number** (ING savings accounts, which have no IBAN). Those come
    together in one download, so there each number belongs to its own
    account.

And two ways a balance comes in, both as "from an import": the balance after
each booking in a transaction export (the last one per day), and a balance
overview with one state per day.
"""

import sqlite3

from domain.i18n import tr
from domain.money import accounts, bank_transactions, categorization
from domain.money import bank_providers as bank


class ImportRefused(Exception):
    """We cannot import this file; the message explains why."""


def _iban_of_the_export(rows: list[dict]) -> str:
    ibans = {r["account_iban"] for r in rows if r["account_iban"]}

    if not ibans:
        raise ImportRefused(tr("There is no account number in this file, so I don't know which account it belongs to."))
    if len(ibans) > 1:
        named = ", ".join(sorted(ibans))
        raise ImportRefused(tr("This file contains more than one account ({0}). Export each account separately.", named))
    return ibans.pop()


def _account_for(conn: sqlite3.Connection, iban: str, provider: str) -> tuple[dict, bool]:
    """Looks up the account by IBAN or creates it. Returns (account, created)."""
    existing = accounts.search_on_iban(conn, iban)
    if existing:
        return existing, False

    account_id = accounts.make_bank_account(
        conn,
        kind="bank",
        provider=provider,
        name=f"{provider.upper()} ···{iban[-4:]}",
        iban=iban,
    )
    return accounts.load_account(conn, account_id), True


def _account_for_number(conn: sqlite3.Connection, number: str, provider: str, name: str) -> tuple[dict, bool]:
    """Looks up the account by its number at this provider, or creates it."""
    existing = accounts.search_on_external_id(conn, provider, number)
    if existing:
        return existing, False
    account_id = accounts.make_bank_account(
        conn,
        kind="bank",
        provider=provider,
        # At ING all savings accounts are called "Oranje Spaarrekening"; the last
        # digits keep them apart in the list.
        name=f"{name} ···{number[-4:]}",
        external_id=number,
    )
    return accounts.load_account(conn, account_id), True


def _closing_balances(rows: list[dict]) -> list[tuple[str, float]]:
    """The balance at the end of each day, from "balance after this booking".

    Within a day the order in the file is the only order there is. ING puts the
    newest on top; look at the first and last date to see which way a file runs,
    so an export in the other order does not take the morning for the evening.
    """
    using = sorted((r for r in rows if r.get("balance_after") is not None), key=lambda r: r["sort_order"])
    if not using:
        return []
    newest_first = using[0]["date"] >= using[-1]["date"]
    per_day: dict[str, float] = {}
    for row in using if newest_first else reversed(using):
        per_day.setdefault(row["date"], row["balance_after"])
    return sorted(per_day.items())


def _only_changes(series: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Of a state per day, only the days it changed, plus the last one.

    A balance from an import runs on until the next measurement, so a thousand
    days with the same amount say nothing more than the first. The last day
    does stay: it says until when it was measured.
    """
    off: list[tuple[str, float]] = []
    for i, (date, balance) in enumerate(series):
        if not off or round(balance, 2) != round(off[-1][1], 2) or i == len(series) - 1:
            off.append((date, balance))
    return off


def _per_account(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["account_number"], []).append(row)
    return groups


def _import_transactions(conn, provider: str, rows: list[dict]) -> list[dict]:
    if any(r.get("account_number") for r in rows):
        groups = [
            (_account_for_number(conn, number, provider, group[0].get("account_name") or provider.upper()), group)
            for number, group in _per_account(rows).items()
        ]
    else:
        iban = _iban_of_the_export(rows)
        groups = [(_account_for(conn, iban, provider), rows)]

    reports = []
    for (account, created), group in groups:
        saved, skipped = bank_transactions.save(conn, account["id"], group)
        balances = accounts.set_balances(conn, account["id"], _closing_balances(group), source="sync")
        reports.append(
            {
                "account": accounts.load_account(conn, account["id"]),
                "created": created,
                "saved": saved,
                "skipped": skipped,
                "balances": balances,
            }
        )
    return reports


def _import_balances(conn, provider: str, rows: list[dict]) -> list[dict]:
    reports = []
    for number, group in _per_account(rows).items():
        account, created = _account_for_number(conn, number, provider, group[0]["account_name"])
        series = sorted({r["date"]: r["balance"] for r in group}.items())
        balances = accounts.set_balances(conn, account["id"], _only_changes(series), source="sync")
        reports.append(
            {
                "account": accounts.load_account(conn, account["id"]),
                "created": created,
                "saved": 0,
                "skipped": 0,
                "balances": balances,
            }
        )
    return reports


def import_file(conn: sqlite3.Connection, path: str) -> dict:
    """Reads a bank export and stores what is not in yet.

    `skipped` in the response is not an error: it is exactly the number of rows
    you already had. On a second import of the same file that is the whole file,
    and that is intended.

    `account` and `account_created` are about the first account in the file;
    `accounts` names them all.
    """
    unreadable: list[dict] = []
    try:
        export = bank.read_export(path, skipped=unreadable)
    except bank.UnknownFormat as e:
        raise ImportRefused(str(e)) from e

    provider, kind, rows = export["provider"], export["kind"], export["rows"]
    if not rows:
        raise ImportRefused(tr("This file contains no readable rows, so I don't know which account it belongs to."))

    if kind == "balances":
        reports = _import_balances(conn, provider, rows)
    else:
        reports = _import_transactions(conn, provider, rows)

    # Label straight away. Without this a fresh import counts in no total until
    # someone clicks "Label new", and then an empty month looks like a frugal one.
    # Also what was unknown: a new account can be the counterparty of transfers
    # imported earlier.
    categorization.seed(conn)
    labelled = categorization.relabel(conn)["labelled"]

    return {
        "provider": provider,
        "kind": kind,
        "accounts": reports,
        "account": reports[0]["account"],
        "account_created": reports[0]["created"],
        "was_read": len(rows),
        "saved": sum(v["saved"] for v in reports),
        "skipped": sum(v["skipped"] for v in reports),
        "balances": sum(v["balances"] for v in reports),
        "labelled": labelled,
        "unreadable": unreadable,
    }
