"""
The Allocation tab (app.py:874-1112): what your funds actually hold.

The route prefix still says etf-analysis, which was this tab's name until it
became Allocation. Kept deliberately: nobody sees it, and renaming it would put
an old frontend on a new backend for the length of a deploy.

The plan calls this tab's data-quality logic the most intricate in the app, and
sets the bar at numeric parity rather than "it renders" — so the coverage
percentages, the excluded percentage and the provenance buckets are all computed
here, by the same code app.py runs, and the page only formats them.
"""

import sqlite3

from fastapi import APIRouter, Depends

from domain import database
from domain.portfolio import etf_holdings
from app.deps import get_db
from app.services import etf_service
from app.services.portfolio_service import load_portfolio

router = APIRouter(prefix="/api/etf-analysis", tags=["etf-analysis"])

def _breakdown(conn: sqlite3.Connection) -> dict:
    return etf_service.get_breakdown(conn, load_portfolio(conn).positions)


def _exposure(conn: sqlite3.Connection) -> dict:
    return etf_service.get_exposure(conn, load_portfolio(conn).positions)


@router.get("/breakdown")
def breakdown(conn: sqlite3.Connection = Depends(get_db)):
    """The three allocations, coverage per position, excluded %, quality strip.

    sector/continent/region used to be three separate /charts/* endpoints that
    handed these same three dicts to charts.py. The frontend draws them itself
    now, so they ride along here instead — one request where there were four,
    and all four answers come from the same cached breakdown.
    """
    data = _breakdown(conn)
    return {
        "sector": etf_service.as_slices(data["sector_totals"]),
        "continent": etf_service.as_slices(data["continent_totals"]),
        # Per country, so this is the long one — tens of entries where the other
        # two have a handful.
        "region": etf_service.as_slices(data["region_totals"]),
        # The same countries with nothing folded into "Other". The balk draws
        # `region`; this is what sits behind its "Overig".
        "region_all": etf_service.as_slices(
            data.get("region_all_totals", data["region_totals"]), decimals=2
        ),
        "coverage": data["coverage"],
        "excluded_pct": data["excluded_pct"],
        "quality": etf_service.diversification_quality(data["coverage"]),
    }


@router.get("/exposure")
def exposure(conn: sqlite3.Connection = Depends(get_db)):
    """Per-company exposure, its coverage %, each fund's source, and the strip."""
    data = _exposure(conn)
    return {
        "stock_list": data["stock_list"],
        "stock_coverage": data["stock_coverage"],
        "etf_sources": data["etf_sources"],
        "quality": etf_service.exposure_quality(data["etf_sources"]),
    }


@router.post("/refresh")
def refresh_holdings(conn: sqlite3.Connection = Depends(get_db)):
    """Drop the cached holdings and this tab's derived answers, so both refetch.

    Both, not just the first: the derived answers are cached for a day of their
    own, so clearing only the holdings would leave yesterday's conclusions
    sitting on top of today's data.
    """
    database.clear_etf_api_cache(conn)
    database.clear_api_cache(conn, "etf:")
    return {"ok": True}
