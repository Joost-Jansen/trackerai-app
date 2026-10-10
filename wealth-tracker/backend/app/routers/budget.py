"""
Budget per group per month, next to what it turned out to be.

The arithmetic lives in domain/money/budget.py; this only routes.
"""

import sqlite3

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from domain.money import budget as budget_domain
from domain.money import categorization
from app.deps import CurrentUser, get_current_user, get_db, require_money

router = APIRouter(prefix="/api/budget", tags=["budget"], dependencies=[Depends(require_money)])


@router.get("")
def overview(
    months: int = Query(13, ge=1, le=120),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    categorization.seed(conn)
    return budget_domain.overview(conn, months=months)


@router.put("/{group_name}")
def put(
    group_name: str,
    amount: float | None = Body(None, embed=True, description="Per month; empty or 0 removes it"),
    months: int = Query(13, ge=1, le=120),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Sets or removes the budget of one group, and returns the new overview."""
    categorization.seed(conn)
    try:
        budget_domain.put(conn, group_name, amount)
    except budget_domain.UnknownGroup as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return budget_domain.overview(conn, months=months)
