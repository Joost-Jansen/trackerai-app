"""/api/hub/{app}/<path> -> <that tracker's API>/api/<path>, for the admin page on trackerai.nl (packages/marketing,
Admin.tsx): it reaches health-tracker's and wealth-tracker's own admin routes (beta features, feedback) through here.

Moved from wealth-tracker's frontend (lib/hub-proxy.ts and app/api/hub), with the same rules:
- only the paths in ALLOWED pass, all admin or feedback ones;
- only the request headers in REQUEST_HEADERS go along (the session cookie, Origin for the tracker's CSRF check), and
  only the response headers in RESPONSE_HEADERS come back;
- each tracker checks the forwarded session cookie and admin rights itself;
- a tracker without an address answers 503 `not_configured`, one that does not answer 502 `unreachable`, so the admin
  page says so quietly and carries on.
"""

from __future__ import annotations

import re

import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

APPS = ("health", "wealth")

ALLOWED = [
    re.compile(r"^admin/tracker$"),
    re.compile(r"^admin/tracker/betas/\d+$"),
    re.compile(r"^admin/feedback$"),
    re.compile(r"^admin/feedback/\d+$"),
    re.compile(r"^feedback/\d+/screenshot$"),
]

# Forwarded to the tracker; nothing else (no host, no x-forwarded-*).
REQUEST_HEADERS = ("cookie", "content-type", "origin", "referer", "x-locale", "user-agent")
# Passed back to the browser.
RESPONSE_HEADERS = ("content-type", "cache-control")

TIMEOUT_SECONDS = 30.0
METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]


def path_allowed(path: str) -> bool:
    """True for the paths (after /api/hub/{app}/) that may be forwarded."""
    segments = path.split("/")
    if any(s in ("", ".", "..") or "\\" in s for s in segments):
        return False
    return any(p.match(path) for p in ALLOWED)


def _pick(headers, names) -> dict[str, str]:
    return {n: headers[n] for n in names if n in headers}


def _fail(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status, headers={"cache-control": "no-store"})


def make_router(trackers: dict[str, str], transport: httpx.AsyncBaseTransport | None = None) -> APIRouter:
    """`trackers`: {app: its API base without /api}. `transport`: tests answer in place of the trackers."""
    r = APIRouter()

    @r.api_route("/api/hub/{app}/{path:path}", methods=METHODS, include_in_schema=False)
    async def forward(app: str, path: str, request: Request) -> Response:
        if app not in APPS or not path_allowed(path):
            return _fail(404, "Not found")
        base = trackers.get(app)
        if not base:
            return _fail(503, "not_configured")
        method = request.method.upper()
        body = await request.body() if method not in ("GET", "HEAD") else None
        url = f"{base}/api/{path}"
        try:
            client = httpx.AsyncClient(transport=transport, timeout=TIMEOUT_SECONDS, follow_redirects=False)
            async with client:
                upstream = await client.request(method, url, params=request.query_params, content=body,
                                                headers=_pick(request.headers, REQUEST_HEADERS))
        except httpx.HTTPError:
            return _fail(502, "unreachable")
        empty = method == "HEAD" or upstream.status_code in (204, 304)
        return Response(content=None if empty else upstream.content, status_code=upstream.status_code,
                        headers=_pick(upstream.headers, RESPONSE_HEADERS))

    return r
