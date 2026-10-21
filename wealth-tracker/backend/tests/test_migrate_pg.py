"""domain/migrate_pg.py: every user's SQLite file into their Postgres schema, once, checked (step 11.7d).

Runs when WEALTH_TEST_DATABASE_URL points at a Postgres the test may make schemas in; skipped otherwise.
"""

import os
import sqlite3
import uuid

import psycopg
import pytest

from domain import database, db, migrate_pg

PG_URL = os.environ.get("WEALTH_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="WEALTH_TEST_DATABASE_URL not set")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """SQLite files first (no WEALTH_DATABASE_URL), then Postgres with schemas of this test's own."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv(db.URL_VAR, raising=False)
    prefix = "m" + uuid.uuid4().hex[:10] + "_"
    monkeypatch.setenv("WEALTH_SCHEMA_PREFIX", prefix)
    yield monkeypatch
    with psycopg.connect(PG_URL, autocommit=True) as conn:
        for (schema,) in conn.execute("SELECT nspname FROM pg_namespace WHERE nspname LIKE %s", (prefix + "%",)):
            conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


def _sqlite_user(folder: str, *, extra=None) -> None:
    conn = database.connect(folder)
    try:
        database.init_db(conn)
        conn.execute("INSERT INTO settings (key, value) VALUES ('theme', 'dark')")
        conn.execute(
            "INSERT INTO prices (isin, name, ticker, price, currency, fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("NL001", "Fund 50%", "FND", 12.3456789, "EUR", "2026-10-09 17:00:00"),
        )
        conn.execute("INSERT INTO budgets (group_name, amount) VALUES (?, ?)", ("Wonen", 1250.5))
        if extra:
            extra(conn)
        conn.commit()
    finally:
        conn.close()


def _switch(monkeypatch):
    monkeypatch.setenv(db.URL_VAR, PG_URL)


def test_copies_every_table_and_checks_it(env):
    _sqlite_user("anna")
    _sqlite_user("bob")
    before = sqlite3.connect(database.db_path_for_user("anna")).execute("SELECT COUNT(*) FROM categories").fetchone()[0]
    _switch(env)
    result = migrate_pg.migrate_all()
    assert set(result["copied"]) == {"anna", "bob"} and result["already"] == []
    assert result["copied"]["anna"]["prices"] == 1 and result["copied"]["anna"]["categories"] == before
    with database.user_db("anna") as conn:
        assert database.load_setting(conn, "theme") == "dark"
        row = conn.execute("SELECT name, price FROM prices WHERE isin = ?", ("NL001",)).fetchone()
        assert row["name"] == "Fund 50%" and row["price"] == 12.3456789
        # New rows continue after the copied ids.
        cur = conn.execute("INSERT INTO budgets (group_name, amount) VALUES (?, ?)", ("Boodschappen", 400))
        conn.commit()
        assert cur.lastrowid is None or cur.lastrowid > 0
    # The SQLite file is untouched, and a second run leaves everyone alone.
    assert os.path.isfile(database.db_path_for_user("anna"))
    assert migrate_pg.migrate_all() == {"copied": {}, "already": ["anna", "bob"]}


def test_the_example_account_is_not_copied(env):
    _sqlite_user("anna")
    _sqlite_user("_example")
    _switch(env)
    assert set(migrate_pg.migrate_all()["copied"]) == {"anna"}


def test_values_sqlite_let_through_are_checked(env):
    # SQLite keeps whatever it is given; a REAL column holding text cannot go into Postgres as it is.
    _sqlite_user("anna", extra=lambda c: c.execute("INSERT INTO budgets (group_name, amount) VALUES ('X', 'lots')"))
    _switch(env)
    with pytest.raises(migrate_pg.MigrationError, match="anna"):
        migrate_pg.migrate_all()
    assert db.open_existing("anna") is None  # no half copy stays behind


def test_a_table_the_schema_lacks_stops_the_copy(env):
    _sqlite_user("anna", extra=lambda c: c.execute("CREATE TABLE stray (x TEXT)"))
    _switch(env)
    with pytest.raises(migrate_pg.MigrationError, match="stray"):
        migrate_pg.migrate_all()


def test_numbers_in_text_columns_survive_the_checksum(env):
    _sqlite_user("anna", extra=lambda c: c.execute("INSERT INTO settings (key, value) VALUES ('n', 5), ('f', 0.1)"))
    _switch(env)
    migrate_pg.migrate_all()
    with database.user_db("anna") as conn:
        assert database.load_setting(conn, "n") == "5" and database.load_setting(conn, "f") == "0.1"


def test_needs_a_postgres(env):
    _sqlite_user("anna")
    with pytest.raises(migrate_pg.MigrationError, match="WEALTH_DATABASE_URL"):
        migrate_pg.migrate_all()


def test_a_child_whose_parent_is_gone_is_copied_as_it_is(env):
    # SQLite runs with foreign_keys off, so old data has balances of an account that was deleted (seen in production:
    # account_balances.account_id = 2 without account 2). The copy keeps them, as SQLite did.
    _sqlite_user(
        "anna",
        extra=lambda c: c.execute(
            "INSERT INTO account_balances (account_id, date, balance, source) VALUES (2, '2026-01-01', 10, 'manual')"
        ),
    )
    _switch(env)
    assert migrate_pg.migrate_all()["copied"]["anna"]["account_balances"] == 1


def test_the_dry_run_checks_everyone_and_leaves_nothing(env):
    _sqlite_user("anna")
    _sqlite_user("bob")
    # The app stays on SQLite: no WEALTH_DATABASE_URL, only the address to check against.
    result = migrate_pg.check_all(PG_URL)
    assert set(result["checked"]) == {"anna", "bob"} and result["checked"]["anna"]["settings"] >= 1
    env.setenv(db.URL_VAR, PG_URL)
    assert db.open_existing("anna") is None and db.open_existing("bob") is None
    # And the real move afterwards still copies them.
    assert set(migrate_pg.migrate_all()["copied"]) == {"anna", "bob"}


def test_the_dry_run_names_the_user_that_fails(env):
    _sqlite_user("anna", extra=lambda c: c.execute("INSERT INTO budgets (group_name, amount) VALUES ('X', 'lots')"))
    with pytest.raises(migrate_pg.MigrationError, match="anna"):
        migrate_pg.check_all(PG_URL)
