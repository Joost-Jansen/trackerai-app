"""
The Portfolio tab: every open position with its cost split and its result,
both all-time and for today — and, one click deeper, a single position with the
same figures spelled out beside its own koersgrafiek.

/overview serves one payload, not one per mode: the two toggle states are the
same rows read two ways, and serving them together means flipping the toggle
costs no request and can never show today's move next to yesterday's prices.

The three /{isin} routes are split by cadence rather than merged into the
detail payload: the position's numbers are a database read, its daily closes a
download cached for an hour, and its five-minute bars a download cached for
five minutes and only worth fetching while the 1D range is selected. One
endpoint would hold the page's first paint behind the slowest of the three.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status

from domain import database
from app.deps import get_db
from app.services import (
    asset_service, etf_service, holdings_service, tradegate_service, venue_price_service,
)
from app.services.portfolio_service import load_portfolio
from domain.i18n import tr

router = APIRouter(prefix="/api/holdings", tags=["holdings"])


@router.get("/overview")
def overview(conn: sqlite3.Connection = Depends(get_db)):
    return holdings_service.overview(load_portfolio(conn))


def _price_row(conn: sqlite3.Connection, isin: str) -> dict:
    """The cached quote for an ISIN: ticker, price, previous close.

    The price table alone, not the whole bundle — the two chart endpoints need
    a symbol and two numbers, and nothing about the position's arithmetic. An
    ISIN with no row (never priced, or a ticker that never resolved) gets an
    empty dict and an empty chart: the position exists, its price history does
    not, and that is not a 404.
    """
    return database.load_prices(conn).get(isin) or {}


# Declared after /overview on purpose: FastAPI matches routes in order, and
# "/{isin}" would otherwise swallow "/overview" as an ISIN.
@router.get("/{isin}")
def position(
    isin: str,
    exchange: str | None = Query(None, description="DeGiro's venue code, for an ISIN held on two"),
    conn: sqlite3.Connection = Depends(get_db),
):
    detail = holdings_service.position_detail(load_portfolio(conn), isin, exchange)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("No open position in {0}.", isin))
    return detail


@router.get("/{isin}/breakdown")
def breakdown(
    isin: str,
    exchange: str | None = Query(None, description="DeGiro's venue code, for an ISIN held on two"),
    conn: sqlite3.Connection = Depends(get_db),
):
    """What this fund holds — its biggest positions, sectors and countries.

    Its own request rather than a part of /{isin} for the reason the other two
    have their own: the position's figures are a database read, this one can
    have to download an issuer's holdings file first. Behind one endpoint, a
    cold cache would hold the price and the average cost back for as long as that takes.

    The euro amounts come off the very position the page is already showing —
    same ISIN, same exchange — so the amounts beside the holdings add up to the
    value printed above them.

    A share is not a fund and gets the empty answer without a lookup: the ISIN
    of a listed company can otherwise still resolve to a same-index proxy by
    name, which would fill this section with a fund the user does not own.
    """
    detail = holdings_service.position_detail(load_portfolio(conn), isin, exchange)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("No open position in {0}.", isin))

    row = detail["position"]
    if row["asset_type"] != "tracker":
        return etf_service.fund_breakdown_unavailable()

    return etf_service.fund_breakdown(conn, isin, row["name"], row["current_value"])


@router.get("/{isin}/tradegate")
def tradegate_quote(
    isin: str,
    exchange: str | None = Query(None, description="DeGiro's venue code, for an ISIN held on two"),
    conn: sqlite3.Connection = Depends(get_db),
):
    """The position's price on Tradegate itself: last, bid and ask, apart.

    Its own request for the same reason as the chart routes: this one can have
    to reach an outside website, and a slow Tradegate must not hold back the
    position's figures. Only for a position held on Tradegate (ISIN + exchange);
    any other gets `not_applicable` without a request going out.

    Never an error status for Tradegate's own trouble — an outage, a refusal
    or an unknown ISIN are ordinary answers the page words for itself.
    """
    detail = holdings_service.position_detail(load_portfolio(conn), isin, exchange)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("No open position in {0}.", isin))
    if not detail["tradegate_quote"]:
        return {
            "status": "not_applicable",
            "isin": isin,
            "venue": tradegate_service.VENUE_CODE,
            "message": tr("This position is not on Tradegate but on {0}.", detail['position']['exchange'] or 'one onbekende exchange'),
        }
    quote = tradegate_service.get_quote(isin)
    # A fresh quote is this position's price from here on — stored, so the
    # figures above the block (value, result, today) use the number the
    # block shows instead of the one from the last refresh round.
    venue_price_service.save_quote(conn, quote)
    return quote


@router.get("/{isin}/history")
def history(isin: str, conn: sqlite3.Connection = Depends(get_db)):
    """The product's daily closes over its whole listed history.

    One payload for every range button; the page slices it locally, so 1M ->
    Alles costs no request. Empty points when the ISIN has no ticker or Yahoo
    has no history for it — the card then says so instead of drawing nothing.
    """
    return asset_service.daily_closes(conn, _price_row(conn, isin).get("ticker"))


@router.get("/{isin}/intraday")
def intraday(
    isin: str,
    exchange: str | None = Query(None, description="DeGiro's venue code, for an ISIN held on two"),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Today's five-minute bars, for the 1D range.

    Anchored to the position's own quote, so the last point of the line is the
    price printed above it — Tradegate's for a TDG position, whose bars still
    come from Yahoo's listing (Tradegate has no minute data to offer). Empty
    points is an ordinary answer (a holiday, a product Yahoo has no minute bars
    for); the page falls back to the daily series.
    """
    info = _price_row(conn, isin)
    quote = venue_price_service.position_quote(
        isin, exchange, database.load_prices(conn), database.load_venue_prices(conn)
    ) or info
    # The bars are in the ticker's own currency, so the anchors must be too: a
    # converted listing's stored (EUR) prices are divided back. A Tradegate
    # quote is in euros, and so is the XETRA ticker its bars come from.
    if quote.get("provider") != "tradegate":
        quote = holdings_service.listing_quote(quote)
    return asset_service.intraday_closes(
        conn,
        info.get("ticker"),
        live_price=quote.get("price"),
        previous_close=quote.get("previous_close"),
    )
