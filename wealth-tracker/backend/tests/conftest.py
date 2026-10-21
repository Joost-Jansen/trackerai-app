import os
import sys

import pytest
import yaml
from fastapi.testclient import TestClient

# Make the `app` package importable when pytest is run from the repo root
# (e.g. `pytest backend/tests`) as well as from backend/ itself.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

os.environ.setdefault("COOKIE_SECURE", "false")  # TestClient uses plain http
# Tests run without APP_ENCRYPTION_KEY: the key file in the throwaway data dir.
os.environ.setdefault("ALLOW_INSECURE_DEFAULTS", "true")
# The tour's example account: no background warm-up during tests, and made-up
# prices instead of Yahoo when a test builds it.
os.environ.setdefault("EXAMPLE_WARM", "off")
os.environ.setdefault("EXAMPLE_OFFLINE", "1")
# The shared accounts: each test gets its own (the `_accounts` fixture); no background sweep.
os.environ.setdefault("ACCOUNTS_SWEEP", "off")


@pytest.fixture(autouse=True)
def _accounts():
    """Accounts of this test's own: a Postgres database of its own (packages/testing), two-step login not required (a test about it sets
    `accounts.config` itself). Logins from auth_config.yaml become accounts on their first use (core/accounts.py)."""
    from trackerai_accounts import Accounts, Config, connect, crypto
    from trackerai_testing import new_database_url

    from app.core import accounts as shared

    cfg = Config(database_url=new_database_url(), session_secret="s" * 40, encryption_key=crypto.new_key(),
                 cookie_secure=False, require_totp="off")
    a = Accounts(connect(cfg.database_url), cfg)
    shared.use(a)
    yield a
    shared.use(None)
    a.engine.dispose()  # closed before packages/testing drops the database: no connections to end first


@pytest.fixture(autouse=True)
def _wealth_schemas(monkeypatch):
    """With WEALTH_DATABASE_URL set, the whole suite runs on Postgres (step 11.7): every test gets schemas of its own
    (WEALTH_SCHEMA_PREFIX) and they are dropped afterwards. Without it nothing happens: SQLite files in tmp_path."""
    url = os.environ.get("WEALTH_DATABASE_URL", "")
    if not url:
        yield
        return
    import uuid

    import psycopg

    prefix = "t" + uuid.uuid4().hex[:10] + "_"
    monkeypatch.setenv("WEALTH_SCHEMA_PREFIX", prefix)
    yield
    with psycopg.connect(url, autocommit=True) as conn:
        # A connection the test left open would hold its locks and make DROP SCHEMA wait for ever. Tests run one at
        # a time against a database of their own, so every other connection to it is that test's leftover.
        conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                     " WHERE datname = current_database() AND pid <> pg_backend_pid()")
        for (schema,) in conn.execute("SELECT nspname FROM pg_namespace WHERE nspname LIKE %s", (prefix + "%",)).fetchall():
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Empty the login/register limiter between tests.

    `throttle` keeps its sliding windows in a module-level dict, which is right
    for one long-lived uvicorn process but makes tests order-dependent: the
    suite logs in as the same handful of users far more often in 15 minutes
    than any person would, so without this the limiter starts answering 429 to
    whichever tests happen to run last.
    """
    from app.core import throttle

    throttle.reset_all()
    yield
    throttle.reset_all()


@pytest.fixture(autouse=True)
def _open_exchange(monkeypatch, request):
    """Run every test as if the exchange is trading.

    The day figures now read a market calendar (price_refresh.traded_today), so
    on a Saturday the chip, the movers and the per-position dagkolom all
    correctly report zero — and every test that asserts the arithmetic behind
    them failed for two days a week. What those tests are about is the sum, not
    the calendar; pinning the calendar open is what lets them keep saying so on
    a Sunday.

    The calendar itself is tested in tests/test_market_calendar.py, which pins
    both answers explicitly and does not use this fixture.
    """
    if request.module.__name__.endswith("test_market_calendar"):
        return  # that test is about the calendar itself
    from app.core import price_refresh

    monkeypatch.setattr(price_refresh, "traded_today", lambda now=None: True)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """An API client with two accounts, over a throwaway data dir.

    Two, not one, so cross-user isolation is always testable: every endpoint
    here is scoped by the session cookie alone.
    """
    from domain import database
    from app.core import config, security
    from app.main import app

    monkeypatch.setattr(database, "_HERE", str(tmp_path))

    auth_path = tmp_path / "auth_config.yaml"
    cfg = {
        "cookie": {"name": "test_cookie", "key": "test-signing-key", "expiry_days": 30},
        "credentials": {
            "usernames": {
                "alice": {"name": "Alice", "email": "alice@local", "password": security.hash_password("alicepw")},
                "bob": {"name": "Bob", "email": "bob@local", "password": security.hash_password("bobpw")},
            }
        },
        # Money sits behind a beta flag; most tests are about it.
        # test_money_beta.py removes it to test the gating.
        "beta": {"money": ["alice", "bob"]},
    }
    auth_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(config, "AUTH_CONFIG_PATH", str(auth_path))

    # A browser names the page's origin on every POST/PUT/PATCH/DELETE; the CSRF
    # check (app/websec/csrf.py) refuses a cookie-carrying write without it.
    return TestClient(app, headers={"Origin": "http://testserver"})
