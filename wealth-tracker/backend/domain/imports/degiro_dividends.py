"""
dividend_parser.py — Parses DeGiro account mutations exports to extract dividend income.

Exact column layout confirmed from DeGiro's mutations export:
  Datum, Tijd, Valutadatum, Product, ISIN, Omschrijving, FX, Mutatie, Unnamed: 8, ...
  - Omschrijving : row-type description
  - Mutatie      : currency code (EUR / USD / ...)
  - Unnamed: 8   : signed amount in that currency
  - FX           : exchange rate in foreign-currency units per EUR
                   (only populated on "Valuta Debitering" rows)

Foreign-currency dividend flow (example: USD):
  1. "Dividend"           row  – USD amount > 0, ISIN present, FX = NaN
  2. "Valuta Debitering"  row  – total USD deducted (negative), FX = <rate>  (USD/EUR)
  3. "Valuta Creditering" row  – EUR deposited

  EUR conversion: gross_eur = usd_amount / fx_rate
  (verified: 10.17 / 1.1749 = 8.66, 2.56 / 1.1801 = 2.17)

  Multiple dividends on the same day that share one FX conversion are handled
  correctly because each is converted independently using the same FX rate
  found by date-proximity matching to the "Valuta Debitering" row.

Withholding tax ("Dividendbelasting"):
  Always EUR, always negative, assigned to the *closest* dividend of the
  same ISIN within ±5 days.

Deduplication key: (date, isin, amount_original, currency_original)
"""

import os

import pandas as pd

from domain.imports.degiro_export import number, read_export

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_str(val) -> str:
    s = str(val).strip()
    return "" if s == "nan" else s


def _safe_float(val) -> float | None:
    return number(val)


