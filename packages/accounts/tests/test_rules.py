"""The password rules and TOTP itself (moved here from each app's websec copy)."""

import base64

from trackerai_accounts import passwords, totp
from trackerai_accounts.config import Config, front_door_origins, front_door_url, tracker_url


def test_password_rules():
    assert passwords.check_password("short") == "password_too_short"
    assert passwords.check_password("password123") == "password_too_common"
    assert passwords.check_password("1234567890") == "password_too_common"
    assert passwords.check_password("aaaaaaaaaaaa") == "password_too_common"
    assert passwords.check_password("annabanana1", "annabanana1") == "password_is_username"
    assert passwords.check_password("x" * 201) == "password_too_long"
    assert passwords.check_password("paars-fiets-tegel-7") is None
    assert len(passwords.common_passwords()) > 5000


def test_totp_rfc6238_vectors():
    # RFC 6238 appendix B, SHA1, secret "12345678901234567890", 8 digits
    secret = base64.b32encode(b"12345678901234567890").decode()
    for t, code in ((59, "94287082"), (1111111109, "07081804"), (1234567890, "89005924"), (2000000000, "69279037")):
        assert totp.hotp(secret, t // 30, digits=8) == code


def test_totp_verify_window_and_replay():
    secret = totp.new_secret()
    t = 1_800_000_000
    code = totp.code_at(secret, t)
    step = totp.verify(secret, code, None, t=t)
    assert step == t // 30
    assert totp.verify(secret, code, step, t=t) is None  # replay refused
    assert totp.verify(secret, totp.code_at(secret, t - 30), None, t=t) == step - 1  # clock drift
    assert totp.verify(secret, totp.code_at(secret, t - 90), None, t=t) is None
    assert totp.verify(secret, "abc", None, t=t) is None
    uri = totp.otpauth_uri(secret, "anna", "trackerai")
    assert uri.startswith("otpauth://totp/trackerai%3Aanna?") and f"secret={secret}" in uri


def test_backup_codes_are_single_use():
    codes, hashes = totp.new_backup_codes(10)
    assert len(set(codes)) == 10 and len(hashes) == 10 and codes[0] not in hashes
    left = totp.use_backup_code(codes[3].upper().replace("-", " "), hashes)
    assert left is not None and len(left) == 9
    assert totp.use_backup_code(codes[3], left) is None


def test_front_door_origins():
    assert front_door_origins("trackerai.nl") == ["https://trackerai.nl", "https://www.trackerai.nl"]
    assert front_door_origins(" .TrackerAI.nl ") == ["https://trackerai.nl", "https://www.trackerai.nl"]
    assert front_door_origins("") == [] and front_door_origins(None) == []


def test_tracker_url(monkeypatch):
    assert tracker_url("health", " https://health.example/ ", "trackerai.nl") == "https://health.example"  # set: as given
    assert tracker_url("wealth", "", ".TrackerAI.nl") == "https://wealth.trackerai.nl"  # derived from the cookie domain
    assert tracker_url("health", "", None) is None  # a tracker on its own
    monkeypatch.setenv("SESSION_COOKIE_DOMAIN", "trackerai.nl")
    monkeypatch.setenv("LANDING_HEALTH_URL", "https://fit.example")
    monkeypatch.delenv("LANDING_WEALTH_URL", raising=False)
    assert Config.from_env().tracker_urls == {"health": "https://fit.example", "wealth": "https://wealth.trackerai.nl"}


def test_front_door_url(monkeypatch):
    assert front_door_url(" https://www.trackerai.nl/ ", "other.nl") == "https://www.trackerai.nl"  # set: as given
    assert front_door_url("", ".TrackerAI.nl") == "https://www.trackerai.nl"  # empty: derived from the cookie domain
    assert front_door_url("", None) is None  # a tracker on its own
    monkeypatch.setenv("SESSION_COOKIE_DOMAIN", "trackerai.nl")
    monkeypatch.delenv("FRONT_DOOR_URL", raising=False)
    assert Config.from_env().front_door_url == "https://www.trackerai.nl"
    monkeypatch.setenv("FRONT_DOOR_URL", "https://trackerai.example")
    assert Config.from_env().front_door_url == "https://trackerai.example"
    monkeypatch.delenv("FRONT_DOOR_URL")
    monkeypatch.delenv("SESSION_COOKIE_DOMAIN")
    assert Config.from_env().front_door_url is None
