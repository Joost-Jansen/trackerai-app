"""
The Benchmarks tab (app.py:861-942): portfolio TWR against index funds.

Three charts over one set of inputs. app.py builds those inputs once per rerun
and hands the same `segments=` to each chart, because each would otherwise
re-download the same price history; here each chart is its own request, so the
sharing has to come from the cache instead — see services/benchmark_service.py.
"""

import datetime as dt
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, status

from domain.portfolio import series as charts
from domain.portfolio import etf_holdings
from app.deps import get_db
from app.services import benchmark_service
from app.services.benchmark_service import get_benchmark_prices, get_portfolio_segments
from app.services.portfolio_service import load_portfolio
from domain.i18n import tr

router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])


class _NoData(HTTPException):
    """A 422 the frontend renders as app.py's st.info/st.warning text."""

    def __init__(self, detail: str):
        super().__init__(status.HTTP_422_UNPROCESSABLE_CONTENT, detail)


def _inputs(conn: sqlite3.Connection, exclude_bonds: bool):
    """Everything the three charts share, filtered and cached (app.py:870-912)."""
    bundle = load_portfolio(conn)
    if not bundle.transactions:
        raise _NoData(tr("Upload your transactions to be able to compare your return."))

    # Bond ETFs are savings, not performance — app.py defaults to hiding them.
    #
    # etf_holdings.bond_isins, not database.bond_isins: the same three tests the
    # Allocation tab uses, so both tabs answer "is this a bond" the same way. The
    # narrower reader only sees what the user classified by hand on the
    # Rebalancing tab, which is behind a beta flag — so for an account that has
    # never opened it there is nothing to match, and this checkbox, on by
    # default, excluded nothing while saying it did. Meanwhile Allocation was
    # setting those very funds aside as bonds. Same portfolio, two answers.
    bonds = etf_holdings.bond_isins(conn, bundle.positions)

    transactions = (
        [t for t in bundle.transactions if t["isin"] not in bonds]
        if exclude_bonds else bundle.transactions
    )
    dividends = (
        [d for d in bundle.dividends if d.get("isin") not in bonds]
        if exclude_bonds else bundle.dividends
    )
    if not transactions:
        raise _NoData(tr("After excluding bonds there is nothing left to show."))

    # Start a few days early so the benchmarks cover the whole period
    # (app.py:893-898).
    first_tx_date = min(t["date"] for t in transactions)
    start = (dt.date.fromisoformat(first_tx_date) - dt.timedelta(days=5)).isoformat()

    # The advice in this message is now true. It used to be a lie by omission:
    # charts.fetch_benchmark_prices swallowed its own failure and returned {},
    # which get_or_fetch stored for the full hour, so "in a few minutes"
    # returned this very sentence again until the TTL ran out. It raises now,
    # nothing is cached, and a retry once the line is back actually works.
    try:
        benchmark_prices = get_benchmark_prices(conn, start)
        segments = get_portfolio_segments(conn, transactions, bundle.prices, dividends)
    except charts.DataUnavailable:
        raise _NoData(
            tr("The benchmark prices could not be fetched from Yahoo Finance. Try again in a few minutes.")
        )
    if not benchmark_prices:
        raise _NoData(
            tr("The benchmark prices could not be fetched from Yahoo Finance. Try again in a few minutes.")
        )

    return transactions, bundle.prices, benchmark_prices, dividends, segments


@router.get("/series")
def series(
    exclude_bonds: bool = Query(True),
    conn: sqlite3.Connection = Depends(get_db),
):
    """All three comparisons as data, in one request.

    Was three /charts/* endpoints returning Plotly figures. One request now
    because they share `segments` and `benchmark_prices` — the cache made three
    calls cheap, but not free, and the page always wanted all three anyway.
    """
    _tx, _prices, benchmark_prices, _dividends, segments = _inputs(conn, exclude_bonds)
    year = dt.date.today().year
    return {
        "indexed": benchmark_service.indexed_series(segments, benchmark_prices),
        "rolling": benchmark_service.rolling_series(segments, benchmark_prices),
        "ytd": benchmark_service.ytd_series(segments, benchmark_prices, year),
        "rolling_window_days": benchmark_service.ROLLING_WINDOW_DAYS,
        "year": year,
    }
