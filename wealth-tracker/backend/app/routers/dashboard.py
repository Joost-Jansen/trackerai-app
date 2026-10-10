import sqlite3

from fastapi import APIRouter, Depends

from app.deps import get_db
from app.services import dashboard_service, etf_service, holdings_service
from app.services.portfolio_service import load_portfolio

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(conn: sqlite3.Connection = Depends(get_db)):
    bundle = load_portfolio(conn)
    stamps = [p["fetched_at"] for p in bundle.prices.values() if p.get("fetched_at")]
    latest_fetch = max(stamps, default=None)
    # The oldest is what the totals are really only as current as. On its own
    # `latest_price_fetch` reads "just now" when a single ISIN refreshed and the
    # rest of the portfolio is days behind, which is precisely the state worth
    # noticing. Both are sent: the line shows the oldest, and the pair together
    # is what makes a partly-failed refresh visible.
    oldest_fetch = min(stamps, default=None)
    return {
        # The hero's breakdown reads as a sum, so it needs the cost-exclusive
        # split alongside the net one the summary carries. Merged here rather
        # than added to calculate_portfolio_summary: that function is shared
        # with the still-running Streamlit app, and its unrealized/realized keys
        # must keep meaning "net of costs" there.
        "summary": {**bundle.summary, **holdings_service.gross_result_split(bundle)},
        "latest_price_fetch": latest_fetch,
        "oldest_price_fetch": oldest_fetch,
        "num_positions": len(bundle.positions),
        # Open positions with no price at all. They sit out every total, so the
        # hero shows "—" — and without naming them here nothing on the owner's
        # screen said why. The dashboard puts them in a warning above the total.
        "unpriced": [
            {"isin": p["isin"], "name": p["name"]}
            for p in bundle.positions
            if p["current_value"] is None
        ],
        # None until a price refresh has stored previous_close values —
        # the hero's day chip hides itself rather than show a made-up 0,00%.
        "day": dashboard_service.portfolio_day_change(bundle.positions, bundle.prices),
    }


@router.get("/sparkline")
def sparkline(conn: sqlite3.Connection = Depends(get_db)):
    """The hero's last-month value line. Served from the same cached segments
    the benchmark charts use, so after the first hit it costs one SELECT."""
    bundle = load_portfolio(conn)
    return {
        "points": dashboard_service.get_sparkline(
            conn, bundle.transactions, bundle.prices, bundle.dividends
        )
    }


@router.get("/value-history")
def value_history(conn: sqlite3.Connection = Depends(get_db)):
    """Own-portfolio value over time in EUR (invested / value / value+dividends).

    One payload covers every range button: the frontend slices locally, so
    toggling 1M -> All costs no request. Empty `points` when there is nothing
    priceable yet — the card then hides, like the other Tier-1 cards. Today's
    point is the hero's total value (see dashboard_service.pin_to_total), so the
    card's "All" and Total return are one number.
    """
    bundle = load_portfolio(conn)
    history = dashboard_service.get_value_history(
        conn, bundle.transactions, bundle.prices, bundle.dividends
    )
    return dashboard_service.pin_to_total(
        history, bundle.positions, bundle.summary["total_value"]
    )


@router.get("/intraday")
def intraday(conn: sqlite3.Connection = Depends(get_db)):
    """Today's portfolio value per 5 minutes, for the card's 1D range.

    Separate from /value-history because it is a different cadence with a
    different TTL, and because it is only worth fetching when 1D is selected —
    the frontend asks for it lazily. Empty `points` is a normal answer (holiday,
    no minute bars); the card then falls back to the daily series.

    `positions` anchors the day's endpoints to the same prices the hero chip
    uses, so the two cannot report different day returns.
    """
    bundle = load_portfolio(conn)
    return dashboard_service.get_intraday(
        conn, bundle.transactions, bundle.prices, bundle.positions
    )


