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
    if snapshot is not None:
        s = svc.get_snapshot(conn, snapshot)
        if not s:
            raise HTTPException(status.HTTP_404_NOT_FOUND, tr("No such snapshot."))
        day, holdings, meta = svc.parse_day(s["date"]), s["holdings"], {"id": s["id"], "name": s["name"], "date": s["date"]}
    else:
        try:
            day = svc.parse_day(date)
        except svc.BadRequest as e:
            raise _bad(e) from e
        holdings = what_if.holdings_on(bundle.transactions, day)
        meta = {"id": None, "name": None, "date": day.isoformat()}
    return {"snapshot": meta, **svc.compare(conn, bundle, holdings, day)}
