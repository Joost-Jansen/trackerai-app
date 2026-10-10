"""S9: APP_ENCRYPTION_KEY is required in production, the old key file can be
taken over, and the Enable Banking session id is encrypted at rest."""

import pytest
from cryptography.fernet import Fernet

from app.core import config, startup
from domain import database, secret_box
from domain.money import bank_link


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    return tmp_path


def test_production_refuses_to_start_without_a_key(data, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_INSECURE_DEFAULTS", False)
    monkeypatch.delenv("ALLOW_INSECURE_DEFAULTS", raising=False)
    # the shared accounts are set up (test_the_shared_accounts_are_required covers them missing)
    monkeypatch.setenv("ACCOUNTS_DATABASE_URL", "sqlite://")
    monkeypatch.setenv("ACCOUNTS_SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("ACCOUNTS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(RuntimeError, match="APP_ENCRYPTION_KEY"):
        startup.check()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "not-a-key")
    with pytest.raises(RuntimeError, match="not a valid"):
        startup.check()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    startup.check()


def test_the_shared_accounts_are_required(data, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_INSECURE_DEFAULTS", False)
    monkeypatch.delenv("ALLOW_INSECURE_DEFAULTS", raising=False)
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    for name in ("ACCOUNTS_DATABASE_URL", "ACCOUNTS_SESSION_SECRET", "ACCOUNTS_ENCRYPTION_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match="ACCOUNTS_DATABASE_URL"):
        startup.check()


def test_the_opt_out_allows_development(data, monkeypatch):
    monkeypatch.setattr(config, "ALLOW_INSECURE_DEFAULTS", True)
    startup.check()


def test_the_old_key_file_is_taken_over(data, monkeypatch):
    # Encrypted before APP_ENCRYPTION_KEY existed: with the key file the app made.
    old_token = secret_box.encrypt(b"private key")
    assert (data / "data" / ".encryption_key").exists()
    # Now the operator sets a *new* key: the old data stays readable through the file...
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert secret_box.decrypt(old_token) == b"private key"
    assert secret_box.needs_rotation(old_token)
    rotated = secret_box.rotate(old_token)
    assert not secret_box.needs_rotation(rotated)
    # ...and once rotated it no longer needs the file.
    (data / "data" / ".encryption_key").unlink()
    assert secret_box.decrypt(rotated) == b"private key"


def test_setting_the_key_to_the_file_content_changes_nothing(data, monkeypatch):
    token = secret_box.encrypt(b"x")
    key = (data / "data" / ".encryption_key").read_text().strip()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", key)
    assert secret_box.decrypt(token) == b"x"
    assert not secret_box.needs_rotation(token)


def test_session_ids_are_encrypted_and_old_plain_ones_migrated(data, monkeypatch):
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    conn = database.connect("alice")
    database.init_db(conn)
    conn.execute("INSERT INTO bank_consents (bank, country, status, session_id, created_at) "
                 "VALUES ('Bank', 'NL', 'active', 'plain-session-uuid', '2026-01-01T00:00:00+00:00')")
    conn.commit()
    assert bank_link.upgrade_secrets(conn) == 1
    stored = conn.execute("SELECT session_id FROM bank_consents").fetchone()[0]
    assert stored != "plain-session-uuid" and secret_box.looks_encrypted(stored)
    assert bank_link._session_id(stored) == "plain-session-uuid"
    assert bank_link.upgrade_secrets(conn) == 0  # idempotent
    conn.close()
