"""
What if you had kept an earlier portfolio: the holdings on any date, snapshots of
them stored under a name, and the comparison with the real portfolio since then
(the dashboard value card's third line, and the MCP tools get_holdings_at,
list_snapshots and compare_portfolio).
"""

import sqlite3

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from app.deps import get_db
from app.services import what_if_service as svc
from app.services.portfolio_service import load_portfolio
from domain import database
from domain.i18n import tr
from domain.portfolio import what_if

router = APIRouter(prefix="/api/what-if", tags=["what-if"])


def _bad(e: svc.BadRequest) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/holdings")
def holdings(
    date: str = Query(..., description="ISO date: the holdings at the end of this day"), conn: sqlite3.Connection = Depends(get_db)
):
    try:
        day = svc.parse_day(date)
    except svc.BadRequest as e:
        raise _bad(e) from e
    return svc.holdings_at(conn, load_portfolio(conn), day)


@router.get("/snapshots")
def snapshots(conn: sqlite3.Connection = Depends(get_db)):
    return {"snapshots": svc.list_snapshots(conn)}


@router.post("/snapshots", status_code=status.HTTP_201_CREATED)
def save(body: dict = Body(...), conn: sqlite3.Connection = Depends(get_db)):
    try:
        day = svc.parse_day(body.get("date"))
        return svc.save_snapshot(conn, load_portfolio(conn), day, body.get("name"))
    except svc.BadRequest as e:
        raise _bad(e) from e


@router.delete("/snapshots/{snapshot_id}")
def delete(snapshot_id: int, conn: sqlite3.Connection = Depends(get_db)):
    if not database.delete_portfolio_snapshot(conn, snapshot_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("No such snapshot."))
    return {"deleted": snapshot_id}


@router.get("/compare")
def compare(
    snapshot: int | None = Query(None, description="A stored snapshot's id"),
    date: str | None = Query(None, description="Or an ISO date: the holdings at the end of it, without storing them"),
    conn: sqlite3.Connection = Depends(get_db),
):
    """The real portfolio and the kept one per day since the snapshot's date.

    Each point is {d, actual, kept}; `summary` has the gain of both over the
    period, and `holdings` what each kept holding did.
    """
    bundle = load_portfolio(conn)
    day, holdings, meta = _chosen(conn, bundle, snapshot, date)
    return {"snapshot": meta, **svc.compare(conn, bundle, holdings, day)}


@router.get("/index")
def index(
    snapshot: int | None = Query(None, description="A stored snapshot's id"),
    date: str | None = Query(None, description="Or an ISO date: the holdings at the end of it, without storing them"),
    exclude_bonds: bool = Query(False, description="Leave the snapshot's bond funds out, as the Returns tab can"),
    conn: sqlite3.Connection = Depends(get_db),
):
    """The kept portfolio's growth since the snapshot's date, 1.0 on that day.

    Dividends reinvested and no money in or out: the basis of the Returns tab's
    time-weighted return and indices, which draws it next to them. `excluded`
    names the bond funds left out.
    """
    bundle = load_portfolio(conn)
    day, holdings, meta = _chosen(conn, bundle, snapshot, date)
    return {"snapshot": meta, **svc.kept_index(conn, bundle, holdings, day, exclude_bonds=exclude_bonds)}


def _chosen(conn: sqlite3.Connection, bundle, snapshot: int | None, date: str | None):
    """(day, holdings, {id, name, date}) of a stored snapshot, or of a date's holdings."""
    if snapshot is not None:
        s = svc.get_snapshot(conn, snapshot)
        if not s:
            raise HTTPException(status.HTTP_404_NOT_FOUND, tr("No such snapshot."))
        return svc.parse_day(s["date"]), s["holdings"], {"id": s["id"], "name": s["name"], "date": s["date"]}
    try:
        day = svc.parse_day(date)
    except svc.BadRequest as e:
        raise _bad(e) from e
    return day, what_if.holdings_on(bundle.transactions, day), {"id": None, "name": None, "date": day.isoformat()}
