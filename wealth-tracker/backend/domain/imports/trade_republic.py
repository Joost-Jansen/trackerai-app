"""
trade_republic.py — reads Trade Republic's transaction export (CSV).

Trade Republic offers, in the app and on the web, an export of every booking on
the securities and the cash account as one CSV ("Transaktionsexport"). Its
header, as published by users of several independent importers (pytr issue
#408, Export-To-Ghostfolio issue #329, GhostfolioSidekick issue #1411), is:

    datetime, date, account_type, category, type, asset_class, name, symbol,
    shares, price, amount, fee, tax, currency, original_amount,
    original_currency, fx_rate, description, transaction_id,
    counterparty_name, counterparty_iban, payment_reference, mcc_code

One row per booking. The column names and the codes in `category` (TRADING,
CASH) and `type` (BUY, SELL, DIVIDEND, CUSTOMER_INBOUND, …) are the same
whatever language the app is set to; only free text such as `description`
differs. The signs as the file has them:

    BUY       shares > 0, amount < 0 (the value, without the fee), fee < 0
    SELL      shares < 0, amount > 0, fee < 0, tax < 0 where tax is withheld
    DIVIDEND  amount > 0 gross, tax < 0; `original_*` in the fund's currency
    deposits  amount > 0;  withdrawals amount < 0

What every row does to the cash is therefore amount + fee + tax, which is what
the cash ledger (broker_ledger.py) records for each one. A trade is also a row
in `transactions`, a dividend also one in `dividends`. Savings-plan executions
are BUY rows with a fractional number of shares and are read as such.

Robustness: column names are matched case-insensitively with spaces and dashes
read as underscores, the separator is sniffed (comma or semicolon), and numbers
may have a decimal comma. Rows in another currency than EUR are reported and
left out: converting needs a rate this file does not give for every row.

Not read here: Trade Republic's per-transaction PDF statements, and the CSV of
the third-party tool pytr. Neither format could be verified from a published
sample, so neither is guessed at.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime

from domain import database
from domain.imports.degiro_export import number, read_export
from domain.money import accounts
from domain.portfolio import broker_ledger

BROKER = "trade_republic"

#: Columns without which a file is not this export.
REQUIRED = ("category", "type", "amount", "currency")

_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

#: Trade Republic's `type` -> the ledger's kind. Anything not listed is
#: classified by its name (see _kind) and still counts in the cash.
_KINDS = {
    "BUY": "buy",
    "SELL": "sell",
    "DIVIDEND": "dividend",
    "DISTRIBUTION": "dividend",
    "INTEREST_PAYMENT": "interest",
    "CUSTOMER_INBOUND": "deposit",
    "CUSTOMER_INPAYMENT": "deposit",
    "TRANSFER_INBOUND": "deposit",
    "TRANSFER_INSTANT_INBOUND": "deposit",
    "CUSTOMER_OUTBOUND_REQUEST": "withdrawal",
    "TRANSFER_OUTBOUND": "withdrawal",
    "TRANSFER_INSTANT_OUTBOUND": "withdrawal",
    "PRE_DETERMINED_TAX_BASE": "tax",
    "TAX_OPTIMIZATION": "tax",
    "CARD_ORDERING_FEE": "fee",
}


def _column_name(raw: str) -> str:
    return re.sub(r"[\s\-]+", "_", str(raw).strip().strip('"').lstrip("﻿").strip().lower())


def looks_like(columns) -> bool:
    """Is a file with these column names Trade Republic's transaction export?"""
    names = {_column_name(c) for c in columns}
    return all(c in names for c in REQUIRED) and ("date" in names or "datetime" in names)


def _text(row: dict, column: str) -> str:
    value = row.get(column)
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in ("nan", "none") else text


def _number(row: dict, column: str) -> float | None:
    text = _text(row, column)
    return number(text) if text else None


def _day(row: dict) -> str | None:
    text = _text(row, "date") or _text(row, "datetime")[:10]
    for form in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], form).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _time(row: dict) -> str | None:
    stamp = _text(row, "datetime")
    match = re.search(r"T(\d{2}:\d{2})", stamp)
    return match.group(1) if match else None


def _kind(category: str, kind: str, amount: float, tax: float) -> str:
    if kind in _KINDS:
        return _KINDS[kind]
    if "INBOUND" in kind or "INPAYMENT" in kind:
        return "deposit"
    if "OUTBOUND" in kind:
        return "withdrawal"
    if "INTEREST" in kind:
        return "interest"
    if "FEE" in kind:
        return "fee"
    if "TAX" in kind or (amount == 0 and tax != 0):
        return "tax"
    return "other"


