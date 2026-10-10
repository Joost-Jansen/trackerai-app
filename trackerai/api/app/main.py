"""trackerai-api: the API behind trackerai.nl (trackerai-web).

    GET  /api/health                  the healthcheck
    the shared account routes         /api/auth/*, /api/account/*, /api/admin/* and /api/trackerai/admin/*
                                      (packages/accounts, without a default app: sign-up names the trackers)
    /api/hub/{app}/<path>             each tracker's own admin API, for the admin page (app/hub.py)

It has no data of its own: the accounts live in the accounts database every tracker shares (ACCOUNTS_DATABASE_URL),
and the session cookie on SESSION_COOKIE_DOMAIN, so a login here opens every tracker.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from trackerai_accounts import Accounts, Config, connect, install, make_router
from trackerai_accounts.config import front_door_origins
from trackerai_accounts.routes import Guards
from trackerai_accounts.session import COOKIE as SESSION_COOKIE
from trackerai_websec import client_ip, log_redact
from trackerai_websec.csrf import OriginCheckMiddleware
from trackerai_websec.headers import SecurityHeadersMiddleware

from app import hub
from app.config import API_CSP, Settings


def create_app(accounts: Accounts | None = None, settings: Settings | None = None,
               hub_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """`accounts`, `settings` and `hub_transport` replace the environment and the trackers in tests."""
    settings = settings or Settings.from_env()
    if accounts is None:
        config = Config.from_env()
        problems = config.problems()
        if problems:
            raise RuntimeError("The shared accounts are not set up: " + "; ".join(problems)
                               + " (packages/accounts/README.md)")
        accounts = Accounts(connect(config.database_url), config)

    app = FastAPI(title="trackerai API", docs_url=None, redoc_url=None, openapi_url=None)
    install(app)
    trusted = client_ip.trusted_networks(settings.trusted_proxies)
    router, _ = make_router(accounts, None, client_ip=lambda request: client_ip.client_ip(request, trusted),
                            guards=Guards())
    app.include_router(router)
    app.include_router(hub.make_router(settings.trackers, hub_transport))

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # A cookie-authenticated write must come from the front door itself (Origin, else Referer): PUBLIC_ORIGINS, or
    # the session cookie's own domain, bare and www.
    app.add_middleware(OriginCheckMiddleware,
                       allowed_origins=settings.public_origins + front_door_origins(accounts.config.cookie_domain),
                       cookie_name=SESSION_COOKIE)
    app.add_middleware(SecurityHeadersMiddleware, csp=API_CSP, hsts=settings.cookie_secure)
    log_redact.install()
    return app
