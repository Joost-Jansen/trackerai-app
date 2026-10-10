# trackerai-websec

The web security building blocks of every trackerai backend. Standard library plus Starlette (which FastAPI brings);
nothing here imports an app, the app wires it up. Password rules and two-step login belong to the shared account
([packages/accounts](../accounts)).

| Module | What |
|---|---|
| `client_ip` | The real client address behind a reverse proxy: `CF-Connecting-IP` and `X-Forwarded-For` are only believed from `TRUSTED_PROXIES`. |
| `throttle` | `Limiter`: an in-memory sliding-window rate limiter (`hit`, `blocked`, `remaining_s` for Retry-After, `reset`). |
| `headers` | `SecurityHeadersMiddleware`: CSP, nosniff, frame and referrer policy, HSTS over https. A route's own header wins. |
| `csrf` | `OriginCheckMiddleware`: a cookie-authenticated write must name this site (or an allowed origin) in `Origin` or `Referer`; 403 `csrf_origin` otherwise. Bearer requests and requests without the session cookie are not checked. |
| `log_redact` | `install()`: MCP tokens in URLs and `Bearer` values never reach uvicorn's logs. |
| `uploads` | `stream_to_file`, `read_limited`, `save_upload` with a byte limit; `check_zip` against zip bombs and unsafe names (`verify=True` also streams every member); `BodyLimitMiddleware` (413 per path). |

```python
from trackerai_websec import log_redact
from trackerai_websec.csrf import OriginCheckMiddleware
from trackerai_websec.headers import SecurityHeadersMiddleware

app.add_middleware(OriginCheckMiddleware, allowed_origins=public_origins, cookie_name=COOKIE, exempt_paths=("/api/mcp",))
app.add_middleware(SecurityHeadersMiddleware, csp="default-src 'none'; frame-ancestors 'none'", hsts=cookie_secure)
log_redact.install()
```

Both images install it from the repo root (`pip install packages/websec`); locally `pip install -e packages/websec`.
Tests: `python -m pytest -q packages/websec/tests`.
