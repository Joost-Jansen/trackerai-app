"""Postgres for the test suites: a test gets databases of its own, dropped when it ends.

The server comes from TEST_DATABASE_URL, a URL that may create databases (CI: the job's Postgres service). Without it,
the development server of compose.dev.yml (`docker compose -f compose.dev.yml up -d` at the repository root).

    new_database_url()      a new, empty database; dropped when the running test ends (also from a plain helper)
    pg_url                  fixture: one such database for the test
    new_pg_url              fixture: new_database_url, for a test that wants more than one
    create_database()       a database that stays until drop_database(url): for a fixture wider than one test

A database is cheap (`STRATEGY = FILE_COPY` from an empty template, some 20 ms), so tests never share one and never
clean up. Dropping uses `WITH (FORCE)`, so an engine a test left open does not hold it up.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

URL_VAR = "TEST_DATABASE_URL"
DEV_URL = "postgresql://postgres:dev@127.0.0.1:55432/postgres"  # compose.dev.yml
PREFIX = "t_"

_admin: psycopg.Connection | None = None
_this_test: list[str] = []  # made by new_database_url() during the running test


def server_url() -> str:
    return os.environ.get(URL_VAR, "").strip() or DEV_URL


def database_url(server: str, name: str) -> str:
    """`server` with its database swapped for `name`."""
    return urlunsplit(urlsplit(server)._replace(path="/" + name))


def _connection() -> psycopg.Connection:
    global _admin
    if _admin is None or _admin.closed:
        try:
            _admin = psycopg.connect(server_url(), autocommit=True, connect_timeout=5)
        except psycopg.OperationalError as e:
            pytest.fail(
                f"no Postgres for the tests ({URL_VAR}, else {DEV_URL.split('@')[1]}): {e}\n"
                "Start one at the repository root: docker compose -f compose.dev.yml up -d",
                pytrace=False,
            )
    return _admin


def create_database() -> str:
    """A new, empty database's URL. It stays until drop_database."""
    name = PREFIX + uuid.uuid4().hex[:16]
    _connection().execute(f'CREATE DATABASE "{name}" TEMPLATE template0 STRATEGY = FILE_COPY')
    return database_url(server_url(), name)


def drop_database(url: str) -> None:
    name = urlsplit(url).path.lstrip("/")
    if not name.startswith(PREFIX):
        raise ValueError(f"not a test database: {name!r}")
    _connection().execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def new_database_url() -> str:
    """A new, empty database's URL, dropped when the running test ends (after its fixtures are torn down)."""
    url = create_database()
    _this_test.append(url)
    return url


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item, nextitem):
    yield  # the test's fixtures are torn down first: engines they hold close before the drop
    while _this_test:
        drop_database(_this_test.pop())


def pytest_sessionfinish(session, exitstatus):
    if _admin is not None:
        _admin.close()


@pytest.fixture
def new_pg_url() -> Callable[[], str]:
    return new_database_url


@pytest.fixture
def pg_url() -> str:
    return new_database_url()
