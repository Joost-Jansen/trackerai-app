"""
Spending insights that take more than adding up.

The arithmetic lives in domain/money/fixed_costs.py; this routes.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from domain import preferences
from domain.i18n import tr
from domain.money import fixed_costs, shared_costs
from app.deps import CurrentUser, get_current_user, get_db, require_money

router = APIRouter(prefix="/api/spending", tags=["spending"], dependencies=[Depends(require_money)])


@router.get("/fixed-costs")
def fixed(
    account_id: list[int] | None = Query(None, description="Only these accounts; empty means all"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Debits that come back every month, with what is new and what has stopped."""
    charges = fixed_costs.find(conn, account_ids=set(account_id) if account_id else None)
    running = [v for v in charges if not v["stopped"]]
    return {"fixed_costs": charges, "per_month": round(sum(v["amount"] for v in running), 2)}


@router.get("/fixed-costs/manage")
def fixed_admin(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Fixed costs, suggestions and what you turned off — for the screen where you choose."""
    return fixed_costs.admin(conn)


class Choice(BaseModel):
    name: str
    is_fixed: bool | None   # None: leave it to the detection again


@router.put("/fixed-costs/choice")
def fixed_choice(
    body: Choice,
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Whether a counterparty is a fixed cost; wins over the detection."""
    try:
        fixed_costs.set_choice(conn, body.name, body.is_fixed)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return fixed_costs.admin(conn)


class SharedCosts(BaseModel):
    category: str | None   # None: your share counts nowhere


@router.get("/shared-costs")
def shared_costs_setting(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Where your own share of shared costs ("Niet meetellen") counts as spending."""
    return {"category": shared_costs.category(conn), "default": shared_costs.DEFAULT_CATEGORY}


@router.put("/shared-costs")
def set_shared_costs(
    body: SharedCosts,
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    if body.category is not None:
        row = conn.execute("SELECT 1 FROM categories WHERE name = ? AND type = 'EXPENSE'", (body.category,)).fetchone()
        if not row:
            raise HTTPException(400, tr("Choose a spending category."))
    preferences.put(conn, shared_costs.PREFERENCE, {"category": body.category})
    return {"category": shared_costs.category(conn), "default": shared_costs.DEFAULT_CATEGORY}
