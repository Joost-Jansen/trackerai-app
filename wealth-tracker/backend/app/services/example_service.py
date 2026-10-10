"""The example account the first-run tour shows on its walk past the pages.

A brand-new account has nothing to show, so while the walk is on a page the
web client asks for example data (header `X-Example-Data: 1`, see deps.get_db)
and reads this shared account instead: a made-up portfolio, bank accounts,
spending and net worth from scripts/seed_demo.py. Nothing in it comes from a
person; the funds and shares are real, public listings.

The account `_example` exists only as data: it is not in auth_config.yaml, so
nobody can log in as it, and the name is reserved so nobody can register it.
Requests in example mode can only read (deps.get_db refuses every write).

It is rebuilt when older than a week, so its dates stay current. A rebuild
goes into a side folder that is swapped in at the end: a request never reads a
half-built database.
"""

import datetime
import importlib.util
import os
import shutil
import threading

from domain import database, db

USER = "_example"
MAX_AGE_DAYS = 7
_lock = threading.Lock()


def _seed_module():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    spec = importlib.util.spec_from_file_location("seed_demo", os.path.join(root, "scripts", "seed_demo.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _marker(user: str = USER) -> str:
    return os.path.join(database.user_data_dir(user), "seeded_on")


def fresh(today: datetime.date | None = None) -> bool:
    """Is there an example database, built in the last week?"""
    today = today or datetime.date.today()
    try:
        with open(_marker(), encoding="utf-8") as f:
            built = datetime.date.fromisoformat(f.read().strip())
    except (OSError, ValueError):
        return False
    return (today - built).days < MAX_AGE_DAYS and database.has_data(USER)


def ensure(today: datetime.date | None = None) -> None:
    """Build the example account if it is missing or older than a week."""
    if fresh(today):
        return
    with _lock:
        if not fresh(today):
            build(today)


def warm_in_background() -> None:
    """Start building now, so the tour's walk does not wait for it later."""
    if os.environ.get("EXAMPLE_WARM", "on") != "off" and not fresh():
        threading.Thread(target=_quiet_ensure, daemon=True).start()


def _quiet_ensure() -> None:
    try:
        ensure()
    except Exception as e:  # a failed warm-up is retried on first use
        print(f"[example] building the example account failed: {e}")


def build(today: datetime.date | None = None) -> None:
    today = today or datetime.date.today()
    seed = _seed_module()
    # With EXAMPLE_OFFLINE set (tests, a host without internet) the prices are a
    # made-up course instead of Yahoo's closes.
    offline = bool(os.environ.get("EXAMPLE_OFFLINE"))
    staging = f"{USER}-next"
    staging_dir = database.user_data_dir(staging)
    database.delete_user_data(staging)  # the folder, and with WEALTH_DATABASE_URL the schema
    conn = database.connect(staging)
    try:
        database.init_db(conn)
        start = datetime.date(today.year - 3, today.month, 1)
        seed.fill_portfolio(conn, start, today, offline)
        seed.fill_money(conn, today)
    finally:
        conn.close()
    with open(_marker(staging), "w", encoding="utf-8") as f:
        f.write(today.isoformat())
    final_dir = database.user_data_dir(USER)
    old_dir = f"{final_dir}-old"
    shutil.rmtree(old_dir, ignore_errors=True)
    if os.path.isdir(final_dir):
        os.replace(final_dir, old_dir)
    os.replace(staging_dir, final_dir)
    shutil.rmtree(old_dir, ignore_errors=True)
    if db.on_postgres():
        db.swap_schema(staging, USER)
