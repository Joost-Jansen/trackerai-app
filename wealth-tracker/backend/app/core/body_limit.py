"""
Request body limits (S1), enforced while the body streams in — before
FastAPI parses a multipart form or a JSON body, so an oversized request is
refused without being held in memory or spooled to disk whole.

Uploads (the multipart endpoints) may carry several files of at most
MAX_UPLOAD_MB each; every other request is JSON and much smaller. A declared
Content-Length over the limit is refused at once; a chunked body is counted.
"""

import json

from app.core import config
from domain import i18n

_MB = 1024 * 1024
UPLOAD_PATHS = ("/api/uploads/", "/api/accounts/import", "/api/connections/enablebanking")


class _TooLarge(Exception):
    pass


def limit_for(path: str) -> int:
    if path.startswith(UPLOAD_PATHS):
        return config.MAX_UPLOAD_REQUEST_MB * _MB + _MB  # plus room for the multipart framing
    return config.MAX_BODY_MB * _MB


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def _refuse(self, scope, send, limit: int):
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        token = i18n.set_locale(headers.get("x-locale"))
        try:
            mb = limit // _MB
            detail = i18n.tr("This upload is too large: at most {0} MB per request.", mb)
        finally:
            i18n.reset_locale(token)
        body = json.dumps({"detail": detail, "code": "upload_too_large", "params": {"max_mb": mb}}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                (b"connection", b"close")]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = limit_for(scope.get("path", ""))
        for k, v in scope.get("headers", []):
            if k.lower() == b"content-length":
                try:
                    if int(v) > limit:
                        return await self._refuse(scope, send, limit)
                except ValueError:
                    return await self._refuse(scope, send, limit)

        received = 0
        exceeded = False
        replaced = False

        async def counting_receive():
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _TooLarge()
            return message

        async def guarded_send(message):
            # FastAPI turns an error while reading the body into its own 400;
            # once the limit was crossed, whatever the app answers becomes 413.
            nonlocal replaced
            if exceeded:
                if not replaced:
                    replaced = True
                    await self._refuse(scope, send, limit)
                return
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except _TooLarge:
            if not replaced:
                replaced = True
                await self._refuse(scope, send, limit)
