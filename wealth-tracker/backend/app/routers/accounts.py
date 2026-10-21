"""
The Accounts page: all money that is not a security.

A current account, a savings account, cash in a drawer. The portfolio knows
what your holdings are worth; this is where the rest of your net worth comes
in, so the net worth curve can cover both.

The rules live in domain/money/accounts.py, the merging in
services/account_service.py; this only routes — and translates the errors of
the domain layer into codes the frontend can act on:

    ValueError            -> 400  a value is not valid
    AccountExistsAlready  -> 409  this IBAN is already there
    AccountUnknown        -> 404  this id does not exist (in your database)

The last one is also the scoping: every user has their own database, so
someone else's id is simply unknown here and not a 403 — it does not exist,
and that is exactly what we want to say.
"""

import sqlite3

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status

from app.deps import CurrentUser, get_current_user, get_db, require_money
from app.services import account_service
from domain.i18n import tr
from domain.money import accounts, debt_schedule

router = APIRouter(prefix="/api/accounts", tags=["accounts"], dependencies=[Depends(require_money)])


def _exists_or_404(conn: sqlite3.Connection, account_id: int) -> dict:
    account = accounts.load_account(conn, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("Account {0} does not exist.", account_id))
    return account


@router.get("")
def items(
    only_active: bool = Query(False),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """All accounts with their last known balance."""
    return {"accounts": account_service.overview(conn, only_active=only_active)}


@router.get("/total")
def total(
    date: str | None = Query(None, description="ISO date; default today"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """All active accounts together on one day.

    Accounts without a measurement on or before that day do not count: unknown
    is not zero. See accounts.total_balance_on.
    """
    date = date or account_service.today()
    try:
        return {"date": date, "total": accounts.total_balance_on(conn, date)}
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.post("", status_code=status.HTTP_201_CREATED)
def make(
    kind: str = Body(...),
    provider: str = Body(...),
    name: str = Body(...),
    iban: str | None = Body(None),
    currency: str = Body("EUR"),
    external_id: str | None = Body(None),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    try:
        account_id = accounts.make_bank_account(
            conn,
            kind=kind,
            provider=provider,
            name=name,
            iban=iban,
            currency=currency,
            external_id=external_id,
        )
    except accounts.AccountExistsAlready as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"account": account_service.one(conn, account_id)}


@router.patch("/{account_id}")
def update(
    account_id: int,
    fields: dict = Body(...),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    _exists_or_404(conn, account_id)
    try:
        accounts.update_account(conn, account_id, **fields)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"account": account_service.one(conn, account_id)}


@router.delete("/{account_id}")
def remove(
    account_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    _exists_or_404(conn, account_id)
    accounts.delete_account(conn, account_id)
    return {"ok": True}


@router.get("/{account_id}/balances")
def balances(
    account_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """All measurements of one account, ascending by date.

    `calculated`: for a debt with interest and repayment, the months the schedule
    calculated, with each month's interest and repayment. These cannot be
    deleted; a measurement of your own replaces them from that day.
    """
    _exists_or_404(conn, account_id)
    measurements = accounts.load_balances(conn, account_id)
    calculated = [p for p in debt_schedule.points(conn, account_id, measurements) if p["source"] == "schedule"]
    return {"balances": measurements, "calculated": calculated}


@router.put("/{account_id}/schedule")
def set_schedule(
    account_id: int,
    interest: float | None = Body(None, description="Percent per year"),
    repayment: float | None = Body(None, description="Required repayment per month"),
    from_date: str | None = Body(None, description="ISO date; default today"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Interest and required repayment of a debt; without both it is removed."""
    account = _exists_or_404(conn, account_id)
    if account["kind"] != "debt":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("Interest and repayment belong to a debt."))
    try:
        debt_schedule.put(conn, account_id, interest=interest, repayment=repayment, from_date=from_date or account_service.today())
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"account": account_service.one(conn, account_id)}


@router.put("/{account_id}/balance")
def set_balance(
    account_id: int,
    date: str = Body(...),
    balance: float = Body(...),
    source: str = Body("manual"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Records the balance on a day; the same day again is a correction."""
    _exists_or_404(conn, account_id)
    try:
        accounts.set_balance(conn, account_id, date, balance, source=source)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"account": account_service.one(conn, account_id)}


@router.delete("/{account_id}/balance/{date}")
def delete_balance(
    account_id: int,
    date: str,
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Removes one measurement. Correcting is a new measurement on the same date."""
    _exists_or_404(conn, account_id)
    try:
        away = accounts.delete_balance(conn, account_id, date)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    if not away:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("There is no measurement on {0}.", date))
    return {"account": account_service.one(conn, account_id)}


@router.post("/{account_id}/balance/{date}/move")
def move_balance(
    account_id: int,
    date: str,
    dest: str = Body(..., embed=True),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Moves a measurement to another day; if there already is one, that one stays."""
    _exists_or_404(conn, account_id)
    try:
        completed = accounts.move_balance(conn, account_id, date, dest)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    if not completed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("There is no measurement on {0}.", date))
    return {"account": account_service.one(conn, account_id)}
