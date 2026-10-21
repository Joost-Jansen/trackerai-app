"""
How you set up a screen, stored with your account. The rules live in
domain/preferences.py; this routes.
"""

import sqlite3

from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.deps import CurrentUser, get_current_user, get_db
from domain import preferences
from domain.i18n import tr

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


@router.get("/{key}")
def read(key: str, conn: sqlite3.Connection = Depends(get_db), _: CurrentUser = Depends(get_current_user)):
    try:
        return {"value": preferences.read(conn, key)}
    except preferences.UnknownKey as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("Unknown preference: {0}.", key)) from e


@router.put("/{key}")
def put(
    key: str,
    value: dict | None = Body(None, embed=True, description="The object; empty restores the default"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    try:
        preferences.put(conn, key, value)
    except preferences.UnknownKey as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("Unknown preference: {0}.", key)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"value": preferences.read(conn, key)}
