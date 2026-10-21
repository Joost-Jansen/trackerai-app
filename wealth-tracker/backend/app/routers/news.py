"""
The News tab: three headline feeds built by app/services/news_service.py.

Every endpoint returns {"items": [...]} and answers [] on any failure by design
(the service swallows provider errors), so the frontend never has to special-case
a dead feed — an empty list just renders as "no news".
"""

import sqlite3

from fastapi import APIRouter, Depends

from app.deps import get_db
from app.services import etf_service, news_service
from app.services.portfolio_service import load_portfolio

router = APIRouter(prefix="/api/news", tags=["news"])

# How many of the largest look-through holdings the etf-top feed covers.
_ETF_TOP_N = 5


@router.get("/market")
def market(conn: sqlite3.Connection = Depends(get_db)):
    """World/market news that moves the exchange (tariffs, a ceasefire, the ECB)."""
    return {"items": news_service.get_market_news(conn)}


@router.get("/holdings")
def holdings(conn: sqlite3.Connection = Depends(get_db)):
    """News about the single stocks the user directly owns."""
    bundle = load_portfolio(conn)
    return {"items": news_service.get_holdings_news(conn, bundle.positions)}


@router.get("/etf-top")
def etf_top(conn: sqlite3.Connection = Depends(get_db)):
    """News about the five largest look-through holdings inside the user's ETFs.

    The ranking is the Allocation tab's stock_list (sorted by exposure value);
    we take the top five and also return their names so the tab can show which
    companies the feed is about.
    """
    exposure = etf_service.get_exposure(conn, load_portfolio(conn).positions)
    top = exposure.get("stock_list", [])[:_ETF_TOP_N]
    return {
        "items": news_service.get_etf_top_news(conn, top),
        "stocks": [{"symbol": s.get("symbol"), "name": s.get("name")} for s in top],
    }


@router.post("/refresh")
def refresh(conn: sqlite3.Connection = Depends(get_db)):
    """Drop the cached feeds so all three refetch on the next load."""
    news_service.clear_cache(conn)
    return {"ok": True}
