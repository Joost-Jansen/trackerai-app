"""
Net worth — investments, bank and debt in one response.

One payload for the whole page, like the value card on the dashboard: the
frontend cuts the periods out itself, so going from 1Y to All costs no
request.

The arithmetic lives in domain/money/net_worth.py; the investment series comes
from dashboard_service.get_value_history, the same one that feeds the value
card. That is the same source on purpose: two places that both answer "what
is my portfolio worth" and do it slightly differently is exactly how an app
starts contradicting itself.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status

from domain.money import net_worth as net_worth_domain
from domain.money import shared_costs
from app.deps import CurrentUser, get_current_user, get_db, require_money
from app.services import dashboard_service
from app.services.portfolio_service import load_portfolio

router = APIRouter(prefix="/api/net-worth", tags=["net_worth"], dependencies=[Depends(require_money)])


@router.get("")
def overview(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """The net worth series plus the month figures below it."""
    bundle = load_portfolio(conn)
    history = dashboard_service.get_value_history(
        conn, bundle.transactions, bundle.prices, bundle.dividends
    )

    series = net_worth_domain.series(conn, history.get("points") or [])
    return {
        **series,
        "months": net_worth_domain.per_month(conn),
        # Per day: saved and deposited into investments, for the split of each
        # change into saved, market and other.
        "flows": net_worth_domain.daily_flows(conn),
        # Where your own share of shared costs counts (Settings), or None: then
        # it stays with Bank & cash as money for friends.
        "shared_costs_category": shared_costs.category(conn),
        # The prices could not be fetched. Then the investment side of the line is
        # not measured but guessed, and the page would rather say so than draw a
        # smooth line that means nothing.
        "prices_unknown": bool(history.get("unavailable")),
        # Positions whose historical price is a stand-in. Usually empty, and
        # usually harmless — but a filled-in position draws a flat line that looks
        # exactly like a real one that did not move.
        "estimated": history.get("estimated") or [],
    }


@router.get("/corrections")
def corrections(
    start: str = Query(..., description="ISO date: from the balance at the end of this day"),
    end: str = Query(..., description="ISO date: to the balance at the end of this day"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """The balance corrections in Bank & cash per account: what the balances did
    that the transactions on those accounts don't explain. See
    net_worth.bank_corrections."""
    try:
        return net_worth_domain.bank_corrections(conn, start, end)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
