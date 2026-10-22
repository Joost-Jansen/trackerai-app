"""
Bank rows: importing and reading back.

Two entry points, separate on purpose:

    POST /api/accounts/import        an export in
    GET  /api/bank-transactions      out, filtered

Importing hangs under /api/accounts because it creates or updates an account
there; reading back stands on its own because it also feeds the Spending
page.

The rules live in domain/money/bank_providers/ (reading),
domain/money/bank_transactions.py (storing) and services/bank_service.py
(which account); this only routes.
"""

import os
import sqlite3

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile, status

from app.core.errors import CodedError
from app.deps import CurrentUser, get_current_user, get_db, require_money
from app.services import bank_service, upload_store
from domain.i18n import tr
from domain.money import accounts, bank_transactions, categorization, shared_costs

router = APIRouter(tags=["bank_transactions"], dependencies=[Depends(require_money)])


def _safe_name(raw: str | None) -> str:
    """Same reason as in uploads.py: the browser picks this text and it is appended
    to the user's upload folder, so "../../foo" must not escape from it.
    """
    return upload_store.safe_name(raw, "export.csv")


@router.post("/api/accounts/import")
def import_file(
    file: UploadFile,
    conn: sqlite3.Connection = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """Upload a bank export. The file itself tells which bank it is from."""
    target = upload_store.receive(user.username, file, "export.csv")
    try:
        report = bank_service.import_file(conn, target)
    except bank_service.ImportRefused as e:
        # The file does not linger if we are not going to use it: prices_status dates
        # the "last import" on the newest file in that folder, so a refused upload
        # would claim an import that never happened.
        os.remove(target)
        # 422 as a plain number, like uploads.py: the name constant for it is
        # deprecated in this starlette version and the new one lives elsewhere.
        raise HTTPException(422, str(e)) from e
    upload_store.done(conn, user.username, target)
    return report


@router.post("/api/uploads/bank")
def import_several(
    files: list[UploadFile],
    conn: sqlite3.Connection = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    """One or more bank exports at once, from the Update panel.

    A report per file. A file that fails does not hold back the rest: someone
    who uploads the current account, the savings accounts and the balance
    overview together and picked one wrong file does not want to redo the
    other two.
    """
    results = []
    for upload in files:
        name = _safe_name(upload.filename)
        try:
            target = upload_store.receive(user.username, upload, "export.csv")
        except CodedError as e:
            results.append({"file": name, "error": e.detail, "code": e.code})
            continue
        try:
            results.append({"file": name, **bank_service.import_file(conn, target)})
            upload_store.done(conn, user.username, target)
        except bank_service.ImportRefused as e:
            # Same reason as above: prices_status dates the "last import" on the newest
            # file in that folder.
            os.remove(target)
            results.append({"file": name, "error": str(e)})
    return {"results": results}


@router.get("/api/bank-transactions")
def items(
    account_id: int | None = Query(None),
    start: str | None = Query(None, description="ISO date, inclusive"),
    end: str | None = Query(None, description="ISO date, inclusive"),
    shared_shares: bool = Query(False, description="Also your own share of shared costs, as derived rows"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    transactions = bank_transactions.load(conn, account_id=account_id, start=start, end=end)
    if shared_shares:
        # Only for screens that add up spending; the list of transactions itself
        # shows what really happened on the account.
        derived = [
            r
            for r in shared_costs.own_share_rows(conn)
            if (account_id is None or r["account_id"] == account_id) and (not start or r["date"] >= start) and (not end or r["date"] <= end)
        ]
        transactions = sorted(transactions + derived, key=lambda r: r["date"])
    # Outside the period filter: so an empty period can say there *are*
    # transactions, and when the latest one is from.
    date_range = bank_transactions.date_range(conn, account_id=account_id)
    return {
        "transactions": transactions,
        "count": len(transactions),
        "total": date_range["total"],
        "last_date": date_range["last"],
    }


@router.post("/api/bank-transactions", status_code=status.HTTP_201_CREATED)
def add(
    account_id: int = Body(...),
    date: str = Body(...),
    amount: float = Body(..., description="Altijd positief; de richting is apart"),
    direction: str = Body("expense", description="expense | income"),
    name: str = Body(...),
    description: str = Body(""),
    category: str | None = Body(None, description="Empty: the rules decide"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """An expense or income that is in no export.

    The amount always comes in positive and the direction separately, so nobody
    needs to know that an expense is stored as positive in the database.
    """
    if accounts.load_account(conn, account_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("Account {0} does not exist.", account_id))
    if direction not in ("expense", "income"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("Choose expense or income."))
    if amount is None or amount <= 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, tr("Enter an amount greater than zero; whether it came in or went out you choose separately.")
        )

    categorization.seed(conn)
    if category is not None and category not in {c["name"] for c in categorization.load_categories(conn)}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("'{0}' is not an existing category.", category))

    try:
        transaction_id = bank_transactions.add_manually(
            conn,
            account_id=account_id,
            date=date,
            amount=amount if direction == "expense" else -amount,
            name=name,
            description=description,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    if category:
        bank_transactions.set_category_manual(conn, transaction_id, category)
    # Also with a category of your own: this way it shows what the rules made of it.
    categorization.relabel(conn)
    return {"transaction": next(r for r in bank_transactions.load(conn) if r["id"] == transaction_id)}


@router.put("/api/bank-transactions/category")
def set_category_for_many(
    ids: list[int] = Body(..., description="The transactions that get this category"),
    category: str | None = Body(None, description="Empty: back to what the rules find"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """One category for a whole selection, by hand: it wins over the rules.

    For what no rule can catch because it happened only once — money from
    friends for a holiday you paid, for example.
    """
    categorization.seed(conn)
    if category is not None and category not in {c["name"] for c in categorization.load_categories(conn)}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("'{0}' is not an existing category.", category))
    existing = [i for i in ids if conn.execute("SELECT 1 FROM bank_transactions WHERE id = ?", (i,)).fetchone()]
    updated = bank_transactions.set_category_manual_for(conn, existing, category)
    # Without a category of your own the rules decide it again.
    categorization.relabel(conn)
    return {"updated": updated}


@router.delete("/api/bank-transactions/{transaction_id}")
def remove(
    transaction_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    try:
        away = bank_transactions.delete_manual(conn, transaction_id)
    except bank_transactions.NotManual as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("{0} An imported one comes back with the next import anyway.", e)) from e
    if not away:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("This transaction does not exist."))
    return {"ok": True}
