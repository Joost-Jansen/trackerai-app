"""Routes that agents and the user both use: documents (profile, goals), log and analyses, and the agent context.

Plans live in api/plans.py."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.dashboard import build_dashboard
from api.errors import ApiError
from tools import db

TZ = ZoneInfo("Europe/Amsterdam")
DOC_KEYS = {"profile", "goals"}


class DocBody(BaseModel):
    body: str = Field(max_length=500_000)


class EntryIn(BaseModel):  # lengths as the columns (tools/db.py): Postgres would refuse longer ones with a 500
    kind: Literal["log", "analysis"]
    title: str = Field(max_length=200)
    body: str = Field(max_length=500_000)
    day: str | None = Field(None, max_length=10)


def content_router(current_user) -> APIRouter:
    """Documents, log and analyses, and the agent context, all of the caller (an api.users.User)."""
    r = APIRouter(prefix="/api")

    @r.get("/docs/{key}")
    def get_doc(key: str, u=Depends(current_user)):
        doc = db.get_document(u.scope, key) if key in DOC_KEYS else None
        if not doc:
            raise ApiError(404, "document_not_found")
        return doc

    @r.put("/docs/{key}")
    def put_doc(key: str, doc: DocBody, u=Depends(current_user)):
        if key not in DOC_KEYS:
            raise ApiError(404, "unknown_document")
        db.put_document(u.scope, key, doc.body, author=u.author)
        return db.get_document(u.scope, key)

    @r.get("/entries")
    def entries(kind: str | None = None, limit: int = 100, u=Depends(current_user)):
        return db.list_entries(u.scope, kind=kind, limit=min(limit, 500))

    @r.post("/entries")
    def add_entry(entry: EntryIn, u=Depends(current_user)):
        day = entry.day or datetime.now(TZ).date().isoformat()
        eid = db.add_entry(u.scope, kind=entry.kind, title=entry.title, body=entry.body, author=u.author, day=day)
        return {"id": eid}

    @r.get("/context")
    def context(u=Depends(current_user)):
        """Everything a coaching agent reads at the start of a session."""
        s = u.store
        profile, goals = db.get_document(u.scope, "profile"), db.get_document(u.scope, "goals")
        return {
            "user": u.public(),
            "last_sync": s.last_sync,
            "profile": profile["body"] if profile else None,
            "goals": goals["body"] if goals else None,
            "zones": s.zones,
            "active_plan": db.active_plan(u.scope),
            "dashboard": build_dashboard(s.activities, s.wellness, s.zones, datetime.now(TZ).date(), s.last_sync, s.rhr_fallback),
            "routes": s.routes,
            "recent_log": db.list_entries(u.scope, kind="log", limit=5),
            "recent_analyses": db.list_entries(u.scope, kind="analysis", limit=3),
        }

    return r
