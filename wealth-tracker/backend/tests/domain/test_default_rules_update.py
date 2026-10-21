"""
New default rules also reach whoever already had their rules — once.

seed() only puts down the default rules when there are no rules yet, so a rule
you throw away stays thrown away. Because of that an existing user never got a
rule that was added later: a savings account's interest stayed unknown, while
a new user did recognise it. Now: per version what was added, added once, and
left alone after that.
"""

import pytest

from domain import database
from domain.money import accounts, bank_transactions, categorization


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


@pytest.fixture()
def conn():
    conn = database.connect("alice")
    database.init_db(conn)
    yield conn
    conn.close()


def _rules(conn) -> set[tuple]:
    return {(r["field"], r["pattern"], r["direction"], r["category"]) for r in categorization.load_rules(conn, only_active=False)}


def _new_in_2() -> set[tuple]:
    return {r[1:] for r in categorization.RULES_SINCE[2]}


def _if_version_1(conn):
    """A user from before version 2: without the version 2 rules, without a version."""
    for field, pattern, direction, category in _new_in_2():
        conn.execute("DELETE FROM rules WHERE field=? AND pattern=? AND direction=? AND category=?", (field, pattern, direction, category))
    conn.execute("DELETE FROM settings WHERE key = 'default_rules_version'")
    conn.commit()


def test_a_new_user_gets_the_full_set_and_the_latest_version(conn):
    """A new user gets the broadened patterns in DEFAULT_RULES itself, not the
    separate additions for existing users — and nothing extra after that.
    """
    categorization.seed(conn)
    assert categorization._read_version(conn) == categorization.DEFAULT_RULES_VERSION
    assert {r[1:] for r in categorization.DEFAULT_RULES} == _rules(conn)
    categorization.seed(conn)
    assert len(categorization.load_rules(conn, only_active=False)) == len(categorization.DEFAULT_RULES)


def test_an_existing_user_gets_the_new_rules(conn):
    categorization.seed(conn)
    _if_version_1(conn)
    assert not _new_in_2() & _rules(conn)

    categorization.seed(conn)
    assert _new_in_2() <= _rules(conn)


def test_only_once(conn):
    categorization.seed(conn)
    _if_version_1(conn)
    categorization.seed(conn)
    count = len(categorization.load_rules(conn, only_active=False))
    categorization.seed(conn)
    assert len(categorization.load_rules(conn, only_active=False)) == count


def test_a_rule_thrown_away_afterwards_stays_away(conn):
    categorization.seed(conn)
    _if_version_1(conn)
    categorization.seed(conn)
    payday = next(r for r in categorization.load_rules(conn, only_active=False) if r["pattern"] == "BUNQ PAYDAY")
    categorization.delete_rule(conn, payday["id"])
    categorization.seed(conn)
    assert not any(r["pattern"] == "BUNQ PAYDAY" for r in categorization.load_rules(conn, only_active=False))


def test_an_own_rule_that_was_already_there_is_not_added_twice(conn):
    categorization.seed(conn)
    _if_version_1(conn)
    categorization.make_rule(conn, priority=40, field="T", pattern="BUNQ PAYDAY", direction="C", category="Overige inkomsten")
    categorization.seed(conn)
    assert sum(1 for r in categorization.load_rules(conn, only_active=False) if r["pattern"] == "BUNQ PAYDAY") == 1


def test_what_was_unknown_is_recognised_at_once(conn):
    """The interest that was already in does not have to wait for the next import."""
    categorization.seed(conn)
    _if_version_1(conn)
    rid = accounts.make_bank_account(conn, kind="bank", provider="bunq", name="bunq")
    tid = bank_transactions.add_manually(
        conn, account_id=rid, date="2026-04-17", amount=-2.08, name="bunq", description="bunq Payday 2026-04-17 EUR"
    )
    categorization.relabel(conn)
    assert next(r for r in bank_transactions.load(conn) if r["id"] == tid)["category"] == categorization.UNKNOWN

    categorization.seed(conn)
    assert next(r for r in bank_transactions.load(conn) if r["id"] == tid)["category"] == "Overige inkomsten"


def _exclude(conn):
    return next((c for c in categorization.load_categories(conn) if c["name"] == "Niet meetellen"), None)


def test_an_existing_user_gets_exclude_once(conn):
    categorization.seed(conn)
    conn.execute("DELETE FROM categories WHERE name = 'Niet meetellen'")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('default_rules_version', '2')")
    conn.commit()

    categorization.seed(conn)
    cat = _exclude(conn)
    assert cat is not None and cat["type"] == "INTERNAL"

    categorization.delete_category(conn, cat["id"])
    categorization.seed(conn)
    assert _exclude(conn) is None, "weggegooid blijft weg"


