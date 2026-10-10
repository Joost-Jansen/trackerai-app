"""
Agent tokens: let an AI assistant (MCP, see routers/mcp.py) or a script act as
this account. Managed from the browser only — deps.AGENT_BLOCKED keeps a token
from listing or minting tokens itself.
"""

from fastapi import APIRouter, Body, Depends, HTTPException, status

from app.core import auth_store
from app.deps import CurrentUser, get_current_user
from domain.i18n import tr

router = APIRouter(prefix="/api/agent-tokens", tags=["agent-tokens"])


@router.get("")
def items(user: CurrentUser = Depends(get_current_user)):
    return {"tokens": auth_store.list_agent_tokens(user.username), "scopes": list(auth_store.AGENT_SCOPES)}


@router.post("", status_code=status.HTTP_201_CREATED)
def make(
    name: str = Body("Agent"),
    scope: str = Body("read"),
    expires_days: int | None = Body(None, description="Days until the token stops working; null: no end date"),
    user: CurrentUser = Depends(get_current_user),
):
    """Creates a token. The token itself is only in this response; a hash is stored.
    Read-only unless `scope` says "write"."""
    try:
        return auth_store.create_agent_token(user.username, name, scope, expires_days)
    except auth_store.AuthError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.delete("/{token_id}")
def remove(token_id: str, user: CurrentUser = Depends(get_current_user)):
    if not auth_store.delete_agent_token(user.username, token_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("Unknown token."))
    return {"ok": True}
