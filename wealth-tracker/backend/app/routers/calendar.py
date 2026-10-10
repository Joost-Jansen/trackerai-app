"""
The Calendar tab, behind its own beta flag.

One endpoint, like /api/dividend and for the same reason: the page is one pass
over the portfolio and every block on it needs the same inputs.

It reuses the dividend outlook rather than recomputing a schedule of its own.
Two forecasts of the same payments would drift apart the moment either changed,
and the user would be looking at two different answers to one question on two
tabs.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import CurrentUser, get_current_user, get_db
from app.services import calendar_service, dashboard_service
from app.services.portfolio_service import load_portfolio
from domain.i18n import tr

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

_BETA_FEATURE = "calendar"


def require_calendar_beta(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Enforced here as well as in the nav: a hidden tab whose endpoint answers
    anyone is not gated, it is merely unlinked."""
    if _BETA_FEATURE not in user.beta_features:
        raise HTTPException(status.HTTP_403_FORBIDDEN, tr("Calendar is not turned on for this account."))
    return user


@router.get("")
def calendar(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(require_calendar_beta),
):
    """Reporting dates, ex-dividend dates, paid dividends, and the estimates.

    Not cached at this level: the slow part is the Yahoo sweep, which
    dashboard_service caches behind its own key and shares with the dashboard's
    ex-dividend card. What is left is arithmetic over a few hundred rows plus
    two lookups that carry their own caches (see filings_service).

    An account with no shares still gets a well-formed payload — the tab uses
    `share_count` to explain an empty grid rather than showing an error.
    """
    bundle = load_portfolio(conn)
    entries = dashboard_service.get_calendar_entries(conn, bundle.positions)
    outlook = dashboard_service.dividend_outlook(
        conn, bundle.positions, bundle.dividends, bundle.transactions
    )
    return calendar_service.build(
        conn, bundle.positions, bundle.dividends, outlook, entries,
    )
