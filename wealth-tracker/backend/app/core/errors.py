"""Errors with a stable code next to the message.

The app's error shape stays `{"detail": "<message in the reader's language>"}`;
a coded error adds `"code"` (a fixed string the frontend and scripts can test
on, e.g. "too_many_attempts", "password_too_short") and `"params"`. The codes
are shared with health-tracker.
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


class CodedError(HTTPException):
    def __init__(self, status_code: int, code: str, detail: str, params: dict | None = None, headers: dict | None = None):
        super().__init__(status_code, detail, headers=headers)
        self.code = code
        self.params = params or {}


def http_error(status_code: int, exc: Exception) -> HTTPException:
    """An HTTP error for a domain exception: coded when it carries a `code`."""
    code = getattr(exc, "code", None)
    if code:
        return CodedError(status_code, code, str(exc))
    return HTTPException(status_code, str(exc))


async def _handle(_: Request, exc: CodedError) -> JSONResponse:
    return JSONResponse(
        {"detail": exc.detail, "code": exc.code, "params": exc.params},
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


def install(app: FastAPI) -> None:
    app.add_exception_handler(CodedError, _handle)
