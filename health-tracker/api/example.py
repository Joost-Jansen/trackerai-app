"""Example data for the first-run walk: a shared, read-only example account with made-up data.

The walk past the pages (web/components/onboarding/Welcome.tsx) would show a new account empty pages, so while it is on a
page step the site sends `X-Example-Data: 1`. For a site login (session cookie) that header makes the data routes in
`EXAMPLE_PATHS` read from the example account instead of the caller's own data. Everything else stays the caller's own:
who you are, account, agent tokens, connections, onboarding, feedback. Admin, MCP and agent-token routes, and every
request with a Bearer agent token, ignore the header. Any write that carries the header is refused (403
`example_read_only`, see `refuse_writes`), so example mode can never change anyone's data.

The example account lives in a schema of its own in the app's database (`example_<yyyymmdd>`), apart from the users'
tables, and is read through an engine whose every transaction is read-only, so Postgres itself refuses a write. It is
made on first use with `scripts/seed_demo.py` (fixed random seeds, so the same day always gives the same data) around a
made-up start point, and made again when the date changes so it always ends today. Nothing in it comes from a real
person.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import make_url, text
from sqlalchemy.engine import Engine

from api.data import DataStore
from api.errors import ApiError
from tools import db

HEADER = "x-example-data"
USERNAME = "example"  # reserved: nobody can register it (api/users.py)
RESERVED_USERNAMES = frozenset({USERNAME})
EXAMPLE_USER_ID = -1  # the example account's id in a `User`: never a real user's id, so nothing cached mixes
DAYS = 120  # a few months of history
# A made-up start point for the loops, in the middle of a forest: not where any user lives, and different from the demo.
HOME = (52.0590, 5.8270)

# Data routes that read from the example account in example mode (prefixes). Everything else stays the caller's own.
EXAMPLE_PATHS = (
    "/api/dashboard",
    "/api/activities",
    "/api/heatmap",
    "/api/trends",
    "/api/plans",
    "/api/docs",
    "/api/entries",
    "/api/context",
    "/api/routes",
    "/api/zones",
    "/api/wellness",
    "/api/settings/zones",
    "/api/settings/profile",
    "/api/settings/resting-hr",
)
# Routes that ignore the header completely (no example data, no refusal).
IGNORED_PATHS = ("/api/admin", "/api/trackerai/admin", "/api/mcp", "/api/agent-tokens")
WRITES = ("POST", "PUT", "PATCH", "DELETE")


def _under(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == p or path.startswith(p + "/") for p in prefixes)


def _bearer(request: Request) -> bool:
    return request.headers.get("authorization", "").lower().startswith("bearer ")


def asked(request: Request) -> bool:
    """The request asks for example data and may get it: header set, a site login, a route that is not exempt."""
    return request.headers.get(HEADER) == "1" and not _bearer(request) and not _under(request.url.path, IGNORED_PATHS)


def serves(request: Request) -> bool:
    """Read from the example account: asked for, a read, and one of the data routes."""
    return asked(request) and request.method in ("GET", "HEAD") and _under(request.url.path, EXAMPLE_PATHS)


async def refuse_writes(request: Request, call_next):
    """HTTP middleware: example mode is read-only, every write carrying the header is refused before any route runs."""
    if request.method in WRITES and request.url.path.startswith("/api/") and asked(request):
        err = ApiError(403, "example_read_only")
        return JSONResponse({"detail": err.detail, "code": err.code, "params": err.params}, status_code=403)
    return await call_next(request)


SCHEMA_PREFIX = "example_"
BUILDING = SCHEMA_PREFIX + "build"  # the one being seeded; a lock makes sure only one process seeds at a time
_LOCK = 0x6865616C7468  # pg_advisory_lock key for seeding ("health")


def schema_for(day: date) -> str:
    return f"{SCHEMA_PREFIX}{day:%Y%m%d}"


def _engine(url: str, schema: str, read_only: bool = False) -> Engine:
    """`url`'s database with `schema` as its search path. Read-only: every transaction is, so a write fails in Postgres
    itself, whatever the code above it does."""
    options = f"-csearch_path={schema}" + (" -cdefault_transaction_read_only=on" if read_only else "")
    given = make_url(url).query.get("options")  # connect_args would replace options the URL already has
    return db.connect(url, connect_args={"options": f"{given} {options}" if given else options})


def _schemas(conn) -> set[str]:
    return {r[0] for r in conn.execute(text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'example\\_%'"))}


def build(url: str, day: date) -> str:
    """Seed the example account for `day` into its schema, unless another process already did. It is seeded under a
    temporary name and renamed into place, so a reader never sees half of it. Returns the schema."""
    from scripts.seed_demo import seed  # the demo seed, reused: same synthetic training, sleep and plan

    target = schema_for(day)
    admin = db.connect(url)
    try:
        with admin.connect() as lock:
            lock.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _LOCK})
            try:
                with admin.begin() as conn:
                    if target in _schemas(conn):
                        return target
                    conn.execute(text(f'DROP SCHEMA IF EXISTS "{BUILDING}" CASCADE'))  # left by a process that stopped
                    conn.execute(text(f'CREATE SCHEMA "{BUILDING}"'))
                engine = _engine(url, BUILDING)
                try:
                    seed(engine, day, days=DAYS, username=USERNAME, display_name="Example", home=HOME, login=False)
                finally:
                    engine.dispose()
                with admin.begin() as conn:
                    conn.execute(text(f'ALTER SCHEMA "{BUILDING}" RENAME TO "{target}"'))
            finally:
                lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK})
                lock.commit()
    finally:
        admin.dispose()
    return target


def drop_before(url: str, day: date) -> None:
    """The example schemas of days before `day`'s yesterday (yesterday's stays a little: another process may still read
    it until its first request of the new day)."""
    keep = {schema_for(day), schema_for(date.fromordinal(day.toordinal() - 1)), BUILDING}
    admin = db.connect(url)
    try:
        with admin.begin() as conn:
            for schema in sorted(_schemas(conn) - keep):
                if schema[len(SCHEMA_PREFIX) :].isdigit():
                    conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        admin.dispose()


class ExampleData:
    """The example account's data for today: seeded on first use, then read-only. `url`: the database it lives in
    (the app's own)."""

    def __init__(self, url: str, today: Callable[[], date]):
        self.url = url
        self.today = today
        self._lock = threading.Lock()
        self._day: date | None = None
        self._store: DataStore | None = None
        self._engine: Engine | None = None

    def warm(self) -> None:
        """Make today's example account in a background thread (at startup)."""

        def run():
            try:
                self.store()
            except Exception as e:  # noqa: BLE001 (the first example request tries again and shows the error)
                print(f"example data: {e!r}", flush=True)

        threading.Thread(target=run, name="example-data", daemon=True).start()

    def store(self) -> DataStore:
        day = self.today()
        if self._day == day and self._store:
            return self._store
        with self._lock:
            if self._day == day and self._store:
                return self._store
            schema = build(self.url, day)
            engine = _engine(self.url, schema, read_only=True)
            user = db.get_user_by_name(engine, USERNAME)
            if not user:
                raise RuntimeError(f"example schema without '{USERNAME}': {schema}")
            old = self._engine
            self._engine, self._day = engine, day
            self._store = DataStore(db.Scope(engine, user["id"]))
            if old is not None:
                old.dispose()
            drop_before(self.url, day)
            return self._store