def parse(path: str) -> dict:
    """The file as {trades, dividends, entries, skipped, rows}.

    trades     dicts in the shape database.save_transactions takes
    dividends  dicts in the shape database.save_dividends takes
    entries    every cash movement: {date, amount, description, key, kind}
    skipped    [{line, type, reason}] rows that were not read, said out loud
    """
    df = read_export(path)
    df.columns = [_column_name(c) for c in df.columns]
    out: dict = {"trades": [], "dividends": [], "entries": [], "skipped": [], "rows": len(df)}
    seen: dict[str, int] = {}

    for position, record in enumerate(df.to_dict("records")):
        line = position + 2  # the header is line 1
        category = _text(record, "category").upper()
        kind_code = _text(record, "type").upper()
        day = _day(record)
        if not day:
            out["skipped"].append({"line": line, "type": kind_code, "reason": "date"})
            continue
        currency = _text(record, "currency").upper() or "EUR"
        if currency != "EUR":
            out["skipped"].append({"line": line, "type": kind_code, "reason": f"currency {currency}"})
            continue

        amount = _number(record, "amount") or 0.0
        fee = _number(record, "fee") or 0.0
        tax = _number(record, "tax") or 0.0
        name = _text(record, "name")
        symbol = _text(record, "symbol").upper()
        reference = _text(record, "transaction_id")
        kind = _kind(category, kind_code, amount, tax)

        if kind in ("buy", "sell") or (category == "TRADING" and _number(record, "shares")):
            shares = _number(record, "shares")
            if not shares or not _ISIN.match(symbol):
                out["skipped"].append({"line": line, "type": kind_code, "reason": "shares or ISIN missing"})
            else:
                if kind not in ("buy", "sell"):
                    kind = "buy" if shares > 0 else "sell"
                quantity = abs(shares)
                price = _number(record, "price") or (abs(amount) / quantity if amount else None)
                value = -abs(amount) if kind == "buy" else abs(amount)
                cost = -abs(fee) if fee else None
                out["trades"].append(
                    {
                        "order_ref": reference or None,
                        "date": day,
                        "time": _time(record),
                        "name": name or symbol,
                        "isin": symbol,
                        "exchange": None,
                        "execution_venue": None,
                        "transaction_type": kind.upper(),
                        "quantity": quantity,
                        "price": price,
                        "local_value": value,
                        "value_eur": value,
                        "exchange_rate": None,
                        "autofx_cost": None,
                        "transaction_fee": cost,
                        # Tax withheld on a sale is not a cost of the trade; it
                        # lowers the cash as its own part of the same row.
                        "total_eur": round(value + (cost or 0.0), 2),
                        "broker": BROKER,
                    }
                )

        if kind == "dividend":
            if _ISIN.match(symbol):
                original = _number(record, "original_amount")
                original_currency = _text(record, "original_currency").upper()
                out["dividends"].append(
                    {
                        "date": day,
                        "isin": symbol,
                        "name": name or symbol,
                        "currency_original": original_currency or "EUR",
                        "amount_original": original if original is not None else amount,
                        "gross_eur": round(amount, 4),
                        "tax_eur": round(-abs(tax), 4),
                        "net_eur": round(amount - abs(tax) - abs(fee), 4),
                        "broker": BROKER,
                    }
                )
            else:
                out["skipped"].append({"line": line, "type": kind_code, "reason": "ISIN missing"})

        cash = round(amount + fee + tax, 2)
        if cash == 0:
            continue
        core = reference or f"{_text(record, 'datetime') or day}|{kind_code}|{cash}"
        seen[core] = seen.get(core, 0) + 1
        out["entries"].append(
            {
                "date": day,
                "amount": cash,
                "description": name or _text(record, "description") or kind_code,
                "key": f"tr|{core}|{seen[core]}",
                "kind": kind,
            }
        )
    return out


def import_file(conn: sqlite3.Connection, path: str, account_id: int | None = None) -> dict:
    """Reads an export into the portfolio and the Trade Republic cash account.

    Creates that account the first time (or uses `account_id`). Importing the
    same file again changes nothing: trades and dividends are counted against
    what is stored, cash movements carry Trade Republic's transaction id.
    """
    parsed = parse(path)
    account = (
        broker_ledger.broker_account(conn, account_id)
        if account_id is not None
        else broker_ledger.cash_account(conn, BROKER, create=bool(parsed["entries"] or parsed["trades"]))
    )
    if account is None:
        return {"account": None, "saved": 0, "skipped": 0, "dividends": 0, "cash_entries": 0, "unread": parsed["skipped"]}

    for row in parsed["trades"] + parsed["dividends"]:
        row["account_id"] = account["id"]
        row["broker"] = account["provider"]
    saved, skipped = database.save_transactions(conn, parsed["trades"])
    dividends, _ = database.save_dividends(conn, parsed["dividends"]) if parsed["dividends"] else (0, 0)
    entries = accounts.save_entries(conn, account["id"], parsed["entries"])
    broker_ledger.sync_balances(conn, account["id"])
    return {
        "account": account,
        "saved": saved,
        "skipped": skipped,
        "dividends": dividends,
        "cash_entries": entries,
        "unread": parsed["skipped"],
    }
