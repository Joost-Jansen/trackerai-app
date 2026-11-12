"""
What if you had kept the portfolio of a day: the holdings on a date, the snapshots
stored of them, and the comparison the dashboard's value card draws as a third line.
The arithmetic is in domain/portfolio/what_if.py; this file fetches and caches.
"""

import datetime
import sqlite3

from app.services import dashboard_service
from app.services.portfolio_service import PortfolioBundle
from domain import database
from domain.i18n import tr
from domain.portfolio import etf_holdings, what_if
from domain.portfolio import series as charts

_CLOSES_TTL_SECONDS = 3600
MAX_SNAPSHOTS = 50
MAX_NAME = 80


class BadRequest(ValueError):
    pass


def parse_day(value: str | None, *, default: datetime.date | None = None) -> datetime.date:
    if not value:
        if default is None:
            raise BadRequest(tr("A date is needed."))
        return default
    try:
        day = datetime.date.fromisoformat(value[:10])
    except ValueError as e:
        raise BadRequest(tr("Not a date: {0}", value)) from e
    if day > datetime.date.today():
        raise BadRequest(tr("That date is in the future."))
    return day


def _eur_price(prices: dict[str, dict], isin: str) -> float | None:
    p = prices.get(isin) or {}
    return p.get("price") if p.get("currency") == "EUR" and p.get("price") is not None else None


def holdings_at(conn: sqlite3.Connection, bundle: PortfolioBundle, day: datetime.date) -> dict:
    """What was held at the end of *day*, valued on that day and today.

    The value on the day is that day's close (the last one before it on a day the
    market was shut); today's is the live price, as on the Portfolio tab.
    """
    holdings = what_if.holdings_on(bundle.transactions, day)
    closes = _closes(conn, bundle.prices, [h["isin"] for h in holdings], day)
    rows = []
    for h in holdings:
        then = what_if._price_on(closes.get(h["isin"], []), day.isoformat())
        now = _eur_price(bundle.prices, h["isin"])
        rows.append(
            {
                **h,
                "price_then": None if then is None else round(then, 4),
                "value_then": None if then is None else round(h["quantity"] * then, 2),
                "price_now": now,
                "value_now": None if now is None else round(h["quantity"] * now, 2),
            }
        )
    total_then = sum(r["value_then"] or 0 for r in rows)
    for r in rows:
        r["weight_then_pct"] = round(100 * (r["value_then"] or 0) / total_then, 2) if total_then else None
    return {
        "date": day.isoformat(),
        "holdings": rows,
        "total_value_then": round(total_then, 2),
        "total_value_now": round(sum(r["value_now"] or 0 for r in rows), 2),
        "total_cost": round(sum(r["cost_eur"] for r in rows), 2),
    }


def _closes(conn: sqlite3.Connection, prices: dict[str, dict], isins: list[str], start: datetime.date) -> dict[str, list]:
    """{isin: [(iso date, EUR close), …]} from a week before *start* to today.

    The week before is so a Saturday has Friday's close to carry. Cached for the
    hour like the value card; an ISIN whose history can't be fetched is absent and
    the comparison falls back for it (what_if.compare names it).
    """
    subset = {i: prices[i] for i in isins if i in prices}
    if not subset:
        return {}
    since = start - datetime.timedelta(days=7)
    today = datetime.date.today()
    key = f"what-if:closes:{dashboard_service._fingerprint(sorted(subset.items()), since, today)}"

    def fetch():
        series = charts._eur_daily_closes(
            subset,
            start=since.isoformat(),
            end=(today + datetime.timedelta(days=1)).isoformat(),
            auto_adjust=True,
        )
        return {isin: [[d.date().isoformat(), float(v)] for d, v in s.sort_index().items()] for isin, s in series.items()}

    try:
        raw = database.get_or_fetch(conn, key, _CLOSES_TTL_SECONDS, fetch)
    except charts.DataUnavailable:
        return {}
    return {isin: [(d, v) for d, v in rows] for isin, rows in raw.items()}


def compare(conn: sqlite3.Connection, bundle: PortfolioBundle, holdings: list[dict], start: datetime.date) -> dict:
    """The real portfolio next to *holdings* kept since *start* (what_if.compare)."""
    history = dashboard_service.pin_to_total(
        dashboard_service.get_value_history(conn, bundle.transactions, bundle.prices, bundle.dividends),
        bundle.positions,
        bundle.summary["total_value"],
    )
    if history.get("unavailable"):
        return {"points": [], "summary": None, "holdings": [], "estimated": [], "unavailable": True}
    closes = _closes(conn, bundle.prices, [h["isin"] for h in holdings], start)
    live = {h["isin"]: p for h in holdings if (p := _eur_price(bundle.prices, h["isin"])) is not None}
    return what_if.compare(history.get("points") or [], holdings, start, closes, live)


def kept_index(
    conn: sqlite3.Connection, bundle: PortfolioBundle, holdings: list[dict], start: datetime.date, *, exclude_bonds: bool
) -> dict:
    """The kept holdings' growth since *start* (what_if.growth), bond funds left out on request.

    Bonds are told apart as the Returns tab tells them apart (etf_holdings.bond_isins),
    so with its "Leave bonds out" on, both its lines leave out the same funds.
    """
    excluded: list[str] = []
    if exclude_bonds:
        bonds = etf_holdings.bond_isins(
            conn, [{"isin": h["isin"], "ticker": (bundle.prices.get(h["isin"]) or {}).get("ticker")} for h in holdings]
        )
        excluded = [h["name"] for h in holdings if h["isin"] in bonds]
        holdings = [h for h in holdings if h["isin"] not in bonds]
    closes = _closes(conn, bundle.prices, [h["isin"] for h in holdings], start)
    return {**what_if.growth(holdings, start, closes), "excluded": excluded}


# ── Snapshots ──────────────────────────────────────────────────────────────


def _out(s: dict) -> dict:
    return {
        "id": s["id"],
        "name": s["name"],
        "date": s["taken_on"],
        "created_at": s["created_at"],
        "holdings": s["holdings"],
        "total_cost": round(sum(h.get("cost_eur") or 0 for h in s["holdings"]), 2),
    }


def list_snapshots(conn: sqlite3.Connection) -> list[dict]:
    return [_out(s) for s in database.list_portfolio_snapshots(conn)]


def get_snapshot(conn: sqlite3.Connection, snapshot_id: int) -> dict | None:
    s = database.load_portfolio_snapshot(conn, snapshot_id)
    return _out(s) if s else None


def save_snapshot(conn: sqlite3.Connection, bundle: PortfolioBundle, day: datetime.date, name: str | None) -> dict:
    """Stores the holdings at the end of *day* under *name* (default: the date)."""
    name = (name or "").strip()[:MAX_NAME] or tr("Portfolio of {0}", day.isoformat())
    holdings = what_if.holdings_on(bundle.transactions, day)
    if not holdings:
        raise BadRequest(tr("There were no holdings at the end of {0}.", day.isoformat()))
    if len(database.list_portfolio_snapshots(conn)) >= MAX_SNAPSHOTS:
        raise BadRequest(tr("At most {0} snapshots; delete one first.", MAX_SNAPSHOTS))
    now = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    new_id = database.insert_portfolio_snapshot(conn, name, day.isoformat(), holdings, now)
    return get_snapshot(conn, new_id)
