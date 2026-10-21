import psycopg
import pytest

from trackerai_testing import create_database, database_url, drop_database, new_database_url

_seen: list[str] = []


def _exists(url: str) -> bool:
    name = url.rsplit("/", 1)[1]
    with psycopg.connect(database_url(url, "postgres")) as conn:
        return conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is not None


def test_each_test_gets_an_empty_database_of_its_own(pg_url, new_pg_url):
    other = new_pg_url()
    assert other != pg_url
    with psycopg.connect(pg_url) as conn:
        conn.execute("CREATE TABLE t (x int)")
    with psycopg.connect(other) as conn:
        assert conn.execute("SELECT count(*) FROM pg_tables WHERE tablename = 't'").fetchone()[0] == 0
    _seen.extend([pg_url, other])


def test_the_databases_of_the_test_before_are_gone():
    assert _seen and not any(_exists(u) for u in _seen)


def test_a_plain_helper_gets_one_too_and_an_open_connection_does_not_hold_up_the_drop():
    conn = psycopg.connect(new_database_url())  # deliberately left open: DROP DATABASE ... WITH (FORCE) ends it
    conn.execute("SELECT 1")


def test_a_wider_fixture_keeps_its_database_until_it_drops_it():
    url = create_database()
    assert _exists(url)
    drop_database(url)
    assert not _exists(url)


def test_only_test_databases_are_dropped():
    with pytest.raises(ValueError):
        drop_database("postgresql://u:p@localhost/health")


def test_database_url_keeps_credentials_host_and_options():
    url = "postgresql://u:p@db.local:5432/postgres?sslmode=disable"
    assert database_url(url, "t_1") == "postgresql://u:p@db.local:5432/t_1?sslmode=disable"
