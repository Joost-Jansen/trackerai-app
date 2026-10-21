"""
The Returns tab, behind its own beta flag.

One endpoint: the whole tab is one pass over the daily series, and splitting it
would mean building that series twice. Cached on a fingerprint of the inputs,
like the other series endpoints — the TWR index runs a yfinance history
download through charts.portfolio_history_series.
"""

import datetime
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import CurrentUser, get_current_user, get_db
from app.services import returns_service
from app.services.dashboard_service import _fingerprint
from app.services.portfolio_service import load_portfolio
from domain import database
from domain.i18n import tr
from domain.portfolio import series as charts

router = APIRouter(prefix="/api/returns", tags=["returns"])

_BETA_FEATURE = "returns"
_TTL_SECONDS = 3600


def require_returns_beta(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Enforced here as well as in the nav: a hidden tab whose endpoints answer
    anyone is not gated, it is merely unlinked."""
    if _BETA_FEATURE not in user.beta_features:
        raise HTTPException(status.HTTP_403_FORBIDDEN, tr("Returns is not turned on for this account."))
    return user


@router.get("")
def returns(
    start: str | None = None,
    end: str | None = None,
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(require_returns_beta),
):
    """TWR index over time, plus TWR / IRR / simple return per range.

    Empty `points` when there is nothing priceable yet — the tab then shows its
    empty state rather than an error, like every other card in this app.
    """
    bundle = load_portfolio(conn)
    if not bundle.transactions:
        return {"points": [], "gaps": [], "ranges": []}
    # A custom window, dragged out on the chart.
    window = None
    if start and end:
        try:
            window = (datetime.date.fromisoformat(start).isoformat(), datetime.date.fromisoformat(end).isoformat())
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("Dates as YYYY-MM-DD."))
    # One cache entry for the whole history (the slow part); a custom window is
    # worked out from its `_series` in milliseconds, so dragging on the chart
    # does not recompute everything. "returns2": entries from before `_series`.
    key = f"returns2:{_fingerprint(bundle.transactions, bundle.prices, bundle.dividends)}"
    try:
        built = database.get_or_fetch(
            conn,
            key,
            _TTL_SECONDS,
            lambda: returns_service.build(bundle.transactions, bundle.prices, bundle.dividends),
        )
        answer = {k: v for k, v in built.items() if k != "_series"}
        if window and built.get("_series"):
            custom = returns_service.custom_range(built["_series"], window)
            if custom is not None:
                answer["ranges"] = [*answer["ranges"], custom]
        return answer
    except charts.DataUnavailable:
        # Without this the whole tab reads 0,00% — every holding falls back to
        # its cost basis, so the day value equals the amount invested and the
        # TWR index never leaves 100. That sat next to a simple return of
        # +16,67% computed from the price cache, two numbers over the same
        # period disagreeing because they degraded differently. Neither is
        # worth showing when the closes never arrived.
        return {"points": [], "gaps": [], "ranges": [], "unavailable": True}
