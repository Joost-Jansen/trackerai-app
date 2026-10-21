import pytest
import yaml

from app.core import auth_store, config, security


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    path = tmp_path / "auth_config.yaml"
    cfg = {
        "cookie": {"name": "test_cookie", "key": "test-signing-key", "expiry_days": 30},
        "credentials": {
            "usernames": {
                "alice": {"name": "Alice", "email": "alice@local", "password": security.hash_password("alicepw")},
            }
        },
        "admins": ["alice"],
    }
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(config, "AUTH_CONFIG_PATH", str(path))
    return path


def test_verify_credentials_success_and_failure():
    assert auth_store.verify_credentials("alice", "alicepw") is not None
    assert auth_store.verify_credentials("alice", "wrong") is None
    assert auth_store.verify_credentials("nobody", "anything") is None


def test_is_admin():
    assert auth_store.is_admin("alice") is True
    assert auth_store.is_admin("bob") is False


def test_register_user_requires_invite_code():
    with pytest.raises(auth_store.AuthError):
        auth_store.register_user("bob", "Bob", "bob-pw-2026", invite_code="wrong")

    cfg = auth_store.load_config()
    cfg["registration_code"] = "letmein"
    auth_store.save_config(cfg)

    auth_store.register_user("bob", "Bob", "bob-pw-2026", invite_code="letmein")
    assert auth_store.verify_credentials("bob", "bob-pw-2026") is not None


def test_register_user_rejects_taken_username():
    cfg = auth_store.load_config()
    cfg["registration_code"] = "letmein"
    auth_store.save_config(cfg)
    with pytest.raises(auth_store.AuthError):
        auth_store.register_user("alice", "Alice2", "pw", invite_code="letmein")


def test_beta_features_admin_always_true():
    assert auth_store.has_beta("alice", "rebalancing") is True  # admin
    assert auth_store.has_beta("bob", "rebalancing") is False  # not admin, not granted

    auth_store.set_beta_features("alice", {"rebalancing": ["bob"]})
    assert auth_store.has_beta("bob", "rebalancing") is True


def test_set_registration_mode_admin_only():
    with pytest.raises(auth_store.AuthError):
        auth_store.set_registration_mode("bob", "invite", "somecode")  # bob isn't admin
    auth_store.set_registration_mode("alice", "invite", "somecode")
    cfg = auth_store.load_config()
    assert cfg["registration_mode"] == "invite"
    assert cfg["registration_code"] == "somecode"


def test_registration_mode_derives_from_legacy_code():
    # No mode, no code -> closed (nobody can sign up).
    assert auth_store.registration_mode() == "closed"
    # A bare legacy registration_code still means invite-only.
    cfg = auth_store.load_config()
    cfg["registration_code"] = "letmein"
    auth_store.save_config(cfg)
    assert auth_store.registration_mode() == "invite"


def test_open_mode_registers_without_a_code():
    auth_store.set_registration_mode("alice", "open")
    auth_store.register_user("bob", "Bob", "bob-pw-2026", invite_code="")
    assert auth_store.verify_credentials("bob", "bob-pw-2026") is not None


def test_suspend_and_delete_guardrails():
    auth_store.set_registration_mode("alice", "open")
    auth_store.register_user("bob", "Bob", "bob-pw-2026", invite_code="")

    auth_store.set_suspended("alice", "bob", True)
    assert auth_store.is_suspended("bob") is True
    with pytest.raises(auth_store.AuthError):  # can't suspend yourself
        auth_store.set_suspended("alice", "alice", True)
    with pytest.raises(auth_store.AuthError):  # can't demote the last admin
        auth_store.set_admin("alice", "alice", False)
    with pytest.raises(auth_store.AuthError):  # can't delete yourself
        auth_store.delete_user("alice", "alice")

    auth_store.delete_user("alice", "bob")
    assert auth_store.verify_credentials("bob", "bob-pw-2026") is None


def test_list_users_admin_only():
    with pytest.raises(auth_store.AuthError):
        auth_store.list_users("bob")
    users = auth_store.list_users("alice")
    assert len(users) == 1
    alice = users[0]
    assert alice["username"] == "alice"
    assert alice["is_admin"] is True
    assert alice["suspended"] is False
    assert alice["beta_features"] == []


def test_password_policy_applies_when_a_password_is_set():
    auth_store.set_registration_mode("alice", "open")
    for weak, code in (("short", "password_too_short"), ("password123", "password_too_common"), ("carol-smith", "password_is_username")):
        with pytest.raises(auth_store.AuthError) as e:
            auth_store.register_user("carol-smith", "Carol", weak, invite_code="")
        assert e.value.code == code
    with pytest.raises(auth_store.AuthError) as e:
        auth_store.reset_password("alice", "alice", "1234567890")
    assert e.value.code == "password_too_common"
    # A temporary password from an admin reset passes its own policy.
    temporary = auth_store.reset_password("alice", "alice")
    assert len(temporary) >= 10


def test_an_existing_short_password_still_logs_in():
    # "alicepw" predates the policy: login never applies it.
    assert auth_store.verify_credentials("alice", "alicepw") is not None


def test_a_password_longer_than_72_bytes_works():
    auth_store.set_registration_mode("alice", "open")
    long_pw = "éñçøü" * 10  # 100 bytes (and not one repeated character, which the policy calls common)
    auth_store.register_user("carol", "Carol", long_pw, invite_code="")
    assert auth_store.verify_credentials("carol", long_pw) is not None


def test_writes_are_atomic_and_private_when_the_folder_allows(tmp_path):
    import os
    import stat

    auth_store.set_locale("alice", "en")
    path = config.AUTH_CONFIG_PATH
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    # No temp files left behind next to it.
    assert [f for f in os.listdir(os.path.dirname(path)) if f.startswith(".auth_config.")] == []


def test_single_file_mount_still_writes_in_place(monkeypatch):
    """The original Pi setup bind-mounts only the file; its folder is read-only."""
    import os

    monkeypatch.setattr(auth_store, "_dir_writable", lambda: False)
    before = os.stat(config.AUTH_CONFIG_PATH).st_ino
    auth_store.set_locale("alice", "nl")
    assert os.stat(config.AUTH_CONFIG_PATH).st_ino == before
    assert auth_store.get_locale("alice") == "nl"
