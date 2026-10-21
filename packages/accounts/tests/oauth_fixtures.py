"""Disposable OAuth storage for app integration tests (no real credentials)."""

import json
import secrets
from dataclasses import replace
from datetime import timedelta

from sqlalchemy import insert

from trackerai_accounts.oauth import digest
from trackerai_accounts.service import now
from trackerai_accounts.store import oauth_clients, oauth_grants, oauth_tokens


def seed_token(accounts, account, app, scope="read"):
    accounts.config = replace(
        accounts.config,
        oauth_issuer="https://wealth.example",
        oauth_resources=json.dumps({"wealth": "https://wealth.example/api/mcp", "health": "https://health.example/api/mcp"}),
    )
    token, cid, gid = "ta_o_" + secrets.token_urlsafe(32), secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    scopes = f"{app}:read" + (f" {app}:write" if scope == "write" else "")
    with accounts.engine.begin() as c:
        c.execute(insert(oauth_clients).values(id=cid, name="Test assistant", redirects=["https://assistant.example/cb"], created_at=now()))
        c.execute(
            insert(oauth_grants).values(
                id=gid,
                client_id=cid,
                account_id=account["id"],
                app=app,
                resource=f"https://{app}.example/api/mcp",
                scope=scopes,
                session_version=account["session_version"],
                created_at=now(),
                expires_at=now() + timedelta(days=90),
            )
        )
        c.execute(
            insert(oauth_tokens).values(
                digest=digest(token),
                refresh_digest=digest(secrets.token_urlsafe(32)),
                grant_id=gid,
                scope=scopes,
                expires_at=now() + timedelta(hours=1),
            )
        )
    return token, gid
