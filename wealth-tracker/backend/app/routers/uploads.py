import os
import sqlite3

from domain.imports.degiro_export import read_export
from fastapi import APIRouter, Depends, HTTPException, UploadFile

from domain.imports import degiro_cash
from domain.money import categorization
from domain import database
from domain.imports import degiro_dividends as dividend_parser
from domain.portfolio import positions as portfolio
from domain.imports import degiro_transactions as transaction_parser
from app.deps import CurrentUser, get_current_user, get_db
from app.services import upload_store
from domain.i18n import tr

router = APIRouter(prefix="/api", tags=["uploads"])


def _safe_name(raw: str | None) -> str:
    return upload_store.safe_name(raw, "upload.xlsx")


def _save_upload(username: str, upload: UploadFile) -> str:
    # transaction_parser/dividend_parser take a file path (pandas.read_excel),
    # so uploads are saved to the user's own upload dir first — in chunks and
    # at most MAX_UPLOAD_MB (upload_store.receive).
    return upload_store.receive(username, upload, "upload.xlsx")


def _check_export(path: str, expected: tuple[str, ...], kind: str) -> None:
    """
    Reject a file the parser would only shrug at, naming what is wrong.

    Both parsers swallow every error and return [], so a wrong or corrupt file
    used to come back as HTTP 200 with saved: 0 — indistinguishable from
    re-uploading rows that were already imported. Only the two cases the user
    can act on are checked here; an export that genuinely holds no rows still
    passes through as 0 saved.

    Raises HTTPException(422) on failure; the sheet shows `detail` verbatim.
    """
    name = os.path.basename(path)
    # An .xlsx is a zip: look inside before pandas unpacks it (zip bombs).
    upload_store.check_spreadsheet(path)
    try:
        header = read_export(path, nrows=0)
    except Exception:
        raise HTTPException(422, tr("I can't open '{0}' as an Excel or CSV file.", name))

    columns = [str(c).strip().lower() for c in header.columns]
    if not any(c.startswith(e) for e in expected for c in columns):
        raise HTTPException(422, tr("'{0}' doesn't look like a DeGiro {1}.", name, kind))


def _accept(username: str, upload: UploadFile, expected: tuple[str, ...], kind: str) -> str:
    """Save an upload and validate it, discarding the file if it is rejected."""
    path = _save_upload(username, upload)
    try:
        _check_export(path, expected, kind)
    except HTTPException:  # CodedError included
        # A rejected file must not linger: prices_status reports the newest
        # file in the upload dir as "last import", so keeping it would
        # date the import to a file that never imported anything.
        os.remove(path)
        raise
    return path


# Both exports carry a Datum/Product/ISIN block, so the column that tells them
# apart is the discriminator: transactions count units, account statements
# describe each mutation. This also catches the two files being swapped.
_TRANSACTION_COLUMNS = ("aantal", "quantity", "number")
_DIVIDEND_COLUMNS = ("omschrijving", "description")


@router.post("/uploads/transactions")
def upload_transactions(
    files: list[UploadFile],
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    results = []
    for upload in files:
        path = _accept(user.username, upload, _TRANSACTION_COLUMNS, "transactieoverzicht")
        # Rows DeGiro booked by amount instead of by units, with no price to
        # derive the units from, are left out of `txs`. Reporting them keeps a
        # short import from passing as the whole file.
        unparsed: list[dict] = []
        txs = transaction_parser.parse_transactions(path, warnings=unparsed)
        saved, skipped = database.save_transactions(conn, txs)
        upload_store.done(conn, user.username, path)
        results.append({
            "filename": os.path.basename(path), "saved": saved, "skipped": skipped,
            "unparsed": unparsed,
        })
    return {"results": results}


@router.post("/uploads/dividends")
def upload_dividends(
    files: list[UploadFile],
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    results = []
    for upload in files:
        path = _accept(user.username, upload, _DIVIDEND_COLUMNS, "rekeningoverzicht")
        # Payments the file has no exchange rate for at all are left out of
        # `divs`. Reporting them keeps a smaller dividend total from looking
        # like the whole truth.
        unconverted: list[dict] = []
        divs = dividend_parser.parse_dividends(path, warnings=unconverted)
        saved, skipped = database.save_dividends(conn, divs) if divs else (0, 0)
        # The same overview keeps the running cash balance: money that sits at DeGiro
        # but is not invested, and so is not in the portfolio value. Without this it
        # was missing from net worth. See degiro_cash.py.
        cash = degiro_cash.import_file(conn, path)
        # Bank transfers that now have a counterpart at DeGiro are no longer income
        # or spending — also when the bank was uploaded earlier.
        categorization.seed(conn)
        categorization.relabel(conn)
        upload_store.done(conn, user.username, path)
        results.append({
            "filename": os.path.basename(path), "saved": saved, "skipped": skipped,
            "unconverted": unconverted, "cash_days": cash["days"],
        })
    return {"results": results}


@router.post("/prices/refresh")
def refresh_prices(conn: sqlite3.Connection = Depends(get_db)):
    """Re-fetch every price, and say honestly how far it got.

    `updated_count` used to be the size of the whole price cache, so a round in
    which nothing could be fetched still answered with a full count and the
    sheet went green over it. It is the number of prices actually stored now,
    and the two companions say what the round could not do: `failed` is what
    Yahoo had no answer for, `skipped` what the deadline cut off. A caller can
    tell all three states apart, which is the whole point.
    """
    from app.services import venue_price_service

    result = portfolio.refresh_all_prices(conn)
    # Tradegate for positions held there. Its own counts, apart from Yahoo's:
    # a Tradegate outage leaves those positions on their last Tradegate price
    # (or Yahoo's, once that has missed a close) and is not a failed refresh.
    venue = venue_price_service.refresh(conn)
    return {
        "updated_count": result.refreshed,
        "failed": result.failed,
        "skipped": result.skipped,
        "complete": result.complete,
        "venue_refreshed": venue["refreshed"],
        "venue_failed": venue["failed"],
    }


@router.get("/prices/status")
def prices_status(
    user: CurrentUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    prices = database.load_prices(conn)
    timestamps = [p["fetched_at"] for p in prices.values() if p.get("fetched_at")]

    # "Last import" in the update sheet: recorded when an import succeeds (the
    # file itself is not kept, see upload_store).
    last_import = upload_store.last_import(conn, user.username)

    return {
        "last_updated": max(timestamps) if timestamps else None,
        # The newest quote flatters the set it belongs to: one ISIN that
        # refreshed while seventeen others failed still makes the sheet read
        # "updated just now". The oldest is the one the totals are actually
        # only as current as, so it is what the line is built from.
        "oldest_price": min(timestamps) if timestamps else None,
        "count": len(prices),
        "last_import": last_import,
    }
