"""
Loads the same positions/prices/transactions/dividends/summary bundle that
app.py computes once at module scope (app.py:422-426) — shared by every
router that needs portfolio data (dashboard, details, benchmarks, ...).
"""

import sqlite3
from dataclasses import dataclass, field

from domain import database
from domain.portfolio import positions as portfolio
from app.services import venue_price_service


@dataclass
class PortfolioBundle:
    #: One quote per ISIN, for everything that computes per ISIN. Where a
    #: position has its own exchange's price this is the share-weighted blend
    #: over that ISIN's positions — see venue_price_service.effective_prices.
    prices: dict
    transactions: list[dict]
    dividends: list[dict]
    dividends_by_isin: dict[str, float]
    positions: list[dict]
    summary: dict
    #: {(isin, exchange): quote} from an exchange's own source (Tradegate).
    venue_prices: dict = field(default_factory=dict)
    #: The stored Yahoo quotes per ISIN, before blending. None means `prices`
    #: is already exactly that (a bundle built without venue prices).
    yahoo_prices: dict | None = None


def load_portfolio(conn: sqlite3.Connection) -> PortfolioBundle:
    yahoo_prices = database.load_prices(conn)
    venue_prices = database.load_venue_prices(conn)
    transactions = database.load_transactions(conn)
    prices = venue_price_service.effective_prices(transactions, yahoo_prices, venue_prices)
    dividends = database.load_dividends(conn)
    dividends_by_isin = database.load_dividends_by_isin(conn)
    positions = portfolio.calculate_positions(transactions, prices)
    summary = portfolio.calculate_portfolio_summary(positions, transactions, dividends)
    return PortfolioBundle(
        prices=prices, transactions=transactions, dividends=dividends,
        dividends_by_isin=dividends_by_isin, positions=positions, summary=summary,
        venue_prices=venue_prices, yahoo_prices=yahoo_prices,
    )
