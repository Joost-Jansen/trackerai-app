"""
Feedback: something broken, or an idea. Users send it from the app (stock- or
wealth-tracker), the admin reads and replies.

    POST  /api/feedback                    send (logged in through the browser); the browser adds page, screen and recent errors
    GET   /api/feedback                    your own reports, with status and reply
    GET   /api/feedback/{id}/screenshot    the screenshot (the sender or an admin)
    GET   /api/admin/feedback              everything (admins)
    PATCH /api/admin/feedback/{id}         status and reply (admins)

Every route returns an item in the shape both trackers share (feedback_store._out): the trackerai.nl admin page
reads them through /api/hub/wealth/... next to health-tracker's.

A new report goes to the admin as a push (core/notify, NTFY_TOPIC_URL): only
the kind, the app and the number, never the text. An admin's AI assistant
reads and answers the same list through MCP (routers/mcp.py).
"""

import base64
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status

from app.core import feedback_store, notify
from app.deps import CurrentUser, get_current_user, require_admin
from domain.i18n import tr

router = APIRouter(tags=["feedback"])

MAX_SCREENSHOT = 3 * 1024 * 1024
SCREENSHOT_TYPES = ("image/png", "image/jpeg", "image/webp")
PER_DAY = 20  # a script or a loop, not a person
APPS = ("stock", "money")
# The name each site goes by; the code stays "money".
SITE_NAMES = {"stock": "stock-tracker", "money": "wealth-tracker"}


def version() -> str | None:
    sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA") or os.environ.get("GIT_COMMIT")
    return sha[:7] if sha else None


def _screenshot(data_url: str | None) -> tuple[bytes | None, str | None]:
    if not data_url:
        return None, None
    head, _, body = data_url.partition(",")
    media = head.removeprefix("data:").removesuffix(";base64")
    if media not in SCREENSHOT_TYPES or not head.endswith(";base64"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, tr("A screenshot must be a PNG, JPEG or WebP."))
    try:
        raw = base64.b64decode(body, validate=True)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, tr("A screenshot must be a PNG, JPEG or WebP.")) from e
    if len(raw) > MAX_SCREENSHOT:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, tr("Screenshot larger than 3 MB."))
    return raw, media


def _context(raw: dict | None) -> dict:
    """What the browser sent along, kept small, plus the server version."""
    ctx = {k: v for k, v in (raw or {}).items() if isinstance(k, str) and len(k) <= 40}
    errors = ctx.get("errors")
    ctx["errors"] = [e for e in errors if isinstance(e, dict)][:10] if isinstance(errors, list) else []
    ctx = {k: (v[:500] if isinstance(v, str) else v) for k, v in ctx.items()}
    ctx["version"] = version()
    return ctx


@router.post("/api/feedback", status_code=status.HTTP_201_CREATED)
def send(
    kind: str = Body(...),
    message: str = Body(..., max_length=5000),
    page: str | None = Body(None, max_length=300),
    app: str | None = Body(None),
    context: dict | None = Body(None),
    screenshot: str | None = Body(None),
    user: CurrentUser = Depends(get_current_user),
):
    if user.via != "cookie":
        raise HTTPException(status.HTTP_403_FORBIDDEN, tr("You send feedback from the app."))
    if kind not in feedback_store.KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, tr("Choose broken or idea."))
    message = message.strip()
    if not message:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, tr("Write what is wrong or what you would like."))
    since = (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0).isoformat()
    if feedback_store.count_since(user.username, since) >= PER_DAY:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, tr("That is a lot of feedback for one day; try again tomorrow."))
    shot, media = _screenshot(screenshot)
    site = app if app in APPS else "stock"
    fid = feedback_store.add(user.username, site, kind, message, page, _context(context), shot, media)
    notify.push(
        f"{SITE_NAMES[site]}: " + ("iets kapot" if kind == "bug" else "new idea"),
        f"Feedback #{fid}",
        tags="bug" if kind == "bug" else "bulb",
    )
    return feedback_store.get(fid)


@router.get("/api/feedback")
def my(user: CurrentUser = Depends(get_current_user)):
    return {"feedback": feedback_store.list_(username=user.username)}


@router.get("/api/feedback/{feedback_id}/screenshot")
def screenshot(feedback_id: int, user: CurrentUser = Depends(get_current_user)):
    shot = feedback_store.screenshot(feedback_id)
    if not shot or (shot[0] != user.username and not user.is_admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("Feedback not found."))
    return Response(shot[1], media_type=shot[2], headers={"Cache-Control": "private, max-age=3600"})


@router.get("/api/admin/feedback")
def inbox(status_: str | None = Query(None, alias="status"), user: CurrentUser = Depends(require_admin)):
    return {"feedback": feedback_store.list_(status=status_)}


@router.patch("/api/admin/feedback/{feedback_id}")
def answer(
    feedback_id: int,
    status_: str | None = Body(None, alias="status"),
    reply: str | None = Body(None, max_length=5000),
    user: CurrentUser = Depends(require_admin),
):
    if status_ is not None and status_ not in feedback_store.STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, tr("Status is one of {0}.", ', '.join(feedback_store.STATUSES)))
    if not feedback_store.update(feedback_id, status=status_, reply=reply):
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("Feedback not found."))
    return feedback_store.get(feedback_id)
