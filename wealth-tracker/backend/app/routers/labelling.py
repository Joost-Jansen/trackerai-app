"""
To label as one queue: everything that needs a decision from you, and
processing those decisions in one go. The rules live in
domain/money/label_queue.py; this routes.
"""

import sqlite3

from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.deps import CurrentUser, get_current_user, get_db, require_money
from domain.i18n import tr
from domain.money import label_queue

router = APIRouter(prefix="/api/labelling", tags=["labelling"], dependencies=[Depends(require_money)])


@router.get("/queue")
def queue(
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    return label_queue.queue(conn)


@router.post("/decision")
def decision(
    decisions: list[dict] = Body(..., embed=True, description="Decisions from the queue"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    try:
        return label_queue.decision(conn, decisions)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e) or tr("Unknown decision.")) from e
