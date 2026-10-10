"""
Smarter labelling: what the money was for, own accounts in the description, and
rules that do nothing.

The trigger: under Vrienden & delen there were transfers to the user's own
savings account, student finance, a payslip, the water bill and Tikkies for a
hotel. A Tikkie is a way of paying, not a category: the description says where
the money went.

Sign convention: spending positive, income negative.
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


def _label(conn, name, description="", amount=10.0, **kw):
    return categorization.label(categorization.load_rules(conn), name=name,
                               description=description, amount=amount, **kw)[0]


def _category(conn, tid):
    return next(r for r in bank_transactions.load(conn) if r["id"] == tid)["category"]


def _rule(conn, pattern, category, priority=25):
    conn.execute("INSERT INTO rules (priority, field, pattern, direction, category) VALUES (?, 'N', ?, '', ?)",
                 (priority, pattern, category))
    conn.commit()


# ---------------------------------------------------------------------------
# What the money was for
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("description, category", [
    ("Tikkie ID 000123, Hotel retour, Van A. Voorbeeld", "Vakantie"),
    ("Tikkie ID 000124, Ubers drankjes", "Cafe & uitgaan"),
    ("Tickets Dekmantel selectors", "Uitjes & evenementen"),
    ("Sint cadeau Guus", "Cadeaus & goede doelen"),
    ("Ov naar rotterdam", "Openbaar vervoer"),
    ("Pizza vrijdag", "Uit eten & bezorgen"),
    ("Zeilvakantie aanbetaling", "Vakantie"),
])
def test_a_tikkie_counts_under_what_it_was_for(conn, description, category):
    assert _label(conn, "Tikkie", description) == category
    # What a friend pays you back comes off that same expense.
    assert _label(conn, "A. VOORBEELD", description, amount=-10.0) == category


def test_without_a_target_it_stays_friends(conn):
    assert _label(conn, "Tikkie", "Tikkie ID 000125, Van A. Voorbeeld") == "Betaald aan vrienden"
    assert _label(conn, "A. VOORBEELD", "Terugbetaling", amount=-10.0) == "Ontvangen van vrienden"


def test_a_shop_name_comes_before_the_description(conn):
    assert _label(conn, "ALBERT HEIJN 1234", "lunch") == "Supermarkt"


def test_a_refund_at_the_till_stays_with_the_shop(conn):
    """ING sometimes calls a refund at the till cashback; that is not income."""
    assert _label(conn, "ALBERT HEIJN 1852 DELFT", "Card sequence no.: 900 Cashback",
                  amount=-20.0) == "Supermarkt"
    assert _label(conn, "Cashback XL B.V.", "Uitbetaling", amount=-4.0) == "Overige inkomsten"


def test_an_old_tikkie_via_abn_amro_is_friends(conn):
    description = "000123456789 0030000000000001 Kempen NL00ABNA0000000017"
    assert _label(conn, "ABN AMRO Bank NV", description) == "Betaald aan vrienden"


# ---------------------------------------------------------------------------
# Who is a person, and what is a company
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Trendhim ApS", "DELFTSCHE STUDENTEN SOCI", "EVIDES WATERBEDRIJF", "ING Punten"])
def test_a_company_is_not_a_friend(conn, name):
    assert _label(conn, name) not in ("Betaald aan vrienden", "Ontvangen van vrienden")


def test_a_person_stays_a_person():
    assert categorization.is_person("JAN DE VRIES")


def test_student_finance_and_a_payslip(conn):
    assert _label(conn, "DUO Hoofdrekening", "Maandbetaling Studiefinanciering", amount=-1069.0) == "Studiefinanciering"
    assert _label(conn, "FLEXDELFT B V", "Betreft loonslipnummer 5", amount=-79.0) == "Salaris"
    # A loan is not earned: internal, like a gift.
    student_finance = next(c for c in categorization.load_categories(conn) if c["name"] == "Studiefinanciering")
    assert student_finance["type"] == "INTERNAL"


def test_paying_abroad_is_holiday(conn):
    assert _label(conn, "7 MART 5", "7 MART 5 Lombok Utara, ID\n25000.00 IDR, 1 IDR = 0.00005 EUR") == "Vakantie"
    assert _label(conn, "R12002 KCP PRAYA SUDIR IDN") == "Vakantie"
    # Dollars are often an online service, and Ireland is where Revolut invoices from.
    assert _label(conn, "SOMEAPP.COM", "9.99 USD, 1 USD = 0.92 EUR") == categorization.UNKNOWN
    assert _label(conn, "Revolut**4512* Dublin IRL") != "Vakantie"


# ---------------------------------------------------------------------------
# Own accounts in the description
# ---------------------------------------------------------------------------

def test_your_savings_account_in_the_description_is_an_own_account(conn):
    """For a savings transfer ING puts down your own name, not an IBAN. The account
    number of the savings account is in the description, though.
    """
    pay = accounts.make_bank_account(conn, kind="bank", provider="ing", name="ING")
    savings = accounts.make_bank_account(conn, kind="bank", provider="ing", name="Spaar")
    conn.execute("UPDATE accounts SET external_id = 'D12345678' WHERE id = ?", (savings,))
    conn.commit()
    dest = bank_transactions.add_manually(conn, account_id=pay, date="2026-01-25", amount=700.0,
                                              name="Hr J de Vries", description="To Oranje spaarrekening D12345678")
    interest = bank_transactions.add_manually(conn, account_id=savings, date="2026-01-31", amount=-3.0,
                                               name="Rente", description="Rente D12345678")
    categorization.relabel(conn)
    assert _category(conn, dest) == "Eigen rekeningen"
    # On the savings account itself its own number says nothing.
    assert _category(conn, interest) == "Overige inkomsten"


def test_even_without_the_savings_account_it_is_saving_not_a_friend(conn):
    assert _label(conn, "Hr J de Vries", "To Oranje spaarrekening D99999999") == "Naar spaarrekening"


# ---------------------------------------------------------------------------
# Rules that do nothing
# ---------------------------------------------------------------------------

def test_a_rule_to_unknown_no_longer_holds_anything_back(conn):
    _rule(conn, "STICHTING MOLLIE PAYMENTS", categorization.UNKNOWN)
    assert _label(conn, "TRAVELBASE APP via Stichting Mollie Payments") == "Vakantie"


def test_clean_up_removes_unknown_and_duplicate_rules(conn):
    before = len(categorization.load_rules(conn, only_active=False))
    _rule(conn, "A\\.VAN VOORBEELD", "Zorgkosten")
    _rule(conn, "A\\.VAN VOORBEELD", "Zorgkosten")
    _rule(conn, "MOLLIE", categorization.UNKNOWN)
    assert categorization.clean_up_rules(conn) == 2
    assert len(categorization.load_rules(conn, only_active=False)) == before + 1


def test_a_new_rule_to_unknown_or_duplicate_is_not_allowed(conn):
    with pytest.raises(ValueError):
        categorization.make_rule(conn, priority=25, field="N", pattern="X", direction="", category=categorization.UNKNOWN)
    first = categorization.make_rule(conn, priority=25, field="N", pattern="SMIT", direction="", category="Vakantie")
    assert categorization.make_rule(conn, priority=30, field="N", pattern="SMIT", direction="", category="Vakantie") == first


# ---------------------------------------------------------------------------
# Who was already a user
# ---------------------------------------------------------------------------

def test_who_had_version_4_gets_everything_relabelled_once(conn):
    for rule in categorization.RULES_SINCE[5]:
        conn.execute("DELETE FROM rules WHERE field=? AND pattern=? AND direction=? AND category=?", rule[1:])
    conn.execute("DELETE FROM categories WHERE name = 'Studiefinanciering'")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('default_rules_version', '4')")
    conn.commit()
    _rule(conn, "MOLLIE", categorization.UNKNOWN)
    rid = accounts.make_bank_account(conn, kind="bank", provider="ing", name="ING")
    hotel = bank_transactions.add_manually(conn, account_id=rid, date="2026-02-01", amount=-50.0,
                                               name="Tikkie", description="Tikkie ID 1, Hotel retour")
    own = bank_transactions.add_manually(conn, account_id=rid, date="2026-02-02", amount=-60.0,
                                              name="Tikkie", description="Tikkie ID 1, Hotel retour 2")
    bank_transactions.set_category_manual(conn, own, "Niet meetellen")
    categorization.relabel(conn)
    assert _category(conn, hotel) == "Ontvangen van vrienden"

    categorization.seed(conn)
    assert _category(conn, hotel) == "Vakantie"
    assert _category(conn, own) == "Niet meetellen", "wat je met de hand zette blijft staan"
    assert not any(r["category"] == categorization.UNKNOWN for r in categorization.load_rules(conn, only_active=False))
    assert any(c["name"] == "Studiefinanciering" for c in categorization.load_categories(conn))
