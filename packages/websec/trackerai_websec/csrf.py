"""CSRF defence by origin: a state-changing request (POST, PUT, PATCH, DELETE) that rides on the session cookie must
come from the site itself.

SameSite=Lax cookies already keep most cross-site posts out; this check closes what Lax leaves open (a sibling
subdomain counts as same-site, old browsers) at no cost. A cookie-authenticated write must name an allowed origin in
`Origin` (or, when a browser left that out, in `Referer`):

  * allowed: an origin in `allowed_origins` (scheme://host[:port]: PUBLIC_ORIGINS and the front door's), or one whose
    host[:port] equals the request's own `Host` header (which a cross-site page cannot choose);
  * refused (403, code `csrf_origin`): any other origin, "null", or neither header at all.

Not checked: requests that authenticate with `Authorization: Bearer` (scripts, MCP clients: a browser cannot attach
that header cross-site without a CORS preflight), requests without the session cookie (nothing to forge), and
`exempt_paths` (path prefixes).
"""

from __future__ import annotations

import json
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_DEFAULT_PORTS = {"http": 80, "https": 443}
BODY = json.dumps({"detail": "This request did not come from this site and was refused.", "code": "csrf_origin", "params": {}}).encode()


def normalise_origin(value: str | None) -> str | None:
    """scheme://host[:port] in lower case, default port dropped; None if unusable ("null", garbage)."""
    if not value:
        return None
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
        return None
    host = parts.hostname.lower()
    if ":" in host:  # IPv6
        host = f"[{host}]"
    if port and port != _DEFAULT_PORTS[parts.scheme]:
        host = f"{host}:{port}"
    return f"{parts.scheme}://{host}"


def _without_default_port(netloc: str) -> str:
    for default in (":80", ":443"):
        if netloc.endswith(default):
            return netloc[: -len(default)]
    return netloc


class OriginCheckMiddleware:
    """Pure ASGI: refuses a cookie-authenticated write from another origin before any route runs."""

    def __init__(self, app, allowed_origins=(), cookie_name: str = "", exempt_paths=()):
        self.app = app
        self.allowed = {o for o in (normalise_origin(x) for x in (allowed_origins or ())) if o}
        self.cookie_name = cookie_name
        self.exempt_paths = tuple(exempt_paths or ())

    def _has_session_cookie(self, headers: dict) -> bool:
        raw = headers.get("cookie")
        if not raw or not self.cookie_name:
            return False
        try:
            jar = SimpleCookie()
            jar.load(raw)
        except Exception:  # noqa: BLE001 - a malformed header: look for the name as text
            return f"{self.cookie_name}=" in raw
        return self.cookie_name in jar and bool(jar[self.cookie_name].value)

    def allowed_request(self, method: str, path: str, headers: dict) -> bool:
        if method.upper() not in UNSAFE_METHODS:
            return True
        if any(path == p or path.startswith(p.rstrip("/") + "/") for p in self.exempt_paths):
            return True
        if (headers.get("authorization") or "").lower().startswith("bearer "):
            return True
        if not self._has_session_cookie(headers):
            return True
        origin = normalise_origin(headers.get("origin") or headers.get("referer"))
        if origin is None:
            return False
        if origin in self.allowed:
            return True
        own = _without_default_port((headers.get("host") or "").strip().lower())
        return bool(own) and _without_default_port(origin.split("://", 1)[1]) == own

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        if self.allowed_request(scope.get("method", "GET"), scope.get("path", ""), headers):
            return await self.app(scope, receive, send)
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(BODY)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": BODY})
