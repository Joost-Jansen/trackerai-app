"""
Running without bind mounts: paths from the environment and the first account.

On the Pi data/ and auth_config.yaml sit next to the code, attached to the
container. A host like Railway cannot do that; there everything is on a volume
and there is no shell to create the first account with. These tests pin down
that both go through environment variables, and that an existing installation
notices nothing.
"""

import os
import stat

import pytest
import yaml

from app.core import auth_store, bootstrap, config
from domain import database

# About SQLite itself (its files, WAL, locks, threads): not run when the suite runs on Postgres (WEALTH_DATABASE_URL).
sqlite_only = pytest.mark.skipif(bool(os.environ.get("WEALTH_DATABASE_URL")), reason="about SQLite itself")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def test_without_data_dir_the_data_stays_next_to_the_code(tmp_path, monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    assert database.data_root() == str(tmp_path / "data")
    assert database.user_data_dir("alice") == str(tmp_path / "data" / "users" / "alice")


@sqlite_only
def test_data_dir_moves_all_user_data(tmp_path, monkeypatch):
    volume = tmp_path / "volume"
    monkeypatch.setenv("DATA_DIR", str(volume))
    assert database.data_root() == str(volume)
    assert database.db_path_for_user("alice") == str(volume / "users" / "alice" / "portfolio.db")

    conn = database.connect("alice")
    conn.close()
    assert (volume / "users" / "alice" / "portfolio.db").exists()


@sqlite_only
def test_a_connection_uses_wal_and_waits_on_a_lock(tmp_path, monkeypatch):
    """Otherwise a writing price loop gives a request "database is locked" straight away."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    conn = database.connect("alice")
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000
    finally:
        conn.close()


@sqlite_only
def test_a_writer_outwaits_a_lock_longer_than_five_seconds(tmp_path, monkeypatch):
    """A dozen requests and the price loop after a login held the write lock for more than 5 s on Railway, and pages
    failed with "database is locked". A writer now waits for the lock instead (up to database.BUSY_TIMEOUT_MS)."""
    import threading
    import time

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    holder, writer = database.connect("alice", same_thread_only=False), database.connect("alice")
    try:
        holder.execute("CREATE TABLE t (x INTEGER)")
        holder.commit()
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO t VALUES (1)")
        threading.Timer(6.0, holder.commit).start()
        started = time.monotonic()
        writer.execute("INSERT INTO t VALUES (2)")
        writer.commit()
        assert time.monotonic() - started >= 5.5
        assert writer.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    finally:
        holder.close()
        writer.close()


# ---------------------------------------------------------------------------
# First account
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_config(tmp_path, monkeypatch):
    path = tmp_path / "volume" / "auth_config.yaml"
    monkeypatch.setattr(config, "AUTH_CONFIG_PATH", str(path))
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    return path


def test_creates_the_first_account_as_admin(empty_config, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "een-lang-wachtwoord")

    assert bootstrap.first_account() == "admin"

    assert auth_store.verify_credentials("admin", "een-lang-wachtwoord") is not None
    assert auth_store.verify_credentials("admin", "error") is None
    assert auth_store.is_admin("admin")
    assert auth_store.registration_mode() == "closed"


def test_the_password_is_nowhere_readable(empty_config, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "een-lang-wachtwoord")
    bootstrap.first_account()

    assert "een-lang-wachtwoord" not in empty_config.read_text(encoding="utf-8")
    assert stat.S_IMODE(os.stat(empty_config).st_mode) == 0o600


def test_every_server_gets_its_own_signing_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "x")
    keys = []
    for n in range(2):
        path = tmp_path / f"server{n}" / "auth_config.yaml"
        monkeypatch.setattr(config, "AUTH_CONFIG_PATH", str(path))
        bootstrap.first_account()
        keys.append(yaml.safe_load(path.read_text())["cookie"]["key"])
    assert keys[0] != keys[1]
    assert all(len(s) >= 32 for s in keys)


def test_an_existing_file_is_never_touched(empty_config, monkeypatch):
    """A forgotten ADMIN_PASSWORD must not reset a password later."""
    empty_config.parent.mkdir(parents=True)
    empty_config.write_text("credentials: {usernames: {}}\n", encoding="utf-8")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "new")

    assert bootstrap.first_account() is None
    assert empty_config.read_text(encoding="utf-8") == "credentials: {usernames: {}}\n"


def test_without_variables_nothing_happens(empty_config):
    assert bootstrap.first_account() is None
    assert not empty_config.exists()


def test_an_invalid_name_is_refused(empty_config, monkeypatch):
    """The name becomes a folder name under data/users/."""
    monkeypatch.setenv("ADMIN_USERNAME", "../buiten")
    monkeypatch.setenv("ADMIN_PASSWORD", "x")
    with pytest.raises(ValueError):
        bootstrap.first_account()
    assert not empty_config.exists()
