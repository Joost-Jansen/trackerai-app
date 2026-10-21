"""OAuth for every TrackerAI MCP server. OAuthlib handles code/PKCE protocol
validation; this module supplies shared account eligibility, consent and storage.
Only hashes of codes/access/refresh tokens persist. Public clients use S256.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from oauthlib.oauth2 import InvalidGrantError, OAuth2Error, RequestValidator, WebApplicationServer
from pydantic import BaseModel
from sqlalchemy import insert, select, update

from .config import APPS, CONSENT_APPS
from .limits import Limiter
from .service import _aware, now
from .store import account_apps
from .store import accounts as people
from .store import oauth_clients as clients
from .store import oauth_codes as codes
from .store import oauth_grants as grants
from .store import oauth_requests as pending
from .store import oauth_tokens as tokens

PREFIX = "ta_o_"
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer"}


class _ProtocolLogs(logging.Filter):
    # OAuthlib's debug messages include codes, tokens and request bodies. Keep
    # them out even if the application or a developer turns on debug logging.
    def filter(self, record):
        return record.levelno >= logging.WARNING


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def safe_url(value: str, *, loopback: bool = False) -> bool:
    try:
        u = urlsplit(value)
        return bool(
            u.hostname
            and not u.username
            and not u.password
            and not u.fragment
            and not any(c in value for c in ("\\", "\r", "\n", "\t"))
            and (u.scheme == "https" or (loopback and u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1")))
        )
    except ValueError:
        return False


def params(query: str) -> dict[str, str]:
    p = parse_qs(query, keep_blank_values=True, max_num_fields=30)
    if any(len(v) != 1 for v in p.values()) or len(query) > 8192:
        raise ValueError("Duplicate or oversized parameters")
    return {k: v[0] for k, v in p.items()}


class OAuth:
    def __init__(self, accounts):
        self.accounts = accounts
        for name, logger in list(logging.Logger.manager.loggerDict.items()):
            if name.startswith("oauthlib.") and isinstance(logger, logging.Logger):
                if not any(isinstance(f, _ProtocolLogs) for f in logger.filters):
                    logger.addFilter(_ProtocolLogs())

    @property
    def enabled(self):
        cfg = self.accounts.config
        resources = cfg.resources
        return (
            safe_url(cfg.oauth_issuer)
            and not urlsplit(cfg.oauth_issuer).query
            and urlsplit(cfg.oauth_issuer).path in ("", "/")
            and bool(resources)
            and set(resources).issubset(APPS)
            and all(
                isinstance(v, str) and safe_url(v) and not urlsplit(v).query and urlsplit(v).path == "/api/mcp" for v in resources.values()
            )
            and len(set(resources.values())) == len(resources)
        )

    def app_for(self, resource):
        return next((k for k, v in self.accounts.config.resources.items() if v == resource), None)

    def challenge(self, app):
        resource = self.accounts.config.resources.get(app)
        if not self.enabled or not resource:
            return {}
        metadata = resource.split("/api/mcp")[0] + "/.well-known/oauth-protected-resource/api/mcp"
        return {"WWW-Authenticate": f'Bearer resource_metadata="{metadata}", scope="{app}:read"'}

    def eligible(self, c, grant):
        account = c.execute(select(people).where(people.c.id == grant["account_id"])).mappings().first()
        apps = {
            a["app"]: dict(a)
            for a in c.execute(
                select(account_apps).where(account_apps.c.account_id == grant["account_id"], account_apps.c.leaving_at.is_(None))
            ).mappings()
        }
        app = apps.get(grant["app"])
        if (
            not account
            or account["suspended"]
            or account["deleted_at"]
            or not app
            or (account["session_version"] or 0) != grant["session_version"]
            or grant["revoked_at"]
            or _aware(grant["expires_at"]) <= now()
            or (grant["app"] in CONSENT_APPS and not app["consent_at"])
            or self.accounts.email_verify_required(dict(account))
            or (self.accounts.totp_required(dict(account), apps) and not self.accounts.two_step(dict(account)))
        ):
            return None
        return dict(account), apps

    def resolve(self, token: str, app: str):
        if not self.enabled or not token.startswith(PREFIX) or len(token) > 200:
            return None
        with self.accounts.engine.begin() as c:
            row = c.execute(select(tokens).where(tokens.c.digest == digest(token))).mappings().first()
            if not row or row["used_at"] or _aware(row["expires_at"]) <= now():
                return None
            grant = c.execute(select(grants).where(grants.c.id == row["grant_id"])).mappings().first()
            if not grant or grant["app"] != app or grant["resource"] != self.accounts.config.resources.get(app):
                return None
            person = self.eligible(c, grant)
            if not person:
                return None
            if not grant["last_used_at"] or (now() - _aware(grant["last_used_at"])).total_seconds() >= 300:
                c.execute(update(grants).where(grants.c.id == grant["id"]).values(last_used_at=now()))
            account, apps = person
            return {
                "account": account,
                "apps": apps,
                "scope": "write" if f"{app}:write" in row["scope"].split() else "read",
                "id": grant["id"],
            }

    def server(self, c):
        return WebApplicationServer(
            Validator(self, c),
            token_expires_in=3600,
            token_generator=lambda r: PREFIX + secrets.token_urlsafe(32),
            refresh_token_generator=lambda r: "ta_r_" + secrets.token_urlsafe(32),
        )


class Validator(RequestValidator):
    def __init__(self, oauth, c):
        self.oauth, self.c = oauth, c

    def client(self, client_id):
        return self.c.execute(select(clients).where(clients.c.id == client_id)).mappings().first()

    def validate_client_id(self, client_id, request, *args, **kwargs):
        row = self.client(client_id)
        if row:
            request.client = SimpleNamespace(client_id=client_id)
        return bool(row)

    def authenticate_client_id(self, client_id, request, *args, **kwargs):
        return self.validate_client_id(client_id, request)

    def client_authentication_required(self, request, *args, **kwargs):
        return False

    def validate_redirect_uri(self, client_id, redirect_uri, request, *args, **kwargs):
        row = self.client(client_id)
        return bool(row and redirect_uri in row["redirects"])

    def get_default_redirect_uri(self, client_id, request, *args, **kwargs):
        return None  # always require an explicit, exactly registered redirect

    def validate_response_type(self, client_id, response_type, client, request, *args, **kwargs):
        return response_type == "code"

    def validate_grant_type(self, client_id, grant_type, client, request, *args, **kwargs):
        return grant_type in ("authorization_code", "refresh_token")

    def is_pkce_required(self, client_id, request):
        return True

    def get_default_scopes(self, client_id, request, *args, **kwargs):
        app = self.oauth.app_for(request.resource)
        return [f"{app}:read"] if app else []

    def validate_scopes(self, client_id, scopes, client, request, *args, **kwargs):
        app = self.oauth.app_for(request.resource)
        return bool(app and scopes and set(scopes).issubset({f"{app}:read", f"{app}:write"}))

    def save_authorization_code(self, client_id, code, request, *args, **kwargs):
        self.c.execute(
            insert(codes).values(
                digest=digest(code["code"]),
                grant_id=request.grant_id,
                redirect_uri=request.redirect_uri,
                challenge=request.code_challenge,
                expires_at=now() + timedelta(minutes=5),
            )
        )

    def validate_code(self, client_id, code, client, request, *args, **kwargs):
        row = self.c.execute(select(codes).where(codes.c.digest == digest(code)).with_for_update()).mappings().first()
        if not row or _aware(row["expires_at"]) <= now():
            return False
        grant = self.c.execute(select(grants).where(grants.c.id == row["grant_id"])).mappings().first()
        if not grant or grant["client_id"] != client_id or request.resource != grant["resource"]:
            return False
        if row["used_at"]:
            self.c.execute(update(grants).where(grants.c.id == grant["id"]).values(revoked_at=now()))
            return False
        person = self.oauth.eligible(self.c, grant)
        if not person:
            return False
        request.code_row, request.grant_id, request.user = dict(row), grant["id"], person[0]["id"]
        request.scopes = grant["scope"].split()
        return True

    def get_code_challenge(self, code, request):
        return request.code_row["challenge"]

    def get_code_challenge_method(self, code, request):
        return "S256"

    def confirm_redirect_uri(self, client_id, code, redirect_uri, client, request, *args, **kwargs):
        return request.code_row["redirect_uri"] == redirect_uri

    def invalidate_authorization_code(self, client_id, code, request, *args, **kwargs):
        pass  # consumed atomically with saving the token

    def validate_refresh_token(self, refresh_token, client, request, *args, **kwargs):
        row = self.c.execute(select(tokens).where(tokens.c.refresh_digest == digest(refresh_token)).with_for_update()).mappings().first()
        if not row:
            return False
        grant = self.c.execute(select(grants).where(grants.c.id == row["grant_id"])).mappings().first()
        if not grant or grant["client_id"] != client.client_id or request.resource != grant["resource"]:
            return False
        if row["used_at"]:
            self.c.execute(update(grants).where(grants.c.id == grant["id"]).values(revoked_at=now()))
            return False
        person = self.oauth.eligible(self.c, grant)
        if not person:
            return False
        request.token_row, request.grant_id, request.user = dict(row), grant["id"], person[0]["id"]
        return True

    def get_original_scopes(self, refresh_token, request, *args, **kwargs):
        return request.token_row["scope"].split()

    def is_within_original_scope(self, scopes, refresh_token, request, *args, **kwargs):
        return False

    def rotate_refresh_token(self, request):
        return True

    def save_bearer_token(self, token, request, *args, **kwargs):
        table, key = (codes, digest(request.code)) if request.grant_type == "authorization_code" else (tokens, request.token_row["digest"])
        consumed = self.c.execute(update(table).where(table.c.digest == key, table.c.used_at.is_(None)).values(used_at=now()))
        if consumed.rowcount != 1:
            raise InvalidGrantError()
        self.c.execute(
            insert(tokens).values(
                digest=digest(token["access_token"]),
                refresh_digest=digest(token["refresh_token"]),
                grant_id=request.grant_id,
                scope=token["scope"],
                expires_at=now() + timedelta(seconds=token["expires_in"]),
            )
        )


class Decision(BaseModel):
    request: str
    allow: bool
    write: bool = False
    health_consent: bool = False


def make_router(accounts, sessions, app: str, client_ip) -> APIRouter:
    r, oauth = APIRouter(), OAuth(accounts)
    register_limit, token_limit, authorize_limit = Limiter(10, 3600), Limiter(120, 60), Limiter(60, 60)

    def fail(error, status=400):
        return JSONResponse({"error": error}, status_code=status, headers=NO_STORE)

    def configured():
        if not oauth.enabled:
            return False
        return True

    def csrf(request):
        # Consent/revocation are cookie-authenticated. Require the actual same
        # origin, never a suffix match or a Host supplied by the OAuth client.
        origin = request.headers.get("origin")
        public = {urlsplit(v)._replace(path="", query="", fragment="").geturl() for v in accounts.config.resources.values()}
        public.add(accounts.config.oauth_issuer)
        # Next's API proxy changes Host to its internal service address. The
        # configured public origins, rather than that private Host, are trusted.
        return origin in public and request.headers.get("sec-fetch-site") != "cross-site"

    @r.get("/.well-known/oauth-authorization-server")
    def metadata():
        if not configured():
            return fail("not_found", 404)
        issuer = accounts.config.oauth_issuer
        return JSONResponse(
            {
                "issuer": issuer,
                "authorization_endpoint": issuer + "/api/oauth/authorize",
                "token_endpoint": issuer + "/api/oauth/token",
                "registration_endpoint": issuer + "/api/oauth/register",
                "revocation_endpoint": issuer + "/api/oauth/revoke",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": [f"{a}:{s}" for a in accounts.config.resources for s in ("read", "write")],
            },
            headers=NO_STORE,
        )

    @r.get("/.well-known/oauth-protected-resource")
    @r.get("/.well-known/oauth-protected-resource/api/mcp")
    def resource_metadata():
        resource = accounts.config.resources.get(app)
        if not configured() or not resource:
            return fail("not_found", 404)
        return JSONResponse(
            {
                "resource": resource,
                "authorization_servers": [accounts.config.oauth_issuer],
                "scopes_supported": [f"{app}:read", f"{app}:write"],
                "bearer_methods_supported": ["header"],
            },
            headers=NO_STORE,
        )

    @r.post("/api/oauth/register")
    async def register(request: Request):
        if not configured():
            return fail("not_found", 404)
        ip = client_ip(request)
        if register_limit.blocked(ip):
            return fail("temporarily_unavailable", 429)
        register_limit.hit(ip)
        try:
            body = await request.json()
            redirects = body["redirect_uris"]
            name = body.get("client_name", "MCP client")
            if (
                not isinstance(redirects, list)
                or not 1 <= len(redirects) <= 5
                or any(not isinstance(u, str) or len(u) > 2048 or not safe_url(u, loopback=True) for u in redirects)
                or not isinstance(name, str)
                or not 1 <= len(name.strip()) <= 100
                or body.get("token_endpoint_auth_method", "none") != "none"
                or not isinstance(body.get("grant_types", ["authorization_code", "refresh_token"]), list)
                or not set(body.get("grant_types", ["authorization_code", "refresh_token"])).issubset(
                    {"authorization_code", "refresh_token"}
                )
                or "authorization_code" not in body.get("grant_types", ["authorization_code", "refresh_token"])
                or body.get("response_types", ["code"]) != ["code"]
            ):
                return fail("invalid_client_metadata")
        except (ValueError, KeyError, TypeError, AttributeError):
            return fail("invalid_client_metadata")
        cid = "ta_client_" + secrets.token_urlsafe(24)
        with accounts.engine.begin() as c:
            c.execute(insert(clients).values(id=cid, name=name.strip(), redirects=redirects, created_at=now()))
        return JSONResponse(
            {
                "client_id": cid,
                "client_name": name.strip(),
                "redirect_uris": redirects,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
            status_code=201,
            headers=NO_STORE,
        )

    def auth_params(query):
        p = params(query)
        if (
            not p.get("redirect_uri")
            or not oauth.app_for(p.get("resource"))
            or p.get("code_challenge_method") != "S256"
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", p.get("code_challenge", ""))
            or not p.get("state")
            or len(p["state"]) > 1024
        ):
            raise ValueError("Invalid authorization request")
        return p

    @r.get("/api/oauth/authorize")
    def authorize(request: Request):
        if not configured():
            return fail("not_found", 404)
        ip = client_ip(request)
        if authorize_limit.blocked(ip):
            return fail("temporarily_unavailable", 429)
        authorize_limit.hit(ip)
        query = request.url.query
        try:
            auth_params(query)
            with accounts.engine.begin() as c:
                oauth.server(c).validate_authorization_request(accounts.config.oauth_issuer + "/api/oauth/authorize?" + query)
                nonce = secrets.token_urlsafe(32)
                c.execute(insert(pending).values(digest=digest(nonce), query=query, expires_at=now() + timedelta(minutes=10)))
        except (OAuth2Error, ValueError):
            # Never redirect an invalid/unregistered callback.
            return fail("invalid_request")
        return RedirectResponse(accounts.config.oauth_issuer + "/connect?request=" + nonce, status_code=302, headers=NO_STORE)

    def pending_request(c, nonce, who):
        row = c.execute(select(pending).where(pending.c.digest == digest(nonce)).with_for_update()).mappings().first()
        if not row or row["used_at"] or _aware(row["expires_at"]) <= now() or row["account_id"] not in (None, who.id):
            return None
        bound = c.execute(
            update(pending)
            .where(
                pending.c.digest == row["digest"],
                pending.c.used_at.is_(None),
                (pending.c.account_id.is_(None)) | (pending.c.account_id == who.id),
            )
            .values(account_id=who.id)
        )
        return dict(row) if bound.rowcount == 1 else None

    @r.get("/api/oauth/consent")
    def consent(request: str, response: Response, s=Depends(sessions.ready)):
        response.headers.update(NO_STORE)
        if not configured():
            return fail("not_found", 404)
        with accounts.engine.begin() as c:
            row = pending_request(c, request, s)
            if not row:
                return fail("invalid_request")
            p = auth_params(row["query"])
            client = c.execute(select(clients).where(clients.c.id == p["client_id"])).mappings().one()
        target = oauth.app_for(p["resource"])
        if target not in s.apps:
            return fail("not_in_app", 403)
        return {
            "client": client["name"],
            "redirect_host": urlsplit(p["redirect_uri"]).netloc,
            "app": target,
            "resource": p["resource"],
            "username": s.username,
            "write_requested": f"{target}:write" in p.get("scope", "").split(),
        }

    @r.post("/api/oauth/consent")
    def decide(body: Decision, request: Request, s=Depends(sessions.ready)):
        if not configured():
            return fail("not_found", 404)
        if not csrf(request):
            return fail("invalid_request", 403)
        with accounts.engine.begin() as c:
            row = pending_request(c, body.request, s)
            if not row:
                return fail("invalid_request")
            p = auth_params(row["query"])
            target = oauth.app_for(p["resource"])
            if body.allow:
                if target not in s.apps or (target in CONSENT_APPS and (not body.health_consent or not s.apps[target].get("consent_at"))):
                    return fail("consent_required", 403)
                write_requested = f"{target}:write" in p.get("scope", "").split()
                if body.write and not write_requested:
                    return fail("invalid_scope")
                scope = [f"{target}:read"] + ([f"{target}:write"] if body.write else [])
                gid = secrets.token_urlsafe(24)
                grant = {
                    "id": gid,
                    "account_id": s.id,
                    "client_id": p["client_id"],
                    "app": target,
                    "resource": p["resource"],
                    "scope": " ".join(scope),
                    "session_version": s.account["session_version"] or 0,
                    "created_at": now(),
                    "expires_at": now() + timedelta(days=90),
                    "revoked_at": None,
                }
                if not oauth.eligible(c, grant):
                    return fail("access_denied", 403)
                used = c.execute(
                    update(pending).where(pending.c.digest == row["digest"], pending.c.used_at.is_(None)).values(used_at=now())
                )
                if used.rowcount != 1:
                    return fail("invalid_request")
                c.execute(insert(grants).values(**grant))
                headers, _, _ = oauth.server(c).create_authorization_response(
                    accounts.config.oauth_issuer + "/api/oauth/authorize?" + row["query"],
                    scopes=scope,
                    credentials={"user": s.id, "grant_id": gid},
                )
                redirect = headers["Location"]
            else:
                used = c.execute(
                    update(pending).where(pending.c.digest == row["digest"], pending.c.used_at.is_(None)).values(used_at=now())
                )
                if used.rowcount != 1:
                    return fail("invalid_request")
                redirect = (
                    p["redirect_uri"]
                    + ("&" if "?" in p["redirect_uri"] else "?")
                    + urlencode({"error": "access_denied", "state": p["state"]})
                )
        return JSONResponse({"redirect": redirect}, headers=NO_STORE)

    @r.post("/api/oauth/token")
    async def token(request: Request):
        if not configured():
            return fail("not_found", 404)
        ip = client_ip(request)
        if token_limit.blocked(ip):
            return fail("temporarily_unavailable", 429)
        token_limit.hit(ip)
        try:
            body = (await request.body()).decode()
            p = params(body)
            if not request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
                return fail("invalid_request")
            if not oauth.app_for(p.get("resource")) or p.get("client_secret") or request.headers.get("authorization"):
                return fail("invalid_request")
            if p.get("grant_type") == "authorization_code" and not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", p.get("code_verifier", "")):
                return fail("invalid_grant")
            with accounts.engine.begin() as c:
                headers, result, status = oauth.server(c).create_token_response(
                    accounts.config.oauth_issuer + "/api/oauth/token", http_method="POST", body=body, headers={}
                )
        except (OAuth2Error, ValueError, UnicodeError):
            return fail("invalid_grant")
        return Response(result, status_code=status, media_type="application/json", headers={**headers, **NO_STORE})

    @r.post("/api/oauth/revoke")
    async def revoke_token(request: Request):
        if not configured():
            return fail("not_found", 404)
        try:
            p = params((await request.body()).decode())
            if not request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
                return fail("invalid_request")
        except (ValueError, UnicodeError):
            return fail("invalid_request")
        with accounts.engine.begin() as c:
            row = (
                c.execute(
                    select(tokens).where(
                        (tokens.c.digest == digest(p.get("token", ""))) | (tokens.c.refresh_digest == digest(p.get("token", "")))
                    )
                )
                .mappings()
                .first()
            )
            if row:
                c.execute(
                    update(grants).where(grants.c.id == row["grant_id"], grants.c.client_id == p.get("client_id")).values(revoked_at=now())
                )
        return Response(status_code=200, headers=NO_STORE)

    @r.get("/api/account/agent-connections")
    def connections(response: Response, s=Depends(sessions.ready)):
        response.headers.update(NO_STORE)
        with accounts.engine.connect() as c:
            rows = c.execute(
                select(grants, clients.c.name.label("client_name"))
                .join(clients)
                .where(grants.c.account_id == s.id, grants.c.revoked_at.is_(None))
            ).mappings()
            connected = [
                {
                    "id": g["id"],
                    "name": g["client_name"],
                    "app": g["app"],
                    "scope": "write" if f"{g['app']}:write" in g["scope"].split() else "read",
                    "created_at": g["created_at"],
                    "last_used_at": g["last_used_at"],
                }
                for g in rows
                if oauth.eligible(c, g)
            ]
        plugin = accounts.config.agent_plugin_url
        return {
            "enabled": bool(oauth.enabled and accounts.config.resources.get(app)),
            "resource": accounts.config.resources.get(app),
            "plugin_url": plugin if safe_url(plugin) and urlsplit(plugin).hostname == "chatgpt.com" else None,
            "connections": connected,
        }

    @r.delete("/api/account/agent-connections/{grant_id}")
    def disconnect(grant_id: str, request: Request, s=Depends(sessions.ready)):
        if not csrf(request):
            return fail("invalid_request", 403)
        with accounts.engine.begin() as c:
            c.execute(update(grants).where(grants.c.id == grant_id, grants.c.account_id == s.id).values(revoked_at=now()))
        return {"ok": True}

    return r
