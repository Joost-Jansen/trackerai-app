"""Training dashboard API: /api/* (health-web, web/, serves the site in front of it).

    uvicorn api.main:create_app --factory --host 0.0.0.0 --port 8000

Data comes from the database (DATABASE_URL), per user. Auth: the shared trackerai session
(packages/accounts, ACCOUNTS_*) or a Bearer agent token; every route sees only the caller's data (api/users.py).
"""

from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel
from trackerai_accounts import Accounts, Config, connect as connect_accounts, crypto, install as install_accounts, make_router as accounts_router
from trackerai_accounts import open_accounts, session as account_session
from trackerai_accounts.config import front_door_origins

from api import account, agent_tokens, apple, connections, daily, errors, example, feedback, gear, mcp, nutrition, onboarding, routes_api, settings_api, tracker_admin, uploads, users, zones_api
from trackerai_websec import log_redact
from trackerai_websec.csrf import OriginCheckMiddleware
from trackerai_websec.headers import SecurityHeadersMiddleware
from trackerai_websec.uploads import BodyLimitMiddleware
from api.errors import ApiError
from api.sync_runner import SyncRunner
from api.content import content_router
from api.dashboard import build_dashboard, next_race, plan_week, sync_day, today_form_pct, today_tsb
from api.history import activity_detail, heatmap, list_activities
from api.plans import enrich, make_router as plans_router
from api.readiness import readiness
from api.trends import build_trends, hr_flags
from tools import db, secretbox

TZ = ZoneInfo("Europe/Amsterdam")
# Only JSON and files come from here (the pages from health-web, with their own policy): nothing may run or load.
API_CSP = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


MIN_KM, MAX_KM = 0.01, 1000  # a corrected distance
JSON_BODY_MAX = 6 * 1024 * 1024  # any other request: a feedback screenshot (3 MB, base64) is the largest legitimate one


class ActivityCorrection(BaseModel):
    distance_km: float | None = None


@dataclass
class Settings:
    jwt_secret: str = ""  # TRAINING_JWT_SECRET: only for the key of installs from before APP_ENCRYPTION_KEY (tools/secretbox.py)
    user: str = ""  # first admin on a fresh multi-user database (bootstrap), not needed afterwards
    password_hash: str = ""
    cookie_secure: bool = True
    session_days: int = 30  # sliding: renewed while in use (api/users.py)
    agent_token_hash: str = ""  # legacy env token, belongs to the first admin
    public_origins: tuple[str, ...] = ()  # PUBLIC_ORIGINS: extra origins allowed to post (the CSRF check)
    trusted_proxies: str = ""  # TRUSTED_PROXIES: whose CF-Connecting-IP / X-Forwarded-For is believed
    accounts: Config | None = None  # the shared accounts (ACCOUNTS_*); tests get their own on SQLite

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            jwt_secret=os.environ.get("TRAINING_JWT_SECRET", ""),
            user=os.environ.get("TRAINING_USER", ""),
            password_hash=os.environ.get("TRAINING_PASSWORD_HASH", ""),
            cookie_secure=os.environ.get("COOKIE_SECURE", "true").lower() != "false",
            agent_token_hash=os.environ.get("TRAINING_AGENT_TOKEN_HASH", ""),
            session_days=int(os.environ.get("SESSION_DAYS") or 30),
            public_origins=tuple(o.strip() for o in os.environ.get("PUBLIC_ORIGINS", "").split(",") if o.strip()),
            trusted_proxies=os.environ.get("TRUSTED_PROXIES", ""),
        )


def today():
    return datetime.now(TZ).date()


def now():
    return datetime.now(TZ)


def insecure_allowed() -> bool:
    """ALLOW_INSECURE_DEFAULTS=true: the one opt-out (local development) of the checks below."""
    return os.environ.get("ALLOW_INSECURE_DEFAULTS", "").lower() == "true"


def check_production_secrets(settings: Settings) -> None:
    """Refuse to start with secrets that would make the install unsafe, instead of running with them quietly."""
    if insecure_allowed():
        return
    problems = (settings.accounts or Config.from_env()).problems()
    if problems:
        raise RuntimeError("The shared accounts are not set up: " + "; ".join(problems) + " (packages/accounts/README.md)")
    key = secretbox.configured_key()
    if not key:
        raise RuntimeError(
            "APP_ENCRYPTION_KEY is not set. New install: python -m tools.secretbox --new-key. Existing install that ran without it: "
            "python -m tools.secretbox --print-derived-key (with the same TRAINING_JWT_SECRET) keeps stored connections readable. "
            "ALLOW_INSECURE_DEFAULTS=true skips this check (development only)."
        )
    if not secretbox.valid_key(key):
        raise RuntimeError("APP_ENCRYPTION_KEY is not a valid Fernet key (32 url-safe base64-encoded bytes)")


