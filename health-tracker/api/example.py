"""Example data for the first-run walk: a shared, read-only example account with made-up data.

The walk past the pages (web/components/onboarding/Welcome.tsx) would show a new account empty pages, so while it is on a
page step the site sends `X-Example-Data: 1`. For a site login (session cookie) that header makes the data routes in
`EXAMPLE_PATHS` read from the example account instead of the caller's own data. Everything else stays the caller's own:
who you are, account, agent tokens, connections, onboarding, feedback. Admin, MCP and agent-token routes, and every
request with a Bearer agent token, ignore the header. Any write that carries the header is refused (403
`example_read_only`, see `refuse_writes`), so example mode can never change anyone's data.

The example account lives in its own SQLite database, apart from the users' database, and is opened read-only
(`mode=ro`). It is made on first use with `scripts/seed_demo.py` (fixed random seeds, so the same day always gives the
same data) around a made-up start point, and made again when the date changes so it always ends today. Nothing in it
comes from a real person.
"""

from __future__ import annotations

import os
import tempfile
import threading
from datetime import date
from pathlib import Path
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
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
    "/api/dashboard", "/api/activities", "/api/heatmap", "/api/trends", "/api/plans", "/api/docs", "/api/entries",
    "/api/context", "/api/routes", "/api/zones", "/api/wellness", "/api/settings/zones", "/api/settings/profile",
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


def read_only_engine(path: Path) -> Engine:
    """SQLite opened with mode=ro: a write fails in SQLite itself, whatever the code above it does."""
    return create_engine(f"sqlite:///file:{path}?mode=ro&uri=true", future=True)


def build(path: Path, end: date) -> None:
    """Seed the example account into a new database file at `path` (written next to it, then moved in place)."""
    from scripts.seed_demo import seed  # the demo seed, reused: same synthetic training, sleep and plan

    tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.unlink(missing_ok=True)
    engine = db.connect(f"sqlite:///{tmp}")
    try:
        seed(engine, end, days=DAYS, username=USERNAME, display_name="Example", home=HOME, login=False)
    finally:
        engine.dispose()
    os.replace(tmp, path)


class ExampleData:
    """The example account's data for today: seeded on first use, then read-only."""

    def __init__(self, directory: Path | None, today: Callable[[], date]):
        self.directory = Path(directory or os.environ.get("EXAMPLE_DATA_DIR") or Path(tempfile.gettempdir()) / "health-tracker-example")
        self.today = today
        self._lock = threading.Lock()
        self._day: date | None = None
        self._store: DataStore | None = None
        self._engine: Engine | None = None

    def warm(self) -> None:
        """Make today's example database in a background thread (at startup)."""

        def run():
            try:
                self.store()
            except Exception as e:  # noqa: BLE001 (the first example request tries again and shows the error)
                print(f"example data: {e!r}", flush=True)

        threading.Thread(target=run, name="example-data", daemon=True).start()

    def path(self, day: date) -> Path:
        return self.directory / f"example-{day.isoformat()}.db"

    def store(self) -> DataStore:
        day = self.today()
        if self._day == day and self._store:
            return self._store
        with self._lock:
            if self._day == day and self._store:
                return self._store
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.path(day)
            if not path.exists():
                build(path, day)
            engine = read_only_engine(path)
            user = db.get_user_by_name(engine, USERNAME)
            if not user:
                raise RuntimeError(f"example database without '{USERNAME}': {path}")
            old, old_day = self._engine, self._day
            self._engine, self._day = engine, day
            self._store = DataStore(db.Scope(engine, user["id"]))
            if old is not None:
                old.dispose()
            if old_day and old_day != day:
                self.path(old_day).unlink(missing_ok=True)
            return self._store