def test_exclude_counts_neither_as_income_nor_as_spending(conn):
    """Money you hold for a friend: in and out again, without changing your income
    or spending.
    """
    from domain.money import net_worth

    categorization.seed(conn)
    rid = accounts.make_bank_account(conn, kind="bank", provider="manual", name="Bank")
    for amount in (-500.0, 500.0):
        tid = bank_transactions.add_manually(conn, account_id=rid, date="2026-03-10", amount=amount, name="A. VOORBEELD")
        bank_transactions.set_category_manual(conn, tid, "Niet meetellen")
    march = next(m for m in net_worth.per_month(conn) if m["month"] == "2026-03")
    assert march["spending"] == 0 and march["income"] == 0


def test_bunq_payday_is_interest(conn):
    categorization.seed(conn)
    rid = accounts.make_bank_account(conn, kind="bank", provider="bunq", name="bunq")
    tid = bank_transactions.add_manually(
        conn, account_id=rid, date="2026-04-17", amount=-2.08, name="bunq", description="bunq Payday 2026-04-17 EUR"
    )
    categorization.relabel(conn)
    row = next(r for r in bank_transactions.load(conn) if r["id"] == tid)
    assert row["category"] == "Overige inkomsten" and row["type"] == "INCOME"


def _group(conn, name):
    return next(c["group_name"] for c in categorization.load_categories(conn) if c["name"] == name)


def test_holiday_its_own_group_and_leisure_under_food(conn):
    """From version 5 to 6: the new layout, except what you moved yourself."""
    categorization.seed(conn)
    for name, old, _ in categorization.GROUPS_SINCE[6]:
        conn.execute("UPDATE categories SET group_name = ? WHERE name = ?", (old, name))
    conn.execute("UPDATE categories SET group_name = 'Mijn sport' WHERE name = 'Sport & hobby'")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('default_rules_version', '5')")
    conn.commit()

    categorization.seed(conn)
    assert _group(conn, "Vakantie") == "Vakantie"
    assert {_group(conn, n) for n in ("Lunch werk", "Cafe & uitgaan", "Uit eten & bezorgen", "Uitjes & evenementen")} == {
        "Eten & vrije tijd"
    }
    assert _group(conn, "Sport & hobby") == "Mijn sport", "wat je zelf verplaatste blijft"


def test_a_new_user_gets_the_new_layout(conn):
    categorization.seed(conn)
    groups = {c["group_name"] for c in categorization.load_categories(conn)}
    assert "Eten & vrije tijd" in groups and "Vakantie" in groups
    assert "Vrije tijd" not in groups and "Eten & drinken" not in groups


def test_sport_and_hobby_under_shopping(conn):
    """From version 6 to 7: Sport & hobby to the same group as clothing."""
    categorization.seed(conn)
    conn.execute("UPDATE categories SET group_name = 'Eten & vrije tijd' WHERE name = 'Sport & hobby'")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('default_rules_version', '6')")
    conn.commit()
    categorization.seed(conn)
    assert _group(conn, "Sport & hobby") == _group(conn, "Kleding & schoenen") == "Shoppen"


def test_from_version_5_in_one_go_to_the_latest_layout(conn):
    categorization.seed(conn)
    conn.execute("UPDATE categories SET group_name = 'Vrije tijd' WHERE name IN ('Sport & hobby', 'Vakantie', 'Uitjes & evenementen')")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('default_rules_version', '5')")
    conn.commit()
    categorization.seed(conn)
    assert (_group(conn, "Sport & hobby"), _group(conn, "Vakantie"), _group(conn, "Uitjes & evenementen")) == (
        "Shoppen",
        "Vakantie",
        "Eten & vrije tijd",
    )


def test_a_budget_on_an_old_main_category_moves_along(conn):
    """Version 6 left "Eten & drinken" and "Vrije tijd" empty; their budget went nowhere."""
    categorization.seed(conn)
    conn.executemany("INSERT INTO budgets (group_name, amount) VALUES (?, ?)", [("Eten & drinken", 200.0), ("Vrije tijd", 100.0)])
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('default_rules_version', '6')")
    conn.commit()
    categorization.seed(conn)
    budgets = {r["group_name"]: r["amount"] for r in conn.execute("SELECT * FROM budgets")}
    assert budgets == {"Eten & vrije tijd": 300.0}
