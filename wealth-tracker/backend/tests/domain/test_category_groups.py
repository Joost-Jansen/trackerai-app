"""
Arranging main categories yourself: moving a category, renaming a main
category. Labels and rules point to the category, so they stay right.
"""

import pytest

from domain.money import bank_transactions
from domain.money import categorization
from domain import database
from domain.money import accounts


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


@pytest.fixture()
def conn():
    conn = database.connect("alice")
    database.init_db(conn)
    categorization.seed(conn)
    yield conn
    conn.close()


def _cat(conn, name):
    return next(c for c in categorization.load_categories(conn) if c["name"] == name)


def _groups_contiguous(conn):
    """Every main category is one block in the order, not scattered."""
    seen, previous = set(), None
    for c in categorization.load_categories(conn):
        if c["group_name"] != previous:
            assert c["group_name"] not in seen, f"{c['group_name']} staat op twee plekken"
            seen.add(c["group_name"])
            previous = c["group_name"]


def test_move_to_an_existing_group(conn):
    categorization.move_category(conn, _cat(conn, "Fiets")["id"], "Shoppen")
    assert _cat(conn, "Fiets")["group_name"] == "Shoppen"
    shopping = [c["name"] for c in categorization.load_categories(conn) if c["group_name"] == "Shoppen"]
    assert shopping[-1] == "Fiets", "achteraan in de nieuwe groep"
    _groups_contiguous(conn)


def test_move_to_a_new_group(conn):
    categorization.move_category(conn, _cat(conn, "Fiets")["id"], "  Mobiliteit  ")
    assert _cat(conn, "Fiets")["group_name"] == "Mobiliteit"
    _groups_contiguous(conn)


def test_rename_and_merge(conn):
    assert categorization.rename_group(conn, "Vervoer", "Onderweg") == 3
    assert _cat(conn, "Openbaar vervoer")["group_name"] == "Onderweg"
    categorization.rename_group(conn, "Onderweg", "Shoppen")
    assert _cat(conn, "Fiets")["group_name"] == "Shoppen"
    _groups_contiguous(conn)


def test_labels_stay_right_after_moving(conn):
    rid = accounts.make_bank_account(conn, kind="bank", provider="manual", name="Bank")
    tid = bank_transactions.add_manually(conn, account_id=rid, date="2026-03-01", amount=20.0, name="Fietsenmaker 9")
    bank_transactions.set_category_manual(conn, tid, "Fiets")
    categorization.move_category(conn, _cat(conn, "Fiets")["id"], "Shoppen")
    row = next(r for r in bank_transactions.load(conn) if r["id"] == tid)
    assert row["category"] == "Fiets" and row["group_name"] == "Shoppen"


def test_nonsense(conn):
    with pytest.raises(ValueError):
        categorization.move_category(conn, _cat(conn, "Fiets")["id"], "  ")
    with pytest.raises(ValueError):
        categorization.move_category(conn, _cat(conn, "Onbekend")["id"], "Shoppen")
    with pytest.raises(KeyError):
        categorization.move_category(conn, 99999, "Shoppen")
    with pytest.raises(KeyError):
        categorization.rename_group(conn, "Bestaat niet", "Iets")


def _budget(conn, group_name):
    row = conn.execute("SELECT amount FROM budgets WHERE group_name = ?", (group_name,)).fetchone()
    return row["amount"] if row else None


def test_the_budget_moves_along_and_adds_up_when_merging(conn):
    conn.executemany("INSERT INTO budgets (group_name, amount) VALUES (?, ?)", [("Vervoer", 100.0), ("Shoppen", 50.0)])
    conn.commit()
    categorization.rename_group(conn, "Vervoer", "Onderweg")
    assert (_budget(conn, "Vervoer"), _budget(conn, "Onderweg")) == (None, 100.0)
    categorization.rename_group(conn, "Onderweg", "Shoppen")
    assert _budget(conn, "Shoppen") == 150.0


def test_the_last_category_takes_the_budget_along(conn):
    categorization.move_category(conn, _cat(conn, "Fiets")["id"], "Mobiliteit")
    conn.execute("INSERT INTO budgets (group_name, amount) VALUES ('Mobiliteit', 40)")
    conn.commit()
    categorization.move_category(conn, _cat(conn, "Fiets")["id"], "Vervoer")
    assert (_budget(conn, "Mobiliteit"), _budget(conn, "Vervoer")) == (None, 40.0)


# ---------------------------------------------------------------------------
# Renaming a category
# ---------------------------------------------------------------------------

def test_renaming_takes_transactions_rules_and_suggestions_along(conn):
    rid = accounts.make_bank_account(conn, kind="bank", provider="manual", name="Bank")
    auto = bank_transactions.add_manually(conn, account_id=rid, date="2026-03-01", amount=30.0, name="BASIC-FIT 12")
    hand = bank_transactions.add_manually(conn, account_id=rid, date="2026-03-02", amount=20.0, name="Zaak 9")
    bank_transactions.set_category_manual(conn, hand, "Sport abonnement")
    categorization.relabel(conn)
    conn.execute("INSERT INTO ai_suggestions (transaction_id, category, confidence, created_at) "
                 "VALUES (?, 'Sport abonnement', 0.5, '2026-01-01')", (hand,))
    conn.commit()

    categorization.rename_category(conn, _cat(conn, "Sport abonnement")["id"], "  Sportschool  ")
    rows = {r["id"]: r for r in bank_transactions.load(conn)}
    assert rows[auto]["category"] == "Sportschool" and rows[hand]["category"] == "Sportschool"
    assert rows[auto]["type"] == "EXPENSE", "de categorie is dezelfde, alleen de naam niet"
    assert not any(r["category"] == "Sport abonnement" for r in categorization.load_rules(conn, only_active=False))
    assert conn.execute("SELECT category FROM ai_suggestions").fetchone()["category"] == "Sportschool"
    categorization.relabel(conn, everything=True)
    assert next(r for r in bank_transactions.load(conn) if r["id"] == auto)["category"] == "Sportschool"


def test_fixed_names_and_duplicate_names_are_not_allowed(conn):
    assert _cat(conn, "Salaris")["is_fixed"] and not _cat(conn, "Sport abonnement")["is_fixed"]
    with pytest.raises(ValueError):
        categorization.rename_category(conn, _cat(conn, "Salaris")["id"], "Loon")
    with pytest.raises(ValueError):
        categorization.rename_category(conn, _cat(conn, "Sport abonnement")["id"], "Supermarkt")
    with pytest.raises(ValueError):
        categorization.rename_category(conn, _cat(conn, "Sport abonnement")["id"], " ")
    with pytest.raises(KeyError):
        categorization.rename_category(conn, 99999, "Iets")


def test_a_later_default_rule_follows_your_name(conn):
    """New default rules point to the renamed category, even after renaming twice."""
    categorization.rename_category(conn, _cat(conn, "Overige inkomsten")["id"], "Extra")
    categorization.rename_category(conn, _cat(conn, "Extra")["id"], "Extra inkomsten")
    for rule in categorization.RULES_SINCE[2]:
        conn.execute("DELETE FROM rules WHERE field = ? AND pattern = ?", rule[1:3])
    conn.execute("DELETE FROM settings WHERE key = 'default_rules_version'")
    conn.commit()
    categorization.seed(conn)
    payday = next(r for r in categorization.load_rules(conn) if r["pattern"] == "BUNQ PAYDAY")
    assert payday["category"] == "Extra inkomsten"
