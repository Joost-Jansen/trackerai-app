import time
from datetime import UTC, datetime

import pytest
import yaml
from cryptography.fernet import Fernet
from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, MetaData, PrimaryKeyConstraint, String, Table, Text, create_engine, insert

from trackerai_accounts import Accounts, Config, connect, crypto, migrate, totp
from trackerai_accounts.service import hash_password
from trackerai_accounts.store import sqlalchemy_url

T = datetime(2026, 1, 1, tzinfo=UTC)


def health_db(url, key):
    """health-tracker's users table as it was before the shared accounts, in the database at `url`."""
    m = MetaData()
    users = Table(
        "users",
        m,
        Column("id", Integer, primary_key=True),
        Column("username", String(40)),
        Column("display_name", String(80)),
        Column("password_hash", String(100)),
        Column("is_admin", Boolean),
        Column("suspended", Boolean),
        Column("created_at", DateTime(timezone=True)),
        Column("last_login_at", DateTime(timezone=True)),
        Column("session_version", Integer),
        Column("consent_at", DateTime(timezone=True)),
        Column("privacy_version", String(20)),
        Column("totp_secret", Text),
        Column("totp_enabled_at", DateTime(timezone=True)),
        Column("totp_last_step", Integer),
        Column("totp_backup", JSON),
    )
    settings = Table(
        "settings", m, Column("user_id", Integer), Column("key", String(64)), Column("value", JSON), PrimaryKeyConstraint("user_id", "key")
    )
    app_settings = Table("app_settings", m, Column("key", String(64), primary_key=True), Column("value", JSON))
    engine = create_engine(sqlalchemy_url(url))
    m.create_all(engine)
    with engine.begin() as c:
        for row in [
            dict(
                id=1,
                username="joost",
                password_hash=hash_password("health password 1"),
                is_admin=True,
                suspended=False,
                created_at=T,
                consent_at=T,
                privacy_version="2026-10-07",
                totp_secret=crypto.encrypt("JBSWY3DPEHPK3PXP", key),
                totp_enabled_at=T,
                totp_backup=["h1"],
            ),
            dict(id=2, username="anna", password_hash=hash_password("anna's passphrase"), is_admin=False, suspended=False, created_at=T),
            dict(id=3, username="_example", password_hash="x", is_admin=False, suspended=False, created_at=T),
        ]:
            c.execute(insert(users).values(**row))
        c.execute(insert(settings).values(user_id=2, key="locale", value="en"))
        c.execute(insert(app_settings).values(key="registration", value="invite"))
    return url


def wealth_yaml(path, key):
    box = Fernet(key.encode())
    cfg = {
        "admins": ["Joost"],
        "registration_mode": "open",
        "credentials": {
            "usernames": {
                "Joost": {
                    "name": "Joost",
                    "password": hash_password("wealth password 2"),
                    "totp": {"enabled": True, "secret": box.encrypt(b"KRSXG5CTMVRXEZLU").decode(), "backup_codes": ["w1"]},
                },
                "tim": {
                    "name": "Tim",
                    "password": hash_password("tim's passphrase"),
                    "locale": "nl",
                    "totp": {"enabled": True, "secret": box.encrypt(b"KRSXG5CTMVRXEZLU").decode(), "backup_codes": []},
                },
                "anna": {"name": "Anna W", "password": hash_password("another anna")},
            }
        },
    }
    path.write_text(yaml.safe_dump(cfg))
    return str(path)


@pytest.fixture
def setup(tmp_path, new_pg_url):
    cfg = Config(database_url=new_pg_url(), session_secret="s" * 40, encryption_key=crypto.new_key(), cookie_secure=False)
    target = Accounts(connect(cfg.database_url), cfg)
    hkey, wkey = crypto.new_key(), crypto.new_key()
    health, hmode = migrate.read_health(health_db(new_pg_url(), hkey), hkey)
    return target, health, hmode, tmp_path, wkey


def test_a_clash_stops_the_import(setup):
    target, health, hmode, tmp, wkey = setup
    wealth, wmode = migrate.read_wealth(wealth_yaml(tmp / "auth.yaml", wkey), [wkey], {})
    p = migrate.plan(target, health, wealth, {"joost"}, None, [hmode, wmode])
    assert len(p.clashes) == 1 and "'anna'" in p.clashes[0]


def test_import(setup):
    target, health, hmode, tmp, wkey = setup
    assert [p.name for p in health] == ["joost", "anna"]  # not the example account
    wealth, wmode = migrate.read_wealth(wealth_yaml(tmp / "auth.yaml", wkey), [wkey], {"anna": "anna.w"})
    p = migrate.plan(target, health, wealth, {"joost"}, None, [hmode, wmode])
    assert not p.clashes and p.registration == "invite" and p.admins == {"joost"}
    migrate.apply(target, p)

    joost = target.by_username("joost")
    apps = target.apps(joost["id"])
    assert {a: r["local_key"] for a, r in apps.items()} == {"health": "1", "wealth": "Joost"}
    assert apps["health"]["is_admin"] and apps["wealth"]["is_admin"] and joost["is_admin"]
    # both passwords open it until it changes; the health two-step secret is kept
    assert target.login("joost", "health password 1", totp.code_at("JBSWY3DPEHPK3PXP"))
    assert target.login("joost", "wealth password 2", totp.code_at("JBSWY3DPEHPK3PXP", time.time() + 30))
    tim = target.by_username("tim")
    assert crypto.decrypt(tim["totp_secret"], target.config.encryption_key) == "KRSXG5CTMVRXEZLU" and tim["locale"] == "nl"
    assert not tim["is_admin"]
    assert target.local_key(target.by_username("anna.w")["id"], "wealth") == "anna"
    assert target.by_username("anna")["locale"] == "en"
    assert target.registration_mode() == "invite"

    # again: nothing new
    again = migrate.plan(target, health, wealth, {"joost"}, None, [hmode, wmode])
    assert not again.new and not again.joins and len(again.skipped) == 5


def test_wrong_key_drops_two_step_login_with_a_note(setup):
    target, health, hmode, tmp, wkey = setup
    wealth, _ = migrate.read_wealth(wealth_yaml(tmp / "auth.yaml", wkey), [crypto.new_key()], {})
    tim = next(p for p in wealth if p.local_key == "tim")
    assert tim.totp_secret is None and "set it up again" in tim.notes[0]