def test_accounts(settings: Settings) -> Accounts:
    """Accounts of their own for a test app: SQLite in a fresh folder, two-step login not required (a test that is
    about it passes its own Settings.accounts)."""
    folder = tempfile.mkdtemp(prefix="accounts-")
    cfg = Config(database_url=f"sqlite:///{folder}/accounts.db", session_secret=(settings.jwt_secret or "test").ljust(32, "x"),
                 encryption_key=secretbox.default_key() or crypto.new_key(), cookie_secure=settings.cookie_secure,
                 session_days=settings.session_days, require_totp="off")
    return Accounts(connect_accounts(cfg.database_url), cfg)


def create_app(engine=None, settings: Settings | None = None, garmin_auth=None, garmin_client=None,
               example_dir: Path | None = None, accounts: Accounts | None = None, **sync_kwargs) -> FastAPI:
    """`garmin_auth`, `garmin_client` and `sync_kwargs` replace the real Garmin login, client and FIT reader (tests).
    `example_dir` holds the example account's database (api/example.py; default EXAMPLE_DATA_DIR or the temp dir).
    `accounts`: the shared accounts (default: from ACCOUNTS_* in production, a private SQLite one in tests)."""
    settings = settings or Settings.from_env()
    production = engine is None  # engine from DATABASE_URL: the real service (tests pass their own engine)
    if production:
        check_production_secrets(settings)
        engine = db.connect(os.environ["DATABASE_URL"])
    if accounts is None:
        if settings.accounts is not None:
            accounts = Accounts(connect_accounts(settings.accounts.database_url), settings.accounts)
        else:
            accounts = open_accounts() if production else test_accounts(settings)
    migrated = db.create_schema(engine)
    if migrated:
        print(f"database: omgezet naar meerdere gebruikers, alle data naar gebruiker 1: {migrated}", flush=True)
    moved = users.bootstrap(engine, accounts, settings.user, settings.password_hash, secretbox.default_key())
    if moved:
        print(f"accounts: {moved} login(s) moved to the shared accounts", flush=True)

    stores = users.Stores(engine)
    examples = example.ExampleData(example_dir, today)
    guards = users.Guards.from_env(settings.trusted_proxies)
    account_routes, sessions = accounts_router(
        accounts, users.APP, client_ip=guards.ip, after_leave=lambda: purge(),
        aliases={"/api/login": "/api/auth/login", "/api/logout": "/api/auth/logout", "/api/register": "/api/auth/register"})
    current_user, token_user, local_user = users.make_auth(engine, stores, accounts, sessions, settings.agent_token_hash, examples, guards)
    app = FastAPI(title="health-tracker", docs_url=None, redoc_url=None, openapi_url=None)
    errors.install(app)
    install_accounts(app, errors.translate)
    log_redact.install()  # the MCP token in /api/mcp/<token> and Bearer values never reach the logs
    # Innermost first (each add wraps the previous): the security headers end up on every response, also a 403 or 413.
    app.middleware("http")(example.refuse_writes)
    # the front door (trackerai.nl, www.trackerai.nl): its admin hub posts here through /api/hub/health/...
    origins = (*settings.public_origins, *front_door_origins(accounts.config.cookie_domain))
    app.add_middleware(OriginCheckMiddleware, allowed_origins=origins, cookie_name=account_session.COOKIE, exempt_paths=("/api/mcp",))
    app.add_middleware(BodyLimitMiddleware, default=JSON_BODY_MAX, limits={
        "/api/activities/upload": uploads.MAX_BYTES + 1024,
        "/api/apple/import": apple.MAX_BYTES + 1024,
        "/api/apple/upload": apple.CHUNK_BYTES + 1024,
        "/api/nutrition/admin/nevo": nutrition.NEVO_MAX_BYTES + 1024,
        "/api/nutrition/photo": nutrition.photos.MAX_BYTES + 1024,
    })
    app.add_middleware(SecurityHeadersMiddleware, csp=API_CSP, hsts=settings.cookie_secure)
    app.state.engine, app.state.stores, app.state.examples, app.state.accounts = engine, stores, examples, accounts
    runner = SyncRunner(engine, stores, client_factory=garmin_client, **sync_kwargs)
    app.state.sync = runner
    app.state.apple = apple.AppleImports(stores, on_done=lambda: cache.clear())

    def purge() -> int:
        """Delete the data of accounts that left health-tracker or were deleted (also from another tracker)."""
        return account.purge(engine, stores, accounts, secretbox.default_key(), runner, app.state.apple)

    app.state.purge = purge
    if production and os.environ.get("SYNC_IN_WEB", "true") != "false":
        runner.start_daily()
    if production:
        examples.warm()  # seed the example account in the background, so the first walk does not wait for it

        def sweep():  # a deletion in another tracker reaches health-tracker's data within a minute
            stop = threading.Event()
            while not stop.wait(60):
                try:
                    purge()
                    nutrition.photos.purge_expired(engine)  # meal photos past the time their owner keeps them
                except Exception as e:  # noqa: BLE001 - the next sweep tries again
                    print(f"purge: {e!r}", flush=True)

        purge()
        threading.Thread(target=sweep, name="purge", daemon=True).start()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    app.include_router(account_routes)  # login, registration, password, two-step login: the shared account's
    app.include_router(users.make_router(engine, stores, accounts, sessions, current_user, local_user))

    @app.get("/api/dashboard")
    def dashboard(u=Depends(current_user)):
        s, day = u.store, today()
        out = build_dashboard(s.activities, s.wellness, s.zones, day, s.last_sync, s.rhr_fallback)
        out["readiness"] = readiness(s.wellness, day, today_tsb(out["form"]), today_form_pct(out["form"]), s.rhr_fallback)
        plan = db.active_plan(u.scope)
        sessions = []
        if plan:
            sessions = enrich(plan, s.activities, s.routes, day)["sessions"]
            out["upcoming"] = [x for x in sessions if x["date"] >= day.isoformat()][:12]  # Today shows as many as fit
            out["plan_title"] = plan["title"]
            out["plan_week"] = plan_week(sessions, s.activities, day, sync_day(s.last_sync))
            out["race"] = next_race(plan, sessions, day)
        out["nutrition"] = nutrition.dashboard_block(u, day, now().strftime("%H:%M"), sessions)
        return out

    cache: dict = {}

    def cached(u, key: tuple, fn):
        # streams-heavy results (trends, heatmap) only change after a sync or at midnight
        key = (u.id, *key, u.store.last_sync, len(u.store.activities))
        if key not in cache:
            if len(cache) > 64:
                cache.clear()
            cache[key] = fn()
        return cache[key]

    @app.get("/api/activities")
    def activities(sport: str | None = None, start: str | None = Query(None, alias="from"), end: str | None = Query(None, alias="to"), u=Depends(current_user)):
        s = u.store
        flags = cached(u, ("hrflags",), lambda: hr_flags(s.activities, s.streams))
        return list_activities(s.activities, sport, start, end, hr_flags=flags)

    @app.get("/api/activities/{activity_id}")
    def activity(activity_id: str, u=Depends(current_user)):
        s = u.store
        out = activity_detail(activity_id, s.activities, s.streams, s.zones, s.routes)
        if out is None:
            raise ApiError(404, "activity_not_found")
        links = db.gear_links(u.scope)
        out["gear"] = gear.gear_of(links, db.list_gear(u.scope), activity_id)
        out["gear_chosen"] = activity_id in (db.get_setting(u.scope, db.GEAR_NONE_KEY) or []) or any(x["source"] == "manual" for x in out["gear"])
        return out

    @app.patch("/api/activities/{activity_id}")
    def correct_activity(activity_id: str, body: ActivityCorrection, u=Depends(current_user)):
        """The real distance of an activity whose GPS got it wrong (an open-water swim); null removes the correction."""
        if body.distance_km is not None and not MIN_KM <= body.distance_km <= MAX_KM:
            raise ApiError(422, "invalid_distance", min=MIN_KM, max=MAX_KM)
        if db.set_manual_distance(u.scope, activity_id, body.distance_km) is None:
            raise ApiError(404, "activity_not_found")
        u.store.invalidate()
        return activity_detail(activity_id, u.store.activities, u.store.streams, u.store.zones, u.store.routes)

    @app.get("/api/heatmap")
    def heatmap_route(sport: str | None = "run", u=Depends(current_user)):
        return cached(u, ("heatmap", sport), lambda: heatmap(u.store.activities, u.store.streams, sport or None))

    @app.get("/api/trends")
    def trends(u=Depends(current_user)):
        day, s = today(), u.store
        plan = db.active_plan(u.scope)
        # the goal-based insights follow the active plan, so it is part of the cache key
        key = ("trends", day, plan and (plan["id"], plan.get("race"), plan.get("goal")))
        return cached(u, key, lambda: build_trends(s.activities, s.wellness, s.zones, s.streams, day, s.rhr_fallback, plan=plan, last_sync=s.last_sync))

    app.include_router(plans_router(today, current_user))
    app.include_router(content_router(current_user))
    app.include_router(routes_api.make_router(today, current_user))
    app.include_router(zones_api.make_router(today, current_user))
    app.include_router(daily.make_router(today, current_user))
    app.include_router(agent_tokens.make_router(current_user))
    app.include_router(connections.make_router(current_user, runner, runner.key, garmin_auth, today))
    app.include_router(settings_api.make_router(current_user))
    app.include_router(uploads.make_router(current_user))
    app.include_router(apple.make_router(current_user, app.state.apple))
    app.include_router(onboarding.make_router(current_user, runner, app.state.apple))
    app.include_router(account.make_router(current_user))
    app.include_router(gear.make_router(current_user, today))
    app.include_router(nutrition.make_router(current_user, today, now))
    app.include_router(feedback.make_router(engine, accounts, current_user))
    app.include_router(tracker_admin.make_router(engine, accounts, current_user, today))
    app.include_router(mcp.make_router(today, current_user, token_user, guards, accounts, runner))

    return app
