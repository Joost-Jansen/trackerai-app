"""
Bank connection through Enable Banking: setting up, giving consent, fetching.

The logic lives in domain/money/bank_link.py and
domain/money/bank_providers/enablebanking.py; this routes. No endpoint
returns the private key.
"""

import sqlite3
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import RedirectResponse

from app.core import config, throttle
from trackerai_websec.csrf import normalise_origin
from domain.money import bank_link
from app.deps import CurrentUser, get_current_user, get_db, require_money
from domain.money.bank_providers import enablebanking
from domain.i18n import tr

router = APIRouter(prefix="/api/connections", tags=["connections"], dependencies=[Depends(require_money)])
# The bank's return address from before the English rename (bank_link.LEGACY_BACK_PATH).
legacy_router = APIRouter(prefix="/api/koppelingen", dependencies=[Depends(require_money)])

# A .pem is a few kilobytes; anything much larger is something else.
_MAX_KEY_BYTES = 64 * 1024


def _error(e: Exception) -> HTTPException:
    if isinstance(e, bank_link.NotConfigured):
        return HTTPException(status.HTTP_409_CONFLICT, str(e))
    if isinstance(e, enablebanking.ErrorNote):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("")
def overview(conn: sqlite3.Connection = Depends(get_db), _: CurrentUser = Depends(get_current_user)):
    return bank_link.status(conn)


@router.put("/enablebanking")
def set_up(
    app_id: str = Form(...),
    key: UploadFile = ...,
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    pem = key.file.read(_MAX_KEY_BYTES + 1)
    if len(pem) > _MAX_KEY_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("This file is too large for a private key."))
    try:
        bank_link.save_key(conn, app_id, pem)
    except ValueError as e:
        raise _error(e) from e
    return bank_link.status(conn)


@router.delete("/enablebanking")
def remove(conn: sqlite3.Connection = Depends(get_db), _: CurrentUser = Depends(get_current_user)):
    bank_link.delete_everything(conn)
    return bank_link.status(conn)


@router.get("/enablebanking/banks")
def banks(
    country: str = Query("NL", min_length=2, max_length=2),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    try:
        items = bank_link.client(conn).banks(country.upper())
    except (bank_link.NotConfigured, enablebanking.ErrorNote) as e:
        raise _error(e) from e
    return {"banks": sorted(({"name": b.get("name"), "country": b.get("country"), "logo": b.get("logo")}
                              for b in items if b.get("name")), key=lambda b: b["name"].lower())}


def _own_origin(request: Request, origin: str) -> bool:
    """The bank sends the browser back to `origin`, and the callback redirects on
    to it: it must be this site (PUBLIC_ORIGINS, or the host the request came
    to), never an address of the caller's choosing."""
    wanted = normalise_origin(origin)
    if not wanted:
        return False
    if wanted in {normalise_origin(o) for o in config.PUBLIC_ORIGINS}:
        return True
    host = wanted.split("://", 1)[1]
    seen = {request.headers.get("host")}
    # Behind a trusted proxy that rewrites Host (Next's rewrite on Railway), the
    # public host is in X-Forwarded-Host; from anyone else that header is ignored.
    if throttle.peer_is_trusted(request):
        seen.add(request.headers.get("x-forwarded-host"))
    return host in {h.strip().lower() for h in seen if h}


@router.post("/enablebanking/start")
def begin(
    request: Request,
    bank: str = Body(...),
    country: str = Body("NL"),
    origin: str = Body(..., description="window.location.origin: where the bank redirects back to"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    if not _own_origin(request, origin):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, tr("Unknown address of the app."))
    try:
        return {"url": bank_link.start(conn, bank=bank, country=country, origin=origin)}
    except (bank_link.NotConfigured, enablebanking.ErrorNote, ValueError) as e:
        raise _error(e) from e


@router.get("/enablebanking/callback")
@legacy_router.get("/enablebanking/terug", include_in_schema=False)
def back(
    state: str = Query(""),
    code: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """This is where the browser comes back from the bank. Always a redirect to the
    connect page, with what happened: a bare error message in JSON is no answer
    for someone who just logged in at their bank.
    """
    origin = bank_link.by_state(conn, state) or {"app": "", "bank": ""}
    page = f"{origin['app']}/accounts/connect"
    bank = {"bank": origin["bank"]} if origin["bank"] else {}

    if error or not code:
        message = error_description or error or tr("No consent came back from the bank.")
        bank_link.failed(conn, state, message)
        return RedirectResponse(f"{page}?{urlencode({'error': message, **bank})}", status_code=303)
    try:
        bank_link.complete(conn, state=state, code=code)
        report = bank_link.fetch(conn)
    except (bank_link.UnknownConsent, bank_link.NotConfigured, enablebanking.ErrorNote) as e:
        bank_link.failed(conn, state, str(e))
        return RedirectResponse(f"{page}?{urlencode({'error': str(e), **bank})}", status_code=303)
    return RedirectResponse(
        f"{page}?{urlencode({'gelukt': 1, 'added': report['added'], 'accounts': report['accounts'], **bank})}",
        status_code=303,
    )


@router.post("/enablebanking/fetch")
def retrieve(
    only_if_older_than_hours: float | None = Query(
        None, ge=0, description="Skip consents that were fetched more recently than this"),
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    """New transactions and balances. Without a parameter always (the button); with
    the parameter only what is outdated (opening the app).
    """
    threshold = timedelta(hours=only_if_older_than_hours) if only_if_older_than_hours is not None else None
    try:
        return bank_link.fetch(conn, only_if_older_than=threshold)
    except (bank_link.NotConfigured, enablebanking.ErrorNote) as e:
        raise _error(e) from e


@router.delete("/enablebanking/consents/{consent_id}")
def pull_in(
    consent_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    if not bank_link.delete_consent(conn, consent_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("This consent does not exist."))
    return bank_link.status(conn)
