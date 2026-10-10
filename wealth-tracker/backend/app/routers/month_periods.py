"""
Where a month starts: the 1st, or the day your salary comes in.

The logic lives in domain/money/month_periods.py; this routes. The choice
applies to the whole user: Spending, Budget, Net worth and Accounts all
calculate with the same months.
"""

import sqlite3

from fastapi import APIRouter, Body, Depends, HTTPException, status

from domain.money import categorization
from domain.money import month_periods
from app.deps import CurrentUser, get_current_user, get_db, require_money
from domain.i18n import tr

router = APIRouter(prefix="/api/month-periods", tags=["month_periods"], dependencies=[Depends(require_money)])

_FIELDS = {"mode", "day", "category"}


@router.get("")
def overview(conn: sqlite3.Connection = Depends(get_db), _: CurrentUser = Depends(get_current_user)):
    categorization.seed(conn)
    return month_periods.details(conn)


@router.put("")
def put(
    fields: dict = Body(..., description="Only what changes: mode, day (empty = recognise), category"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    unknown = set(fields) - _FIELDS
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("Unknown field: {0}.", ', '.join(sorted(unknown))))
    categorization.seed(conn)
    try:
        month_periods.put(conn, **fields)
    except (ValueError, TypeError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return month_periods.details(conn)
