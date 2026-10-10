"""
The welcome flow and Help: what you track, whether the tour is done, and
where you are. The logic lives in domain/onboarding.py; this routes.
"""

import sqlite3

from fastapi import APIRouter, Body, Depends, HTTPException, status

from domain.money import categorization
from domain import onboarding
from app.services import example_service
from app.deps import CurrentUser, get_current_user, get_db
from domain.i18n import tr

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

_FIELDS = {"choice", "bank", "done", "step"}


def _for_user(user: CurrentUser, conn: sqlite3.Connection) -> dict:
    """What you track, as this account is allowed to see it.

    Without the beta flag `money` you only track investments, whatever is
    stored: then Money disappears everywhere (Help, the tour, the start banner)
    without every screen having to know the flag itself. If the flag is turned
    on later, your own choice comes back.
    """
    off = onboarding.read(conn)
    off["money"] = "money" in user.beta_features
    if not off["money"]:
        off["choice"] = "investments"
    return off


@router.get("")
def read(conn: sqlite3.Connection = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    categorization.seed(conn)
    out = _for_user(user, conn)
    # A tour still to come walks past the pages with example data: build it now
    # so the walk doesn't wait for it.
    if not out.get("done"):
        example_service.warm_in_background()
    return out


@router.put("")
def put(
    fields: dict = Body(..., description="Only what changes: choice (investments|money|both), bank (upload|connect), done and/or step"),
    conn: sqlite3.Connection = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    unknown = set(fields) - _FIELDS
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("Unknown field: {0}.", ', '.join(sorted(unknown))))
    if fields.get("choice") in ("money", "both") and "money" not in user.beta_features:
        raise HTTPException(status.HTTP_403_FORBIDDEN, tr("Money is not turned on for this account."))
    categorization.seed(conn)
    try:
        onboarding.put(conn, **fields)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return _for_user(user, conn)
