"""
The Dividend tab, behind its own beta flag.

One endpoint, like /api/returns: the whole tab is one pass over the payment
history, and every card on it needs the same three inputs. Splitting it would
mean loading the portfolio bundle four times for one page load.

Singular `/api/dividend` on purpose — the plural is taken. `/api/dividends`
belongs to the Details tab (routers/details.py), which serves the flat
per-stock totals and the raw payment log that tab has always had.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import CurrentUser, get_current_user, get_db
from app.services import dashboard_service, dividend_service
from app.services.portfolio_service import load_portfolio
from domain.i18n import tr

router = APIRouter(prefix="/api/dividend", tags=["dividend"])

_BETA_FEATURE = "dividends"


def require_dividend_beta(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Enforced here as well as in the nav, for the same reason /api/returns
    does it: a hidden tab whose endpoint answers anyone is not gated, it is
    merely unlinked."""
    if _BETA_FEATURE not in user.beta_features:
        raise HTTPException(status.HTTP_403_FORBIDDEN, tr("Dividend is not turned on for this account."))
    return user


@router.get("")
def dividend(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(require_dividend_beta),
):
    """Received dividends, the schedule ahead, and the aggregations over both.

    Not cached: the only slow part is the ex-dividend calendar, and
    dashboard_service.get_ex_dividends already caches that fetch behind its own
    key. What is left is arithmetic over a few hundred rows.

    An account with no dividends at all still gets a well-formed payload —
    empty lists and zeroed totals — so the tab renders its own empty state
    rather than an error.
    """
    bundle = load_portfolio(conn)
    outlook = dashboard_service.dividend_outlook(conn, bundle.positions, bundle.dividends, bundle.transactions)
    return dividend_service.build(
        bundle.positions,
        bundle.transactions,
        bundle.dividends,
        outlook,
        summary=bundle.summary,
    )
