"""
Everything the Details tab shows (app.py:600-849): the positions table with the
exact prices behind every dashboard number, the ticker-override editor, all
transactions, dividends, and closed positions.

Aggregation stays here rather than in the browser. app.py sums dividends with a
pandas groupby; summing the same floats in JS instead would be a reimplementation
that can disagree in the last cent, and a cent is exactly what this tab exists to
let the user reconcile against DeGiro.
"""

import sqlite3

import pandas as pd
from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.deps import get_db
from app.services.portfolio_service import load_portfolio
from domain import database
from domain.i18n import tr
from domain.portfolio import positions as portfolio

router = APIRouter(prefix="/api", tags=["details"])


@router.get("/positions")
def positions(conn: sqlite3.Connection = Depends(get_db)):
    """Open positions, each carrying when its price was fetched.

    The fetch timestamp is per position, not per request: app.py:613 reads it
    from the price row so a stale line is visible as stale, next to the others.
    """
    bundle = load_portfolio(conn)
    rows = [
        {
            **p,
            "price_fetched_at": (bundle.prices.get(p["isin"]) or {}).get("fetched_at"),
            # This tab is per ISIN. For a fund held on two exchanges with
            # different prices the price is the share-weighted mean of the two
            # — the one that makes the value column right — and says so.
            "price_blended": bool((bundle.prices.get(p["isin"]) or {}).get("blended")),
        }
        for p in bundle.positions
    ]
    # app.py:650 sums only the priced positions — an unpriced one contributes
    # nothing rather than counting as zero.
    priced_total = sum(p["current_value"] for p in bundle.positions if p["current_value"] is not None)
    return {"positions": rows, "priced_total": priced_total}


@router.get("/positions/closed")
def closed_positions(conn: sqlite3.Connection = Depends(get_db)):
    transactions = database.load_transactions(conn)
    return {"positions": portfolio.calculate_closed_positions(transactions)}


@router.get("/transactions")
def transactions(conn: sqlite3.Connection = Depends(get_db)):
    return {"transactions": database.load_transactions(conn)}


@router.get("/dividends")
def dividends(conn: sqlite3.Connection = Depends(get_db)):
    """Per-stock totals plus the individual payments behind them.

    The groupby mirrors app.py:765-783 exactly — same aggregations, same
    descending sort by net — so the two tabs cannot disagree on a total.
    """
    payments = database.load_dividends(conn)
    if not payments:
        return {"by_stock": [], "payments": []}

    df = pd.DataFrame(payments)
    by_stock = (
        df.groupby(["isin", "name"])
        .agg(
            payments=("net_eur", "count"),
            gross_eur=("gross_eur", "sum"),
            tax_eur=("tax_eur", "sum"),
            net_eur=("net_eur", "sum"),
        )
        .reset_index()
        .sort_values("net_eur", ascending=False)
    )
    return {"by_stock": by_stock.to_dict(orient="records"), "payments": payments}


@router.get("/ticker-overrides")
def ticker_overrides(conn: sqlite3.Connection = Depends(get_db)):
    return {"overrides": database.load_ticker_overrides(conn)}


@router.put("/ticker-overrides/{isin}")
def save_ticker_override(
    isin: str,
    ticker: str = Body(..., embed=True),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Pin an ISIN to a Yahoo ticker and re-fetch its price from there.

    Mirrors app.py:689-712, including its order: the override is written before
    the fetch is attempted, so it persists even when the ticker turns out to be
    wrong or non-EUR. That is deliberate parity, not an endorsement — the user
    still sees the error and can correct or remove it, and refusing to store it
    would silently discard what they typed.
    """
    # Upper-cased, not merely stripped. Yahoo resolves "spy" and "SPY" alike, so
    # a lower-case override priced correctly and looked accepted — but every
    # chart matches the stored string against yf.download's columns, which are
    # always upper case, and the position then dropped out of the intraday sum
    # and flat-lined in the history. charts.py normalises on its side too, so
    # overrides already stored this way are covered; this stops new ones.
    ticker = ticker.strip().upper()
    if not ticker:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("Enter a ticker first."))

    position = next((p for p in load_portfolio(conn).positions if p["isin"] == isin), None)
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("No open position for {0}.", isin))

    database.save_ticker_override(conn, isin, ticker)
    result = portfolio.fetch_price_for_isin(conn, isin, position["name"])

    if result and result.get("currency") == "EUR":
        database.save_price(
            conn,
            isin=isin,
            name=position["name"],
            ticker=result["ticker"],
            price=result["price"],
            currency=result["currency"],
            # save_price rewrites the whole row, so omitting this blanks the
            # previous close — and the position then silently drops out of the
            # day chip ("today") until the next full refresh puts one back.
            previous_close=result.get("previous_close"),
            quote_currency=result.get("quote_currency"),
            quote_fx_rate=result.get("quote_fx_rate"),
        )
        return {"ok": True, "ticker": result["ticker"], "price": result["price"]}

    if result:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            tr("{0} is priced in {1}, not EUR. Pick a listing in euros (e.g. the .DE or .AS one).", ticker, result.get("currency")),
        )
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        tr("No price found for '{0}'. Check the symbol on finance.yahoo.com.", ticker),
    )


@router.delete("/ticker-overrides/{isin}")
def delete_ticker_override(isin: str, conn: sqlite3.Connection = Depends(get_db)):
    """Drop the override and re-resolve automatically (app.py:714-718)."""
    database.delete_ticker_override(conn, isin)
    portfolio.refresh_all_prices(conn)
    return {"ok": True}
