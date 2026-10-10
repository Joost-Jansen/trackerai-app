import contextlib
import os
import threading

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from trackerai_accounts import install as install_accounts
from trackerai_accounts.session import COOKIE as SESSION_COOKIE

from app.core import accounts as shared_accounts
from app.core import bootstrap, config, errors, price_refresh, startup
from app.core.body_limit import BodyLimitMiddleware
from trackerai_websec import log_redact
from trackerai_websec.csrf import OriginCheckMiddleware
from trackerai_websec.headers import SecurityHeadersMiddleware
from domain import db, i18n
from app.routers import (
    account, admin, agent_tokens, mcp, auth, bank_transactions, benchmarks, budget, calendar, categories, dashboard, details,
    dividend, etf_analysis, feedback, holdings, connections, labelling, month_periods, news, onboarding, rebalancing, accounts, returns,
    spending, uploads, net_worth, preferences,
)


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    """Keeps the price cache current while the process lives.

    Everything the app says about "today" is read off that cache, so how old
    it is *is* how wrong the day is. See app/core/price_refresh.py; it stays
    off unless PRICE_REFRESH is set, which docker-compose does.

    Before that: refuse insecure defaults in production (core/startup.py), and
    on an empty server, the first account (see core/bootstrap.py).
    """
    startup.check()
    # The move from SQLite files to Postgres (domain/migrate_pg.py): with WEALTH_DATABASE_URL and
    # WEALTH_MIGRATE_FROM_SQLITE=on, whoever is not in Postgres yet is copied and checked before the API answers.
    # A failure stops the start, so the deployment before this one, still on SQLite, goes on serving.
    if db.on_postgres() and os.environ.get("WEALTH_MIGRATE_FROM_SQLITE", "") == "on":
        from domain import migrate_pg

        print(f"[migrate] {migrate_pg.migrate_all()}")
    # The dry run of that move (WEALTH_MIGRATION_CHECK_URL): in the background, the API keeps serving from SQLite.
    check_url = os.environ.get("WEALTH_MIGRATION_CHECK_URL", "").strip()
    if check_url and not db.on_postgres():
        def check():
            from domain import migrate_pg

            try:
                print(f"[migrate-check] ok: {migrate_pg.check_all(check_url)}")
            except Exception as e:  # noqa: BLE001 - the result is the log line
                print(f"[migrate-check] FAILED: {e}")

        threading.Thread(target=check, name="migrate-check", daemon=True).start()
    created = bootstrap.first_account()
    if created:
        print(f"[bootstrap] first account '{created}' created; remove ADMIN_PASSWORD now")
    elif not os.path.exists(config.AUTH_CONFIG_PATH):
        print(f"[bootstrap] no accounts in {config.AUTH_CONFIG_PATH}: set ADMIN_USERNAME and ADMIN_PASSWORD, or run manage_users.py add")
    # Deleting an account (or leaving wealth-tracker) in another tracker reaches this one's data within a minute.
    stop = threading.Event()

    def sweep():
        while True:
            try:
                shared_accounts.purge()
            except Exception as e:  # noqa: BLE001 - the next sweep tries again
                print(f"[accounts] purge: {e!r}")
            if stop.wait(60):
                return

    if os.environ.get("ACCOUNTS_SWEEP", "on") != "off":
        threading.Thread(target=sweep, name="accounts-purge", daemon=True).start()
    if price_refresh.start():
        print(f"[price-refresh] every {price_refresh.INTERVAL_SECONDS}s "
              f"between {price_refresh.OPEN_HOUR:%H:%M} and {price_refresh.CLOSE_HOUR:%H:%M}")
    try:
        yield
    finally:
        stop.set()
        price_refresh.stop()


app = FastAPI(title="Stock Tracker API", lifespan=lifespan)
errors.install(app)


def _account_text(e) -> str:
    """The shared account's message in the reader's language (domain/i18n_nl.py has the Dutch)."""
    from trackerai_accounts.errors import MESSAGES

    template = MESSAGES.get(e.code)
    if not template:
        return e.detail
    text = i18n.NL.get(template, template) if i18n.current_locale() == "nl" else template
    shown = {k: ", ".join(map(str, v)) if isinstance(v, (list, tuple)) else v for k, v in e.params.items()}
    try:
        return text.format(**shown)
    except (KeyError, IndexError):
        return e.detail


# The shared account's errors in the reader's language, in the same {detail, code, params} shape.
install_accounts(app, _account_text)
# S6: a cookie-authenticated POST/PUT/PATCH/DELETE must come from this site
# (Origin, else Referer: PUBLIC_ORIGINS, the front door's or the request's own Host). Bearer
# tokens (agents) are exempt, and so is MCP, which never uses the cookie.
app.add_middleware(
    OriginCheckMiddleware,
    allowed_origins=config.PUBLIC_ORIGINS + config.FRONT_DOOR_ORIGINS,
    cookie_name=SESSION_COOKIE,
    exempt_paths=("/api/mcp",),
)
# S1: request bodies are limited while they stream in, before any parsing.
app.add_middleware(BodyLimitMiddleware)
# S5: security headers on every API response (pages get theirs from Next, proxy.ts).
app.add_middleware(SecurityHeadersMiddleware, csp=config.API_CSP, hsts=config.COOKIE_SECURE)
# Agent tokens (in /api/mcp/<token> and Bearer headers) never reach the logs.
log_redact.install()


@app.middleware("http")
async def request_locale(request: Request, call_next):
    """Messages in the reader's language: the frontend sends X-Locale (domain/i18n.py)."""
    token = i18n.set_locale(request.headers.get("x-locale"))
    try:
        return await call_next(request)
    finally:
        i18n.reset_locale(token)


# Only enabled for local dev (`next dev` on a different port than uvicorn).
# In production, Caddy puts both behind one origin and this is unnecessary.
if os.environ.get("ENABLE_DEV_CORS", "false").lower() == "true":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.DEV_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(account.router)
app.include_router(admin.router)
app.include_router(agent_tokens.router)
app.include_router(mcp.router)
app.include_router(auth.router)  # wealth-tracker's register, me and change-password, before the shared routes
# Login, logout, the password and two-step login: the shared trackerai account (packages/accounts).
app.include_router(shared_accounts.router)
app.include_router(bank_transactions.router)
app.include_router(benchmarks.router)
app.include_router(budget.router)
app.include_router(calendar.router)
app.include_router(categories.router)
app.include_router(dashboard.router)
app.include_router(details.router)
app.include_router(dividend.router)
app.include_router(etf_analysis.router)
app.include_router(feedback.router)
app.include_router(holdings.router)
app.include_router(connections.router)
app.include_router(connections.legacy_router)
app.include_router(labelling.router)
app.include_router(month_periods.router)
app.include_router(onboarding.router)
app.include_router(spending.router)
app.include_router(preferences.router)
app.include_router(news.router)
app.include_router(rebalancing.router)
app.include_router(accounts.router)
app.include_router(returns.router)
app.include_router(uploads.router)
app.include_router(net_worth.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/privacy")
def privacy():
    """Public: who runs this installation and how to reach them (PRIVACY_CONTROLLER,
    PRIVACY_CONTACT), and whether Claude labelling is offered here at all."""
    from domain.money import ai_labelling

    return {
        "controller": config.PRIVACY_CONTROLLER or None,
        "contact": config.PRIVACY_CONTACT or None,
        "ai_labelling_available": ai_labelling.available(),
    }