@router.get("/allocation")
def allocation(conn: sqlite3.Connection = Depends(get_db)):
    """Sector look-through donut (+ region for the 'switch to region' toggle).

    Reuses the Allocation tab's engine and its 24h cache — the dashboard and that
    tab must never disagree about a slice.
    """
    bundle = load_portfolio(conn)
    data = etf_service.get_breakdown(conn, bundle.positions)
    return {
        "sector": etf_service.as_slices(data["sector_totals"]),
        "region": etf_service.as_slices(data["continent_totals"]),
        "excluded_pct": data["excluded_pct"],
        "num_positions": len(bundle.positions),
    }


@router.get("/dividends")
def dividends(conn: sqlite3.Connection = Depends(get_db)):
    """Received (this month / this year) plus the forecast: expected payments
    for the coming months, projected from the user's own payment history —
    the official calendar covers none of the UCITS ETFs, so the estimate is the
    primary engine, with a real upcoming ex-div overriding where one exists.
    """
    bundle = load_portfolio(conn)
    return {
        **dashboard_service.dividend_stats(bundle.dividends),
        "outlook": dashboard_service.dividend_outlook(
            conn, bundle.positions, bundle.dividends, bundle.transactions
        ),
    }


@router.get("/movers")
def movers(conn: sqlite3.Connection = Depends(get_db)):
    """Biggest riser/faller today, for the attention card."""
    bundle = load_portfolio(conn)
    return dashboard_service.day_movers(bundle.positions, bundle.prices)


@router.post("/visit")
def visit(conn: sqlite3.Connection = Depends(get_db)):
    """Registers this page load; answers with the previous session's diff.

    POST, not GET: it writes (the snapshot row). The dashboard calls it once
    per load.
    """
    bundle = load_portfolio(conn)
    total_value = (
        bundle.summary["total_value"] if bundle.summary["prices_available"] else None
    )
    diff = dashboard_service.record_visit(conn, total_value)
    if diff is None:
        return {"since": None}

    # Whether the strip may follow the day chip is a question about sessions,
    # not about dates: a visit at 08:00 this morning sits in the same gap
    # between two sessions as one from yesterday at 22:57, and both have
    # exactly today's move behind them. Gating this on "an earlier calendar
    # day", as it once did, left the morning case reporting its own snapshot
    # under a chip saying something else — the very split the alignment exists
    # to close. The intraday series carries both bounds of that gap, and it is
    # cached for five minutes (and fetched by the 1D card anyway), so asking
    # for it on every visit costs a SELECT.
    intraday = dashboard_service.get_intraday(
        conn, bundle.transactions, bundle.prices, bundle.positions
    )
    diff = dashboard_service.align_visit_with_the_day(
        diff,
        dashboard_service.previous_close_at(intraday),
        dashboard_service.session_start_at(intraday),
        dashboard_service.portfolio_day_change(bundle.positions, bundle.prices),
    )

    return {
        "since": {
            **diff,
            "dividends": dashboard_service.dividends_since(
                bundle.dividends, diff["last_seen_at"]
            ),
        }
    }


@router.get("/news")
def news(conn: sqlite3.Connection = Depends(get_db)):
    """Latest headlines across the holdings. [] on any failure, by design."""
    bundle = load_portfolio(conn)
    return {"items": dashboard_service.get_news(conn, bundle.positions)}


@router.get("/ex-dividends")
def ex_dividends(conn: sqlite3.Connection = Depends(get_db)):
    """Upcoming ex-dividend dates with a 'expected' estimate from the last
    payment. [] when the calendar has nothing (common for ETFs) or fails.
    """
    bundle = load_portfolio(conn)
    return {"items": dashboard_service.get_ex_dividends(conn, bundle.positions, bundle.dividends)}


# The original dashboard's four Plotly figures used to be served from here as
# well, for side-by-side parity checks against the Streamlit app. That app is
# retired and nothing in frontend/ ever asked for these, so they are gone —
# see CHART_MIGRATION_PLAN.md.
#
# /performance went the same way, and for a sharper reason: it served a TWR
# index against the MSCI World for a card this dashboard deliberately does not
# have. TWR has no euro counterpart, so beside "+€3.543,57" a "+112,5%" reads
# as "I more than doubled my money" — which is why that measure lives on the
# Returns tab with the paragraph it needs, and why an endpoint aimed back at
# this screen was worth deleting rather than leaving for someone to plug in.
