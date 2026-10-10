"""Security headers on every response, set by the app itself so they are there with or without a proxy in front.

    app.add_middleware(SecurityHeadersMiddleware, csp="default-src 'self'; ...", hsts=cookie_secure)

A response that already carries a Content-Security-Policy keeps it: a page with its own policy (for instance one with
the hashes of its inline scripts) wins over the app-wide default. HSTS only when the site is served over https
(`hsts=True`): over plain http browsers ignore it, and sending it from a dev server is pointless.
"""

from __future__ import annotations

PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=(), payment=()"
HSTS = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware): streaming responses and background tasks are left alone."""

    def __init__(self, app, csp: str, hsts: bool = False):
        self.app = app
        self.static = [
            (b"x-frame-options", b"DENY"),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (b"permissions-policy", PERMISSIONS_POLICY.encode()),
            (b"cross-origin-opener-policy", b"same-origin"),
        ]
        if hsts:
            self.static.append((b"strict-transport-security", HSTS.encode()))
        self.csp = csp.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def wrapped(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {k.lower() for k, _ in headers}
                for k, v in self.static:
                    if k not in present:
                        headers.append((k, v))
                if b"content-security-policy" not in present:
                    headers.append((b"content-security-policy", self.csp))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, wrapped)
