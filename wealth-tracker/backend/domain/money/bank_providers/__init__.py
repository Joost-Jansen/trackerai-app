"""
bank_providers/ — reading bank exports.

One entry point: `read_export(path)` looks at the columns to see which bank and
which kind of file it is. That way the user does not have to say which bank it
was when uploading; the file already says so itself. Two kinds:

  * **transactions** — what happened, per row (ING current and savings
    account, bunq). Some include the balance after each booking.
  * **balances** — only states, one per day per account (ING balance
    overview).

Comma or semicolon it also works out itself: ING delivers both, depending on
which download you choose.

Why CSV and not the bank's API: bunq's financial API sits behind a Pro/Elite
subscription, and ING has none at all for private customers. PSD2 through an
aggregator is possible, but there the consent expires every ~90 days and you
only see 90 days back. An export is free, never breaks, and reaches as far
back as you want. The API comes alongside it later, not instead.

Every transaction parser delivers the same normalised row; see
bank_providers/base.py for the fields and for the sign convention.
"""

import csv

from domain.money.bank_providers import base, bunq, ing, ing_balances as ing_balances, ing_savings as ing_saving
from domain.i18n import tr


# Order matters where columns overlap: ing_savings itself refuses a file with
# "Name / Description", so ing is not lost to it.
PARSERS = (ing, ing_saving, bunq, ing_balances)

# The provider names a caller can expect.
PROVIDERS = tuple(dict.fromkeys(p.PROVIDER for p in PARSERS))


class UnknownFormat(Exception):
    """No parser recognises the columns of this file."""


def _choose_parser(columns: list[str] | None):
    for parser in PARSERS:
        if columns and parser.recognises(columns):
            return parser
    found = ", ".join(columns) if columns else tr("(no columns)")
    raise UnknownFormat(
        tr("This file belongs to none of the banks we know ({0}). Columns found: {1}", ', '.join(PROVIDERS), found)
    )


def _separator(header_row: str) -> str:
    return ";" if header_row.count(";") > header_row.count(",") else ","


def read_export(path: str, skipped: list[dict] | None = None) -> dict:
    """{"provider", "kind": "transactions" | "balances", "rows"}.

    A row that cannot be read does not cost the whole file — the same lesson as
    with the DeGiro upload, where one empty `Aantal` cell once took 124 good rows
    along in the rollback. Such rows end up in `skipped` with their line number
    and the reason, so the user sees *what* did not come along instead of it
    disappearing silently.

    `sort_order` on every row is its place in the file: within one day that is the
    only way to know which booking was the last.
    """
    with open(path, newline="", encoding="utf-8-sig") as file:
        header_row = file.readline()
        file.seek(0)
        reader = csv.DictReader(file, delimiter=_separator(header_row))
        parser = _choose_parser(reader.fieldnames)

        rows: list[dict] = []
        for line_number, row in enumerate(reader, start=2):  # 1 is the header row
            try:
                parsed = parser.parse_row(row)
            except base.UnreadableRule as e:
                if skipped is not None:
                    skipped.append({"line_number": line_number, "reason": str(e)})
                continue
            parsed["sort_order"] = line_number
            rows.append(parsed)

    kind = getattr(parser, "KIND", "transactions")
    if kind == "transactions":
        rows = base.add_hashes(rows)
    return {"provider": parser.PROVIDER, "kind": kind, "rows": rows}


def read(path: str, skipped: list[dict] | None = None) -> tuple[str, list[dict]]:
    """Reads a transaction export and returns (provider, normalised rows)."""
    export = read_export(path, skipped)
    if export["kind"] != "transactions":
        raise UnknownFormat(tr("This is a balance overview and not a transaction export."))
    return export["provider"], export["rows"]
