"""
transaction_parser.py — Reads DeGiro Excel transaction exports

DeGiro exports transactions as .xlsx files. Depending on the user's UI
language the column headers come out in either Dutch or English, so every
column is resolved against both languages (see _COLUMN_CANDIDATES).
This module parses those files into a list of standardised dicts that
the rest of the app can work with.

Note: regardless of UI language DeGiro keeps Dutch number/date formatting
(dd-mm-yyyy, comma decimal), so only the header names differ per language.

Named transaction_parser instead of parser to avoid shadowing
Python's built-in 'parser' module.
"""

import math
import os

import pandas as pd
from domain.imports.degiro_export import read_export, number


# Logical field → list of candidate header prefixes (Dutch first, then English).
# Matching is case-insensitive and prefix-based, so "Waarde EUR" / "Value EUR"
# both resolve via "Waarde" / "Value". Order matters: more specific candidates
# must come before generic ones to avoid collisions (e.g. "Exchange rate"
# must never be matched by the "Exchange" venue field).
_COLUMN_CANDIDATES: dict[str, list[str]] = {
    "isin":          ["ISIN"],
    "product":       ["Product"],
    "date":          ["Datum", "Date"],
    "time":          ["Tijd", "Time"],
    "exchange":      ["Beurs", "Reference Exchange"],
    "venue":         ["Uitvoeringsplaats", "Execution Venue", "Venue"],
    "quantity":      ["Aantal", "Quantity", "Number"],
    "price":         ["Koers", "Price"],
    "local_value":   ["Lokale waarde", "Local value"],
    "value_eur":     ["Waarde", "Value"],
    "exchange_rate": ["Wisselkoers", "Exchange rate"],
    "autofx":        ["AutoFX"],
    "transaction_fee": ["Transactiekosten", "Transaction and/or", "Transaction"],
    "total_eur":     ["Totaal", "Total"],
}


def parse_transactions(file_path: str, warnings: list[dict] | None = None) -> list[dict]:
    """
    Parses a single DeGiro Excel export file.

    Parameters:
        file_path: path to the .xlsx file
        warnings:  optional list; rows that name a product but whose number of
                   units could not be established are appended to it. They are
                   left out of the returned transactions, so reporting them is
                   the only thing that keeps them from vanishing silently.

    Returns:
        A list of transaction dicts, one per row.
        Returns an empty list if the file cannot be parsed.
    """
    try:
        df = read_export(file_path)
    except Exception as e:
        print(f"  Error reading {os.path.basename(file_path)}: {e}")
        return []

    # Strip whitespace from all column names (handles 'Koers ' trailing space)
    df.columns = [str(c).strip() for c in df.columns]

    # Resolve every logical field to an actual column name, matching both the
    # Dutch and English header sets (and the old/new Dutch variants such as
    # "Waarde" vs "Waarde EUR"). Case-insensitive prefix match.
    col_names = list(df.columns)

    def _resolve(*candidates: str) -> str | None:
        """Return the first column matching any candidate prefix, or None."""
        for cand in candidates:
            cl = cand.lower()
            for c in col_names:
                cc = c.lower()
                if cc == cl or cc.startswith(cl + " "):
                    return c
        return None

    COL = {field: _resolve(*cands) for field, cands in _COLUMN_CANDIDATES.items()}

    # Identify the last column — DeGiro puts the order UUID there,
    # but it has no header (shows as 'Unnamed: N')
    last_col = df.columns[-1]

    transactions = []

    for _, row in df.iterrows():
        # Skip rows that have no ISIN (header repeats, totals rows, etc.)
        isin = str(row.get(COL["isin"], "")).strip() if COL["isin"] else ""
        if not isin or isin == "nan" or isin == "ISIN":
            continue

        # Extract order reference (UUID) from the last unnamed column
        order_ref = str(row.get(last_col, "")).strip()
        if order_ref == "nan":
            order_ref = None

        def _float(col: str) -> float | None:
            if col is None:
                return None
            val = row.get(col)
            try:
                num = number(val)
            except (ValueError, TypeError):
                return None
            # An empty numeric cell reaches us as float NaN rather than None,
            # and NaN survives float() silently. It must never leave this
            # function: sqlite has no NaN and binds it as NULL, which trips the
            # NOT NULL columns and fails the whole import.
            return num if num is not None and math.isfinite(num) else None

        def _str(col: str) -> str | None:
            if col is None:
                return None
            val = row.get(col)
            s = str(val).strip()
            # An empty cell arrives as either float NaN or None depending on the
            # column's dtype; str() turns those into "nan" and "None", and a
            # venue literally called "None" then looks like a real exchange.
            return s if s and s not in ("nan", "None") else None

        price       = _float(COL["price"])
        local_value = _float(COL["local_value"])

        # Quantity: positive = BUY, negative = SELL.
        #
        # DeGiro leaves "Aantal" empty on orders it books by amount rather than
        # by units — a money-market fund bought for exactly €50.000, say. The
        # number of units is still implied by the row: local value ÷ price is
        # the same arithmetic DeGiro did, not a guess. Its sign carries the
        # direction, since money leaving the account (negative local value) is
        # a purchase.
        qty_signed = _float(COL["quantity"])
        if qty_signed is None and local_value is not None and price:
            qty_signed = -local_value / price

        if qty_signed is None:
            # Nothing to hold a position in and nothing to derive it from.
            # Dropping the row keeps the rest of the file importable; the
            # caller reports it so a real trade cannot go missing in silence.
            if warnings is not None:
                warnings.append({
                    "date": _str(COL["date"]),
                    "name": _str(COL["product"]),
                    "isin": isin,
                    "reason": "aantal ontbreekt",
                })
            continue

        transaction_type = "BUY" if qty_signed >= 0 else "SELL"
        quantity = abs(qty_signed)

        # Parse date — DeGiro uses DD-MM-YYYY format
        date_raw = _str(COL["date"])
        date_iso = None
        if date_raw:
            try:
                date_iso = pd.to_datetime(date_raw, dayfirst=True).strftime("%Y-%m-%d")
            except Exception:
                # Unparseable date: leave None so the row is skipped on save —
                # a raw non-ISO string would corrupt date sorting and crash
                # the history charts.
                date_iso = None

        # Parse time
        time_raw = _str(COL["time"])
        time_fmt = None
        if time_raw:
            # Keep only HH:MM
            time_fmt = str(time_raw)[:5]

        transactions.append({
            "order_ref":        order_ref,
            "date":             date_iso,
            "time":             time_fmt,
            "name":             _str(COL["product"]),
            "isin":             isin,
            "exchange":         _str(COL["exchange"]),
            "execution_venue":  _str(COL["venue"]),
            "transaction_type": transaction_type,
            "quantity":         quantity,
            "price":            price,
            "local_value":      local_value,
            "value_eur":        _float(COL["value_eur"]),
            "exchange_rate":    _float(COL["exchange_rate"]),
            "autofx_cost":      _float(COL["autofx"]),
            "transaction_fee":  _float(COL["transaction_fee"]),
            "total_eur":        _float(COL["total_eur"]),
        })

    return transactions
