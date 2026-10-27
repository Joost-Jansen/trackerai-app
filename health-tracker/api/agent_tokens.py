"""Agent tokens made on the website (Settings), so no Railway CLI is needed. Only SHA-256 hashes are stored
(table `agent_tokens`, each token belongs to one user); the token is shown once. Creating and revoking needs the
user's login cookie; an agent cannot mint tokens.

The same as wealth's tokens, so the shared Agents page (packages/ui) serves both: read-only unless you choose
write, with an end date unless you choose none; GET answers {"tokens": [...], "scopes": [...]}.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.errors import ApiError
from tools import db

MAX_TOKENS = 20
SCOPES = ("read", "write")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(scope: db.Scope, name: str, access: str = "read", expires_days: int | None = None) -> tuple[str, dict]:
    if len(db.list_agent_tokens(scope)) >= MAX_TOKENS:
        raise ApiError(422, "too_many_tokens", max=MAX_TOKENS)
    token = "tr_" + secrets.token_urlsafe(32)
    token_id = secrets.token_hex(4)
    expires_at = datetime.now(UTC) + timedelta(days=expires_days) if expires_days else None
    db.add_agent_token(scope, token_id, name, _hash(token), access, expires_at)
    entry = next(t for t in db.list_agent_tokens(scope) if t["id"] == token_id)
    return token, entry


class NewToken(BaseModel):
    name: str
    scope: str = "read"
    # Days until the token stops working; null: no end date.
    expires_days: int | None = None


def make_router(current_user: Callable) -> APIRouter:
    r = APIRouter(prefix="/api/agent-tokens")

    def person(u=Depends(current_user)):
        if u.via == "agent":
            raise ApiError(403, "tokens_site_only")
        return u

    @r.get("")
    def get_tokens(u=Depends(person)):
        return {"tokens": db.list_agent_tokens(u.scope), "scopes": list(SCOPES)}

    @r.post("")
    def new_token(body: NewToken, u=Depends(person)):
        name = body.name.strip()
        if not name or len(name) > 60:
            raise ApiError(422, "token_name_length", min=1, max=60)
        if body.scope not in SCOPES or (body.expires_days is not None and not 1 <= body.expires_days <= 3650):
            raise ApiError(422, "invalid_token_settings")
        token, entry = create_token(u.scope, name, body.scope, body.expires_days)
        return {**entry, "token": token}

    @r.delete("/{token_id}")
    def delete_token(token_id: str, u=Depends(person)):
        if not db.delete_agent_token(u.scope, token_id):
            raise ApiError(404, "token_not_found")
        return {"ok": True}

    return r