def _parse_date(val) -> str | None:
    s = _safe_str(val)
    if not s:
        return None
    try:
        return pd.to_datetime(s, dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        # Unparseable date: treat the row as dateless (it gets skipped) rather
        # than letting a raw string crash pd.Timestamp() later on.
        return None


def _detect_columns(df: pd.DataFrame) -> dict:
    """
    Locate column names from the DataFrame header.

    Works for both Dutch and English DeGiro exports. The mutations file has a
    currency column ("Mutatie" / "Change") immediately followed by an unnamed
    column (e.g. "Unnamed: 8") holding the signed amount. The "FX" column
    carries the exchange rate only on currency-conversion rows.

    English header equivalents (confirmed from a DeGiro EN export):
      Datum→Date, Product→Product, ISIN→ISIN, Omschrijving→Description,
      FX→FX, Mutatie→Change, Saldo→Balance.
    """
    cols = list(df.columns)
    found: dict = {}

    for i, col in enumerate(cols):
        cl = col.lower()
        if cl.startswith("datum") or cl.startswith("date"):
            found.setdefault("date", col)
        elif cl.startswith("product"):
            found.setdefault("product", col)
        elif cl == "isin":
            found.setdefault("isin", col)
        elif cl.startswith("omschrijving") or cl.startswith("description"):
            found.setdefault("desc", col)
        elif cl.startswith("fx"):
            found.setdefault("fx", col)
        elif cl.startswith("mutatie") or cl.startswith("change"):
            found.setdefault("mut_ccy", col)
            if i + 1 < len(cols):
                found.setdefault("mut_amt", cols[i + 1])

    return found


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_dividends(file_path: str, warnings: list[dict] | None = None) -> list[dict]:
    """
    Parse a DeGiro account mutations Excel export and return one dict per
    net dividend payment.

    *warnings*, when given, collects the payments this file could not convert to
    EUR at all — they are left out of the result, and a caller that shows the
    list can say so instead of silently reporting a smaller total.

    Each dict has:
        date              – ISO date string (YYYY-MM-DD)
        isin              – ISIN of the paying stock/ETF
        name              – Product name
        currency_original – Currency of the original dividend (EUR / USD / …)
        amount_original   – Raw amount in original currency (negative for
                            corrections/reversals)
        gross_eur         – Gross dividend in EUR
        tax_eur           – Withholding tax in EUR (≤ 0)
        net_eur           – gross_eur + tax_eur
    """
    try:
        df = read_export(file_path)
    except Exception as e:
        print(f"  Error reading {os.path.basename(file_path)}: {e}")
        return []

    df.columns = [str(c).strip() for c in df.columns]
    C = _detect_columns(df)

    if "desc" not in C:
        print(f"  Could not find 'Omschrijving' column in {os.path.basename(file_path)}")
        print(f"  Found columns: {list(df.columns)}")
        return []

    # ------------------------------------------------------------------
    # Pass 1: bucket rows into dividends / taxes / FX debit events
    # ------------------------------------------------------------------
    dividend_rows: list[dict] = []
    tax_rows: list[dict] = []
    fx_debit_rows: list[dict] = []  # "Valuta Debitering" — carry the FX rate

    for _, row in df.iterrows():
        desc = _safe_str(row.get(C.get("desc", ""), "")).lower()
        if not desc:
            continue

        date_str = _parse_date(row.get(C.get("date", ""), ""))
        if not date_str:
            continue

        isin = _safe_str(row.get(C.get("isin", ""), ""))
        name = _safe_str(row.get(C.get("product", ""), ""))
        currency = _safe_str(row.get(C.get("mut_ccy", ""), "")).upper()
        amount = _safe_float(row.get(C.get("mut_amt", ""), ""))
        fx_rate = _safe_float(row.get(C.get("fx", ""), "")) if "fx" in C else None

        if amount is None:
            continue

        # NOTE on language: DeGiro's mutations export keeps the Description
        # column in Dutch even when the UI/headers are English, so the Dutch
        # matches below are the primary path. The English fallbacks
        # ("dividend tax", "withholding", "fx debit", "currency debit") are
        # best-effort guesses — verify them against a real English export.
        # Tax must be checked before the generic "dividend" branch, because
        # "Dividend Tax" also contains "dividend".
        if "dividendbelasting" in desc or "dividend tax" in desc or "withholding" in desc:
            # Withholding tax — always EUR, always negative
            tax_rows.append(
                {
                    "date": date_str,
                    "isin": isin,
                    "amount_eur": amount,  # negative
                }
            )

        elif "dividend" in desc:
            # Gross dividend row.  Keep the sign: a negative amount is a
            # correction/reversal and must reduce the totals, not add to them.
            dividend_rows.append(
                {
                    "date": date_str,
                    "isin": isin,
                    "name": name,
                    "currency": currency,
                    "amount": amount,
                }
            )

        elif "valuta debitering" in desc or "fx debit" in desc or "currency debit" in desc:
            # FX conversion debit — carries the exchange rate
            if fx_rate and fx_rate != 0:
                fx_debit_rows.append(
                    {
                        "date": date_str,
                        "currency": currency,  # foreign currency (e.g. USD)
                        "fx_rate": fx_rate,  # foreign-currency units per EUR
                    }
                )

    # ------------------------------------------------------------------
    # Pass 2: build net dividend records
    # ------------------------------------------------------------------
    results: list[dict] = []
    skipped_no_fx: list[dict] = warnings if warnings is not None else []

    # Assign each withholding-tax row to the *closest* dividend of the same
    # ISIN within ±5 days.  (Greedy first-come matching let one payment
    # absorb every tax row in the window when two payments fell close
    # together — totals were right but the per-payment split was wrong.)
    tax_by_div: dict[int, float] = {}
    assigned: dict[int, int] = {}  # payment index → tax rows already on it
    for tax in tax_rows:
        tax_ts = pd.Timestamp(tax["date"])
        best_di = None
        best_key = None
        for di, div in enumerate(dividend_rows):
            if tax["isin"] and div["isin"] and tax["isin"] != div["isin"]:
                continue
            gap = abs((pd.Timestamp(div["date"]) - tax_ts).days)
            if gap > 5:
                continue
            # Nearest wins; on a tie the payment that has no tax on it yet.
            # Distance alone let both tax rows of two payments two days apart
            # land on the first one — the year total stayed right while one
            # payment read as heavily taxed and the other as untaxed.
            key = (gap, assigned.get(di, 0))
            if best_key is None or key < best_key:
                best_di, best_key = di, key
        if best_di is not None:
            tax_by_div[best_di] = tax_by_div.get(best_di, 0.0) + tax["amount_eur"]
            assigned[best_di] = assigned.get(best_di, 0) + 1

    for div_idx, div in enumerate(dividend_rows):
        currency = div["currency"]
        amount_raw = div["amount"]
        div_ts = pd.Timestamp(div["date"])

        # ---- Convert to EUR ----
        if currency == "EUR":
            gross_eur = amount_raw

        else:
            # Find the closest "Valuta Debitering" row for this currency
            # within a [0, +7] day window after the dividend date.
            # The FX rate is: foreign-currency units per EUR
            # → EUR = foreign_amount / fx_rate
            best_fx = None
            best_gap = float("inf")
            for fxd in fx_debit_rows:
                if fxd["currency"] != currency:
                    continue
                fxd_ts = pd.Timestamp(fxd["date"])
                gap = (fxd_ts - div_ts).days  # positive = debitering after dividend
                if 0 <= gap <= 7 and gap < best_gap:
                    best_gap = gap
                    best_fx = fxd

            # Nothing in the window is the common case at a file boundary: a
            # December dividend converted in January has its debitering row in
            # the *next* export. Dropping the payment there cost real money out
            # of every dividend total, silently — the warning only ever reached
            # the server log. So fall back to the nearest rate this file does
            # have for the currency, in either direction. A rate from a few days
            # off is worth a fraction of a percent; a missing payment is worth
            # all of it.
            if best_fx is None:
                nearest = min(
                    (f for f in fx_debit_rows if f["currency"] == currency),
                    key=lambda f: abs((pd.Timestamp(f["date"]) - div_ts).days),
                    default=None,
                )
                if nearest is not None:
                    best_fx = nearest
                    print(
                        f"  Note: no FX rate within 7 days of the {currency} dividend "
                        f"({div['name']}, {div['date']}) — using the rate of "
                        f"{nearest['date']} instead."
                    )

            if best_fx:
                gross_eur = amount_raw / best_fx["fx_rate"]
            else:
                # No rate for this currency anywhere in the file. Still skipped,
                # but the caller is told so it can say it on screen rather than
                # quietly reporting a smaller total.
                skipped_no_fx.append(
                    {
                        "date": div["date"],
                        "name": div["name"],
                        "currency": currency,
                        "amount": amount_raw,
                    }
                )
                print(f"  Warning: no FX rate found for {currency} dividend ({div['name']}, {div['date']}) — skipped.")
                continue

        # ---- Withholding tax assigned to this payment ----
        tax_eur = tax_by_div.get(div_idx, 0.0)
        net_eur = gross_eur + tax_eur

        results.append(
            {
                "date": div["date"],
                "isin": div["isin"],
                "name": div["name"],
                "currency_original": div["currency"],
                "amount_original": round(amount_raw, 6),
                "gross_eur": round(gross_eur, 4),
                "tax_eur": round(tax_eur, 4),
                "net_eur": round(net_eur, 4),
            }
        )

    results.sort(key=lambda d: d["date"])
    print(f"  → Found {len(results)} dividend payment(s)")
    return results
