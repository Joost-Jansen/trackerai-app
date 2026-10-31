"""
Brokers: the accounts the portfolio is spread over, and entering their
movements by hand.

A broker account is an account of kind `broker` (see domain/portfolio/brokers.py
and broker_ledger.py). It is created here as well as on the Accounts page, so
someone without the Money beta can still add a Trade Republic account: its
trades and positions are portfolio, not money. Its cash counts in net worth.

    GET    /api/brokers                          the known brokers and their accounts
    POST   /api/brokers/accounts                 a broker account (the existing one if there is one)
    GET    /api/brokers/accounts/{id}/ledger     its movements, newest first
    POST   /api/brokers/transactions             a buy, sell, deposit, … entered by hand
    DELETE /api/brokers/transactions/{table}/{id}  remove one entered by hand

Importing a broker's export is in routers/uploads.py, beside DeGiro's.
"""

import sqlite3

from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.deps import CurrentUser, get_current_user, get_db
from app.services import account_service
from domain.i18n import tr
from domain.money import accounts, categorization
from domain.portfolio import broker_ledger, brokers

router = APIRouter(prefix="/api/brokers", tags=["brokers"])


def _account_out(conn: sqlite3.Connection, account: dict) -> dict:
    out = account_service.one(conn, account["id"]) or account
    return {**out, "broker": account["provider"], "broker_label": brokers.label(account["provider"])}


@router.get("")
def overview(conn: sqlite3.Connection = Depends(get_db), _: CurrentUser = Depends(get_current_user)):
    return {
        "brokers": [{"code": code, "label": label} for code, label in brokers.BROKERS.items()],
        "accounts": [_account_out(conn, a) for a in broker_ledger.broker_accounts(conn)],
        "kinds": list(broker_ledger.KINDS),
    }


@router.post("/accounts")
def make_account(
    broker: str = Body(...),
    name: str | None = Body(None),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """The cash account of `broker`; created when there is none yet (`created`)."""
    try:
        existing = broker_ledger.cash_account(conn, broker)
        account = existing or broker_ledger.cash_account(conn, broker, create=True, name=name)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"account": _account_out(conn, account), "created": existing is None}


@router.get("/accounts/{account_id}/ledger")
def ledger(account_id: int, conn: sqlite3.Connection = Depends(get_db), _: CurrentUser = Depends(get_current_user)):
    try:
        account = broker_ledger.broker_account(conn, account_id)
    except accounts.AccountUnknown as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"account": _account_out(conn, account), "entries": broker_ledger.ledger(conn, account_id)}


@router.post("/transactions", status_code=status.HTTP_201_CREATED)
def add_transaction(
    kind: str = Body(..., description="buy, sell, deposit, withdrawal, interest, dividend, fee or tax"),
    date: str = Body(..., description="ISO date"),
    account_id: int | None = Body(None),
    broker: str | None = Body(None, description="Instead of account_id: the broker's existing account"),
    isin: str | None = Body(None),
    name: str | None = Body(None),
    quantity: float | None = Body(None, description="Units; fractions are fine"),
    price: float | None = Body(None, description="Per unit, in euros"),
    amount: float | None = Body(None, description="Euros, positive; for a buy/sell instead of the price"),
    fee: float | None = Body(None, description="Euros, positive"),
    tax: float | None = Body(None, description="Euros, positive"),
    description: str | None = Body(None),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """One movement on a broker account, entered by hand.

    The account must exist: an agent may record a transaction but not create an
    account (deps.AGENT_WRITES), so a missing one is a 404 that says so.
    """
    if account_id is None:
        if not broker:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("Give the account or the broker."))
        try:
            account = broker_ledger.cash_account(conn, broker)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
        if account is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, tr("There is no {0} account yet. Add it first.", brokers.label(broker)))
        account_id = account["id"]
    try:
        stored = broker_ledger.add_manual(
            conn,
            account_id,
            kind=kind,
            date=date,
            isin=isin,
            name=name,
            quantity=quantity,
            price=price,
            amount=amount,
            fee=fee,
            tax=tax,
            description=description,
        )
    except accounts.AccountUnknown as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    if kind in ("deposit", "withdrawal"):
        # A transfer from the bank now has its other half: it is investing, not spending.
        categorization.seed(conn)
        categorization.relabel(conn)
    return {"stored": stored, "account": _account_out(conn, accounts.load_account(conn, account_id))}


@router.delete("/transactions/{table}/{row_id}")
def delete_transaction(
    table: str,
    row_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """Removes a movement entered by hand. Imported ones come back with the next import, so they can't."""
    if not broker_ledger.delete_manual(conn, table, row_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("There is no transaction entered by hand with that id."))
    return {"ok": True}
