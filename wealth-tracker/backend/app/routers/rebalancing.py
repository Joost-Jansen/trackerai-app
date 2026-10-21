"""
The Rebalancing tab (app.py:1118-1525), behind the same beta flag app.py:375
gates it with.

Two views over one idea — how far from target are you, and where should the next
euro go: Stocks/Bonds by hand-assigned category, and US/Europe/Emerging Markets
by look-through country data from the ETF tab's breakdown.

The arithmetic lives in services/rebalancing_service.py; this only routes.
"""

import sqlite3

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from app.deps import CurrentUser, get_current_user, get_db
from app.services import etf_service
from app.services import rebalancing_service as rb
from app.services.portfolio_service import load_portfolio
from domain import database
from domain.i18n import tr

router = APIRouter(prefix="/api/rebalancing", tags=["rebalancing"])

_BETA_FEATURE = "rebalancing"


def require_rebalancing_beta(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """app.py:375 hides the whole tab unless the account has the beta flag.

    Enforced here as well as in the nav: a hidden tab whose endpoints answer
    anyone is not gated, it is merely unlinked.
    """
    if _BETA_FEATURE not in user.beta_features:
        raise HTTPException(status.HTTP_403_FORBIDDEN, tr("Rebalancing is not turned on for this account."))
    return user


@router.get("/allocation")
def allocation(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(require_rebalancing_beta),
):
    """Targets, each position's category, and where the portfolio actually sits."""
    positions = load_portfolio(conn).positions
    targets = rb.load_targets(conn)
    rows = rb.categorise(conn, positions)
    by_category, current_pcts, total = rb.allocation(positions, {r["isin"]: r["category"] for r in rows})
    return {
        "targets": targets,
        "positions": rows,
        "by_category": by_category,
        "current_pcts": current_pcts,
        "total_value": total,
        "status": {cat: rb.deviation_status(current_pcts[cat], targets[cat]) for cat in rb.CATEGORIES},
    }


@router.put("/targets")
def save_targets(
    stocks: int = Body(..., embed=True),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(require_rebalancing_beta),
):
    """Only Stocks is set; Bonds is the remainder, so the two always make 100."""
    return {"targets": rb.save_targets(conn, stocks)}


@router.put("/categories")
def save_categories(
    categories: dict[str, str] = Body(..., embed=True),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(require_rebalancing_beta),
):
    for isin, category in categories.items():
        if category not in rb.CATEGORIES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("Unknown category '{0}' for {1}.", category, isin))
    for isin, category in categories.items():
        database.save_asset_category(conn, isin, category)
    return {"ok": True, "saved": len(categories)}


@router.get("/next-investment")
def next_investment(
    amount: float = Query(..., ge=0),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(require_rebalancing_beta),
):
    positions = load_portfolio(conn).positions
    targets = rb.load_targets(conn)
    rows = rb.categorise(conn, positions)
    by_category, _pcts, total = rb.allocation(positions, {r["isin"]: r["category"] for r in rows})
    return rb.split_investment(by_category, targets, total, amount, rb.CATEGORIES)


# ---------------------------------------------------------------------------
# Market allocation (US / Europe / Emerging Markets)
# ---------------------------------------------------------------------------


def _market_state(conn: sqlite3.Connection):
    """Equity value and its US/Europe/EM split, from the ETF tab's breakdown.

    Reuses etf_service, so this view and the ETF tab cannot disagree about which
    country a holding is in, and the (slow) holdings fetch is cached once for
    both.
    """
    positions = load_portfolio(conn).positions
    breakdown = etf_service.get_breakdown(conn, positions)
    equity_value = sum(c["current_value"] for c in breakdown["coverage"] if c["region_data"] != "excluded")
    by_market = rb.market_allocation(breakdown["region_totals"], equity_value)
    return by_market, equity_value


@router.get("/market")
def market(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(require_rebalancing_beta),
):
    by_market, equity_value = _market_state(conn)
    targets = rb.load_market_targets(conn)
    current_pcts = {b: (by_market.get(b, 0.0) / equity_value * 100) if equity_value else 0.0 for b in rb.MARKET_BUCKETS}
    return {
        "targets": targets,
        "by_market": by_market,
        "current_pcts": current_pcts,
        "equity_value": equity_value,
        "other_value": by_market.get(rb.OTHER_MARKET, 0.0),
        "status": {b: rb.deviation_status(current_pcts[b], targets[b]) for b in rb.MARKET_BUCKETS},
    }


@router.put("/market/targets")
def save_market_targets(
    targets: dict[str, int] = Body(..., embed=True),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(require_rebalancing_beta),
):
    """app.py:1416 only enables Save when the three make 100 — same rule here."""
    total = sum(int(targets.get(b, 0)) for b in rb.MARKET_BUCKETS)
    if total != 100:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            tr("US + Europe + Emerging markets = {0}%, but together they must be 100%.", total),
        )
    return {"targets": rb.save_market_targets(conn, targets)}


@router.get("/market/next-investment")
def market_next_investment(
    amount: float = Query(..., ge=0),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(require_rebalancing_beta),
):
    by_market, equity_value = _market_state(conn)
    targets = rb.load_market_targets(conn)
    return rb.split_investment(by_market, targets, equity_value, amount, rb.MARKET_BUCKETS)


# The four Plotly figures this router used to serve (charts/allocation,
# charts/after-investment and their market twins) are gone: every number they
# drew is already in the /allocation, /next-investment, /market and
# /market/next-investment payloads above, so the frontend draws them itself
# with components/rebalancing/AllocationBars. See CHART_MIGRATION_PLAN.md.
