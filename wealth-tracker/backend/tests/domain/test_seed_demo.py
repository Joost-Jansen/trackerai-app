"""The demo account (scripts/seed_demo.py): made up, offline and usable at once."""

import os
import sys
from datetime import date

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "scripts"))

import seed_demo  # noqa: E402

from domain import database  # noqa: E402

END = date(2026, 10, 2)


@pytest.fixture()
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AUTH_CONFIG_PATH", str(tmp_path / "auth_config.yaml"))
    return tmp_path


def test_creates_an_admin_with_portfolio_and_money(environment):
    off = seed_demo.seed(END, "demo-wachtwoord", offline=True)
    assert off["admin"] and not off["real_prices"]
    cfg = yaml.safe_load((environment / "auth_config.yaml").read_text())
    assert cfg["admins"] == ["demo"] and "demo" in cfg["beta"]["money"]
    assert cfg["credentials"]["usernames"]["demo"]["password"].startswith("$2")
    with database.user_db("demo") as conn:
        assert len(database.load_transactions(conn)) == off["transactions"] > 100
        assert len(database.load_dividends(conn)) == off["dividends"] > 10
        assert set(database.load_prices(conn)) == {f[0] for f in seed_demo.FUNDS}
        assert conn.execute("SELECT COUNT(*) FROM bank_transactions").fetchone()[0] == off["bank_transactions"]
    assert off["labelled"]["coverage"] > 90


def test_price_series_is_fixed_and_ends_at_todays_price():
    a = seed_demo.price_series("TEST.AS", date(2024, 1, 1), END, 50.0)
    b = seed_demo.price_series("TEST.AS", date(2025, 1, 1), END, 50.0)
    assert a[max(a)] == 50.0
    assert all(a[d] == b[d] for d in b)


def test_a_second_time_only_with_reset(environment):
    seed_demo.seed(END, "demo-wachtwoord", offline=True)
    with pytest.raises(SystemExit):
        seed_demo.seed(END, "demo-wachtwoord", offline=True)
    seed_demo.seed(END, "nieuw-wachtwoord", reset=True, offline=True)
    with database.user_db("demo") as conn:
        assert database.load_transactions(conn)  # not doubled: the old folder is gone
        count = len(database.load_transactions(conn))
    assert count < 200
