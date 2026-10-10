"""Feedback from users: something that is broken, or an idea. Read and answered by the admins.

    POST  /api/feedback                    send (site login only); the browser adds page, screen and recent errors
    GET   /api/feedback                    your own, with status and the admin's reply
    GET   /api/feedback/{id}/screenshot    the screenshot (its sender or an admin)
    GET   /api/admin/feedback              everyone's (admins)
    PATCH /api/admin/feedback/{id}         status and reply (admins)

Every item has the same fields as in the other trackers (the admin hub at trackerai.nl/admin shows them side by side):
id, app ("health"), kind, message, page, context, status, reply, created_at, updated_at (ISO with zone), account_id
and username (the sender's trackerai account; null and the local name once it is gone), has_screenshot.

The admins' AI assistant reads and answers the same list through MCP (api/mcp.py: list_feedback, update_feedback).
A new report can ping the admin (FEEDBACK_NTFY_URL, an ntfy.sh topic): only the kind and a link go out, never the text.
"""

from __future__ import annotations

import base64
import logging
import os
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from trackerai_accounts import Accounts

from api.errors import ApiError
from api.users import APP
from tools import db

MAX_SCREENSHOT = 3 * 1024 * 1024
SCREENSHOT_TYPES = ("image/png", "image/jpeg", "image/webp")
PER_DAY = 20  # a typo loop or a script, not a person
log = logging.getLogger(__name__)


class FeedbackIn(BaseModel):
    kind: str
    message: str = Field(min_length=1, max_length=5000)
    page: str | None = Field(None, max_length=300)
    context: dict | None = None
    screenshot: str | None = None  # data URL: data:image/png;base64,...


class FeedbackPatch(BaseModel):
    status: str | None = None
    reply: str | None = Field(None, max_length=5000)


def version() -> str | None:
    sha = os.environ.get("RAILWAY_GIT_COMMIT_SHA") or os.environ.get("GIT_COMMIT")
    return sha[:7] if sha else None


def _screenshot(data_url: str | None) -> tuple[bytes | None, str | None]:
    if not data_url:
        return None, None
    head, _, body = data_url.partition(",")
    media = head.removeprefix("data:").removesuffix(";base64")
    if media not in SCREENSHOT_TYPES or not head.endswith(";base64"):
        raise ApiError(422, "feedback_screenshot_type")
    try:
        raw = base64.b64decode(body, validate=True)
    except ValueError as err:
        raise ApiError(422, "feedback_screenshot_type") from err
    if len(raw) > MAX_SCREENSHOT:
        raise ApiError(413, "upload_too_large", max_mb=MAX_SCREENSHOT // (1024 * 1024))
    return raw, media


def _context(raw: dict | None) -> dict:
    """What the browser sent, kept small, plus the server's own version."""
    ctx = {k: v for k, v in (raw or {}).items() if isinstance(k, str) and len(k) <= 40}
    errors = ctx.get("errors")
    ctx["errors"] = [e for e in errors if isinstance(e, dict)][:10] if isinstance(errors, list) else []
    ctx = {k: (v[:500] if isinstance(v, str) else v) for k, v in ctx.items()}
    ctx["version"] = version()
    return ctx


def site_url() -> str | None:
    if os.environ.get("PUBLIC_URL"):
        return os.environ["PUBLIC_URL"]
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    return f"https://{domain}" if domain else None


def notify(kind: str, feedback_id: int, site: str | None = None) -> None:
    """Ping the admin in the background; a failing ping never fails the report."""
    url = os.environ.get("FEEDBACK_NTFY_URL")
    if not url:
        return
    title = "health-tracker: " + ("something broken" if kind == "bug" else "new idea")
    headers = {"Title": title, "Tags": "bug" if kind == "bug" else "bulb"}
    if site:
        headers["Click"] = f"{site.rstrip('/')}/settings/feedback/"

    def send():
        try:
            req = urllib.request.Request(url, data=f"Feedback #{feedback_id}".encode(), headers=headers, method="POST")
            urllib.request.urlopen(req, timeout=10).close()
        except Exception as err:  # noqa: BLE001
            log.warning("feedback ping failed: %s", err)

    threading.Thread(target=send, daemon=True).start()


FIELDS = ("id", "app", "kind", "message", "page", "context", "status", "reply", "created_at", "updated_at", "account_id", "username", "has_screenshot")


def public(items: list[dict], accounts: Accounts) -> list[dict]:
    """tools/db.py's items (local user id and name) as the hub's: the sender's trackerai account id and username."""
    people = {int(x["local_keys"][APP]): x for x in accounts.list_accounts() if (x["local_keys"].get(APP) or "").isdigit()}
    out = []
    for f in items:
        account = people.get(f["user_id"])
        f = {**f, "app": APP, "account_id": account["id"] if account else None, "username": account["username"] if account else f.get("username")}
        out.append({k: f.get(k) for k in FIELDS})
    return out


def make_router(engine, accounts: Accounts, current_user: Callable) -> APIRouter:
    r = APIRouter()

    def one(feedback_id: int) -> dict:
        return public([db.get_feedback(engine, feedback_id)], accounts)[0]

    def person(u=Depends(current_user)):
        if u.via != "cookie":
            raise ApiError(403, "site_login_only")
        return u

    def admin(u=Depends(current_user)):
        if u.via != "cookie" or not u.is_admin:
            raise ApiError(403, "admins_only")
        return u

    @r.post("/api/feedback", status_code=201)
    def send(body: FeedbackIn, u=Depends(person)):
        if body.kind not in db.FEEDBACK_KINDS:
            raise ApiError(422, "feedback_kind")
        message = body.message.strip()
        if not message:
            raise ApiError(422, "feedback_empty")
        since = datetime.now(timezone.utc) - timedelta(days=1)
        recent = [f for f in db.list_feedback(engine, user_id=u.id, limit=PER_DAY) if datetime.fromisoformat(f["created_at"]) > since]
        if len(recent) >= PER_DAY:
            raise ApiError(429, "feedback_too_many")
        shot, media = _screenshot(body.screenshot)
        fid = db.add_feedback(engine, u.id, body.kind, message, body.page, _context(body.context), shot, media)
        notify(body.kind, fid, site_url())
        return one(fid)

    @r.get("/api/feedback")
    def mine(u=Depends(person)):
        return public(db.list_feedback(engine, user_id=u.id), accounts)

    @r.get("/api/feedback/{feedback_id}/screenshot")
    def screenshot(feedback_id: int, u=Depends(person)):
        shot = db.feedback_screenshot(engine, feedback_id)
        if not shot or (shot[0] != u.id and not u.is_admin):
            raise ApiError(404, "feedback_not_found")
        return Response(shot[1], media_type=shot[2], headers={"Cache-Control": "private, max-age=3600"})

    @r.get("/api/admin/feedback")
    def inbox(status: str | None = None, a=Depends(admin)):
        return public(db.list_feedback(engine, status=status), accounts)

    @r.patch("/api/admin/feedback/{feedback_id}")
    def answer(feedback_id: int, body: FeedbackPatch, a=Depends(admin)):
        if body.status is not None and body.status not in db.FEEDBACK_STATUSES:
            raise ApiError(422, "feedback_status", options=list(db.FEEDBACK_STATUSES))
        if not db.update_feedback(engine, feedback_id, status=body.status, reply=body.reply):
            raise ApiError(404, "feedback_not_found")
        db.add_audit(engine, a.username, "answer_feedback", f"#{feedback_id}", body.status)
        return one(feedback_id)

    return r
