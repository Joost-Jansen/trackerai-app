"""Agent tokens made on the website (Settings), so no Railway CLI is needed. Only SHA-256 hashes are stored
(table `agent_tokens`, each token belongs to one user); the token is shown once. Creating and revoking needs the
user's login cookie; an agent cannot mint tokens.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.errors import ApiError
from tools import db

MAX_TOKENS = 20


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(scope: db.Scope, name: str) -> tuple[str, dict]:
    if len(db.list_agent_tokens(scope)) >= MAX_TOKENS:
        raise ApiError(422, "too_many_tokens", max=MAX_TOKENS)
    token = "tr_" + secrets.token_urlsafe(32)
    token_id = secrets.token_hex(4)
    db.add_agent_token(scope, token_id, name, _hash(token))
    entry = next(t for t in db.list_agent_tokens(scope) if t["id"] == token_id)
    return token, entry


class NewToken(BaseModel):
    name: str


def make_router(current_user: Callable) -> APIRouter:
    r = APIRouter(prefix="/api/agent-tokens")

    def person(u=Depends(current_user)):
        if u.via == "agent":
            raise ApiError(403, "tokens_site_only")
        return u

    @r.get("")
    def get_tokens(u=Depends(person)):
        return db.list_agent_tokens(u.scope)

    @r.post("")
    def new_token(body: NewToken, u=Depends(person)):
        name = body.name.strip()
        if not name or len(name) > 60:
            raise ApiError(422, "token_name_length", min=1, max=60)
        token, entry = create_token(u.scope, name)
        return {**entry, "token": token}

    @r.delete("/{token_id}")
    def delete_token(token_id: str, u=Depends(person)):
        if not db.delete_agent_token(u.scope, token_id):
            raise ApiError(404, "token_not_found")
        return {"ok": True}

    return r
