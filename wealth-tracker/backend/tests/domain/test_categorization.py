"""
Tests for categorization.py — the labelling engine.

This engine was not invented anew: it was ported from the existing bookkeeping
(financien/migratie/rules.py), where it labelled the vast majority of the
transactions over a long history. The sharpest test we have is therefore not
a made-up case but **parity**: does the ported engine give exactly the same
category as the original on that same history?

That test needs your own transaction file and skips itself if you do not have
it:

    FINANCIEN_CLASSIFIED=~/personal/financien/data/tx_classified.json pytest

The rest below pins down the rules you can explain about the engine without
looking at the data: which rule wins, what INTERNAL is, and that a manual
judgement is never overwritten by a rule round.

Sign convention, everywhere in this file: **spending positive, income negative.**
"""

import importlib.util
import json
import os
import sqlite3

import pytest

from domain import database
from domain.money import accounts, bank_transactions, categorization


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


def _conn(username: str = "alice") -> sqlite3.Connection:
    conn = database.connect(username)
    database.init_db(conn)
    categorization.seed(conn)
    return conn


def _label(conn, name, description="", counterparty_iban=None, amount=10.0, own=()):
    return categorization.label(
        categorization.load_rules(conn),
        name=name,
        description=description,
        counterparty_iban=counterparty_iban,
        amount=amount,
        own_ibans=set(own),
    )[0]


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def test_seeding_sets_up_the_taxonomy_and_the_rules():
    conn = _conn()
    assert len(categorization.load_categories(conn)) == len(categorization.DEFAULT_CATEGORIES)
    assert len(categorization.load_rules(conn)) == len(categorization.DEFAULT_RULES)
    conn.close()


def test_seeding_does_not_overwrite_your_own_changes():
    """Seeding happens on every init; a deleted rule must stay deleted."""
    conn = _conn()
    rules = categorization.load_rules(conn)
    categorization.delete_rule(conn, rules[0]["id"])

    categorization.seed(conn)
    assert len(categorization.load_rules(conn)) == len(rules) - 1
    conn.close()


def test_every_rule_points_to_an_existing_category():
    """A rule that points to a category that does not exist labels to nothing."""
    names = {c["name"] for c in categorization.DEFAULT_CATEGORIES_IF_DICTS}
    referred = {r[4] for r in categorization.DEFAULT_RULES}
    assert referred <= names, f"onbekende categorie in een regel: {referred - names}"


# ---------------------------------------------------------------------------
# Which rule wins
# ---------------------------------------------------------------------------


def test_lower_priority_wins():
    """INTERNAL is at 10 so a savings transfer never becomes an expense."""
    conn = _conn()
    # "SPAARREKENING" falls under INTERNAL (priority 10); without that precedence a
    # name like this could land in a spending category further down.
    assert _label(conn, "ORANJE SPAARREKENING") == "Naar spaarrekening"
    conn.close()


def test_direction_separates_paid_from_received():
    """The same counterparty, a different sign, a different category."""
    conn = _conn()
    assert _label(conn, "IEMAND", "TIKKIE van Jan", amount=10.0) == "Betaald aan vrienden"
    assert _label(conn, "IEMAND", "TIKKIE van Jan", amount=-10.0) == "Ontvangen van vrienden"
    conn.close()


def test_unknown_when_nothing_matches():
    conn = _conn()
    assert _label(conn, "IETS VOLSTREKT ONHERKENBAARS 12345") == categorization.UNKNOWN
    conn.close()


# ---------------------------------------------------------------------------
# The fields N / T / A / P
# ---------------------------------------------------------------------------


def test_a_personal_name_is_recognised_as_a_friend():
    """Two to four words, no digits, no company suffix."""
    conn = _conn()
    assert _label(conn, "JAN DE VRIES", amount=10.0) == "Betaald aan vrienden"
    conn.close()


def test_a_company_is_not_a_person():
    conn = _conn()
    assert _label(conn, "VRIES TRANSPORT B.V.", amount=10.0) != "Betaald aan vrienden"
    conn.close()


def test_a_name_with_digits_is_not_a_person():
    conn = _conn()
    assert _label(conn, "TERMINAL 4471 NL", amount=10.0) != "Betaald aan vrienden"
    conn.close()


def test_a_payment_processor_looks_at_the_description():
    """With Buckaroo or Mollie the real shop is in the description, not in the name."""
    conn = _conn()
    assert _label(conn, "BUCKAROO B.V.", "ALBERT HEIJN 1234") == "Supermarkt"
    conn.close()


def test_a_payment_processor_without_a_usable_description_stays_unknown():
    conn = _conn()
    assert _label(conn, "MOLLIE B.V.", "referentie 99887766") == categorization.UNKNOWN
    conn.close()


# ---------------------------------------------------------------------------
# Own accounts
# ---------------------------------------------------------------------------


def test_a_transfer_to_your_own_account_is_internal():
    """Money to your own account is not an expense, even when it shows as a debit in
    your bank export.
    """
    conn = _conn()
    assert (
        _label(conn, "J DE VRIES", counterparty_iban="NL00BUNQ0000000002", amount=500.0, own={"NL00BUNQ0000000002"}) == "Eigen rekeningen"
    )
    conn.close()


def test_the_same_transfer_without_an_own_iban_is_not_internal():
    conn = _conn()
    assert _label(conn, "J DE VRIES", counterparty_iban="NL00BUNQ0000000002", amount=500.0, own=set()) != "Eigen rekeningen"
    conn.close()


def test_own_ibans_come_from_the_accounts():
    """They are not in the code and not in a separate file, but in your accounts."""
    conn = _conn()
    accounts.make_bank_account(conn, kind="bank", provider="bunq", name="bunq", iban="NL00 BUNQ 0000 0000 02")
    assert categorization.own_ibans(conn) == {"NL00BUNQ0000000002"}
    conn.close()


# ---------------------------------------------------------------------------
# Herlabelen
# ---------------------------------------------------------------------------


def _save(conn, name, description="", amount=10.0, hash_="a" * 16):
    account_id = accounts.search_on_iban(conn, "NL00INGB0000000001")
    if account_id is None:
        account_id = accounts.make_bank_account(conn, kind="bank", provider="ing", name="ING", iban="NL00INGB0000000001")
    else:
        account_id = account_id["id"]
    # Every row its own day, derived from the hash. save() sees two rows with the
    # same date and the same amount as the same booking from another source (an
    # export next to the bank connection); these tests are about labelling, not
    # about merging, and store their rows one by one.
    bank_transactions.save(
        conn,
        account_id,
        [
            {
                "date": f"2026-02-{1 + ord(hash_[0]) % 28:02d}",
                "interest_date": None,
                "amount": amount,
                "currency": "EUR",
                "name": name,
                "counterparty_iban": None,
                "description": description,
                "code": None,
                "kind": None,
                "dedup_hash": hash_,
                "raw": {},
            }
        ],
    )


def test_relabelling_fills_the_automatic_category_and_the_type():
    conn = _conn()
    _save(conn, "ALBERT HEIJN 1234")

    report = categorization.relabel(conn)
    assert report["labelled"] == 1

    row = bank_transactions.load(conn)[0]
    assert row["category_auto"] == "Supermarkt"
    assert row["category"] == "Supermarkt"
    assert row["type"] == "EXPENSE"
    conn.close()


def test_internal_gets_the_type_internal():
    """Everything hangs on this: INTERNAL counts nowhere in budget or savings rate."""
    conn = _conn()
    _save(conn, "ORANJE SPAARREKENING", amount=500.0)
    categorization.relabel(conn)
    assert bank_transactions.load(conn)[0]["type"] == "INTERNAL"
    conn.close()


def test_relabelling_never_touches_a_manual_category():
    """The whole point of three columns: automatic where possible, your judgement
    where needed — and a rule change must not erase that judgement.
    """
    conn = _conn()
    _save(conn, "ALBERT HEIJN 1234")
    row_id = bank_transactions.load(conn)[0]["id"]
    bank_transactions.set_category_manual(conn, row_id, "Cadeaus & goede doelen")

    categorization.relabel(conn, everything=True)

    row = bank_transactions.load(conn)[0]
    assert row["category_auto"] == "Supermarkt", "auto mag wel bijgewerkt worden"
    assert row["category"] == "Cadeaus & goede doelen", "handmatig wint"
    conn.close()


def test_relabelling_skips_already_labelled_rows_by_default():
    conn = _conn()
    _save(conn, "ALBERT HEIJN 1234")
    assert categorization.relabel(conn)["labelled"] == 1
    assert categorization.relabel(conn)["labelled"] == 0
    assert categorization.relabel(conn, everything=True)["labelled"] == 1
    conn.close()


def test_a_new_rule_labels_the_history_too():
    """Adding a category in the frontend must work back on what is already there."""
    conn = _conn()
    # With a digit in it, otherwise the personal name heuristic already catches it.
    _save(conn, "OPPASDIENST 4471")
    categorization.relabel(conn)
    assert bank_transactions.load(conn)[0]["category"] == categorization.UNKNOWN

    categorization.make_category(conn, group_name="Wonen", name="Oppas", type="EXPENSE")
    categorization.make_rule(conn, priority=25, field="N", pattern=r"OPPASDIENST", direction="", category="Oppas")
    assert categorization.relabel(conn, everything=True)["labelled"] == 1
    assert bank_transactions.load(conn)[0]["category"] == "Oppas"
    conn.close()


def test_the_report_counts_how_many_stayed_unknown():
    conn = _conn()
    _save(conn, "ALBERT HEIJN 1234", hash_="a" * 16)
    _save(conn, "ONHERKENBAAR 99999", hash_="b" * 16)

    report = categorization.relabel(conn)
    assert report["labelled"] == 2
    assert report["unknown"] == 1
    assert report["coverage"] == pytest.approx(50.0)
    conn.close()


# ---------------------------------------------------------------------------
# Parity with the existing bookkeeping
# ---------------------------------------------------------------------------


def test_the_ported_engine_gives_the_same_answers():
    """The sharpest test there is: the same history, the same outcome.

    If this is green, the port is demonstrably correct — the same trick with which
    rules.py and Financien.gs were run against each other back then.
    """
    path = os.environ.get("FINANCES_CLASSIFIED")
    if not path or not os.path.exists(path):
        pytest.skip("FINANCIEN_CLASSIFIED niet gezet — zie de moduledocstring")

    rows = json.loads(open(path, encoding="utf-8").read())
    own = set(json.loads(open(os.path.join(os.path.dirname(path), "eigen_rekeningen.json"), encoding="utf-8").read())["ibans"])

    # Parity of the *engine*, with the original's rules. The default rules in
    # categorization.py are deliberately more general — no employer, no landlord, no
    # regular pub — and so would not label identically here. That is also not what
    # this test proves.
    rules_path = os.environ.get("FINANCES_RULES") or os.path.join(os.path.dirname(os.path.dirname(path)), "migration", "rules.py")
    spec = importlib.util.spec_from_file_location("original", rules_path)
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    rules = sorted(
        (
            {"priority": p_, "field": v, "pattern": pat, "direction": r, "category": cat}
            for p_, v, pat, r, cat in original.R
            if cat != "Eigen rekeningen"
        ),
        key=lambda x: x["priority"],
    )
    conn = _conn()

    deviations = []
    for row in rows:
        # The old setup passed the counterparty as text in the notes field; our T rule
        # appends it the same way.
        got, _ = categorization.label(
            rules,
            name=row["name"] or "",
            description=row["note"] or "",
            counterparty_iban=row["counterparty"] or None,
            amount=float(row["amount"]),
            own_ibans=own,
        )
        if got != row["cat_new"]:
            deviations.append((row["name"], row["cat_new"], got))

    assert not deviations, f"{len(deviations)} van {len(rows)} anders gelabeld; eerste vijf: {deviations[:5]}"
    conn.close()


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


def test_money_received_counts_as_income_not_as_spending():
    """In the original these two were EXPENSE.

    Because of that received money counted with a minus sign in the spending
    total, which could therefore go negative.
    """
    types = {n: t for _g, n, t in categorization.DEFAULT_CATEGORIES}
    assert types["Ontvangen van vrienden"] == "INCOME"
    assert types["Huur ontvangen huisgenoten"] == "INCOME"


def test_every_category_has_a_valid_type():
    for group_name, name, type_ in categorization.DEFAULT_CATEGORIES:
        assert type_ in categorization.TYPES, f"{name} heeft type {type_!r}"


def test_a_spending_category_gets_no_income_type_when_relabelling():
    """The type comes from the taxonomy, not from the sign of the amount."""
    conn = _conn()
    _save(conn, "ALBERT HEIJN 1234", amount=-5.0)  # a refund
    categorization.relabel(conn)
    row = bank_transactions.load(conn)[0]
    assert row["category"] == "Supermarkt"
    assert row["type"] == "EXPENSE"
    conn.close()


def test_a_lowercase_pattern_works_too():
    """The engine turns the name into capitals, so a pattern in lowercase would never
    match.

    That is exactly what happened with "Make a rule from this": it takes over the
    counterparty's name literally, and at bunq that is "bunq". The rule was
    created neatly, looked fine in the list, and did not label fourteen
    transactions. Silently doing nothing is the worst outcome here.
    """
    conn = _conn()
    categorization.make_category(conn, group_name="Inkomsten", name="Rente", type="INCOME")
    categorization.make_rule(conn, priority=25, field="N", pattern="bunq", direction="", category="Rente")

    assert _label(conn, "bunq", amount=-1.50) == "Rente"
    assert _label(conn, "BUNQ", amount=-1.50) == "Rente"
    assert _label(conn, "Bunq Payday", amount=-1.50) == "Rente"
    conn.close()


def test_a_rule_from_a_transaction_labels_the_others_with_the_same_name():
    """The whole loop: one correction, and the rest of that counterparty moves along."""
    conn = _conn()
    for i, name in enumerate(["bunq", "bunq", "ALBERT HEIJN 1"]):
        _save(conn, name, amount=-1.50 if name == "bunq" else 10.0, hash_=f"{i}" * 16)
    categorization.relabel(conn)
    assert sum(1 for r in bank_transactions.load(conn) if r["category"] == categorization.UNKNOWN) == 2

    categorization.make_category(conn, group_name="Inkomsten", name="Rente", type="INCOME")
    categorization.make_rule(conn, priority=25, field="N", pattern="BUNQ", direction="", category="Rente")
    categorization.relabel(conn, everything=True)

    rows = bank_transactions.load(conn)
    assert sum(1 for r in rows if r["category"] == "Rente") == 2
    assert sum(1 for r in rows if r["category"] == "Supermarkt") == 1
    conn.close()


def test_an_unknown_income_does_not_count_as_spending():
    """The taxonomy puts Onbekend on EXPENSE, so an unrecognised deposit landed with
    a minus sign in the spending total and pulled it down.

    The same mistake as "Ontvangen van vrienden" on EXPENSE, but then for
    everything that has no rule yet — and that is exactly what you have most of
    at the start.
    """
    conn = _conn()
    _save(conn, "ONHERKENBARE STORTING 99", amount=-3000.0, hash_="a" * 16)
    _save(conn, "ONHERKENBARE WINKEL 99", amount=100.0, hash_="b" * 16)
    categorization.relabel(conn)

    on_name = {r["name"]: r for r in bank_transactions.load(conn)}
    assert on_name["ONHERKENBARE STORTING 99"]["category"] == categorization.UNKNOWN
    assert on_name["ONHERKENBARE STORTING 99"]["type"] == "INCOME"
    assert on_name["ONHERKENBARE WINKEL 99"]["type"] == "EXPENSE"
    conn.close()


def test_a_refund_in_a_known_category_stays_spending():
    """Only Onbekend follows the sign. For the rest the type *is* the agreement:
    money back from the supermarket belongs under Boodschappen, not under income.
    """
    conn = _conn()
    _save(conn, "ALBERT HEIJN 1234", amount=-5.0)
    categorization.relabel(conn)
    row = bank_transactions.load(conn)[0]
    assert row["category"] == "Supermarkt"
    assert row["type"] == "EXPENSE"
    conn.close()


# ---------------------------------------------------------------------------
# The type follows the category you see
# ---------------------------------------------------------------------------


def test_a_manual_category_also_changes_where_it_counts():
    """The core of the correction loop, and it was broken.

    A grocery that was actually a transfer to your savings account you correct by
    hand — and then it must disappear from the spending total. That did not
    happen: the type stuck at what the rules found, even after "relabel
    everything", because relabelling took the type from the automatic category and
    not from the category you see.
    """
    conn = _conn()
    _save(conn, "ALBERT HEIJN 1234", amount=500.0)
    categorization.relabel(conn)
    row_id = bank_transactions.load(conn)[0]["id"]
    assert bank_transactions.load(conn)[0]["type"] == "EXPENSE"

    bank_transactions.set_category_manual(conn, row_id, "Naar spaarrekening")
    assert bank_transactions.load(conn)[0]["type"] == "INTERNAL", "meteen, zonder herlabelen"

    categorization.relabel(conn, everything=True)
    assert bank_transactions.load(conn)[0]["type"] == "INTERNAL", "en ook na een regelronde"
    conn.close()


def test_undoing_a_correction_also_restores_the_type():
    conn = _conn()
    _save(conn, "ALBERT HEIJN 1234", amount=500.0)
    categorization.relabel(conn)
    row_id = bank_transactions.load(conn)[0]["id"]

    bank_transactions.set_category_manual(conn, row_id, "Naar spaarrekening")
    bank_transactions.set_category_manual(conn, row_id, None)
    assert bank_transactions.load(conn)[0]["type"] == "EXPENSE"
    conn.close()


def test_changing_a_categorys_type_takes_effect_at_once():
    """If you change a category in the taxonomy, the history moves along — without
    anything having to be relabelled first.
    """
    conn = _conn()
    _save(conn, "ALBERT HEIJN 1234", amount=500.0)
    categorization.relabel(conn)

    conn.cursor().execute("UPDATE categories SET type = 'INTERNAL' WHERE name = 'Supermarkt'")
    conn.commit()
    assert bank_transactions.load(conn)[0]["type"] == "INTERNAL"
    conn.close()


def test_a_category_that_no_longer_exists_counts_by_direction():
    """A deleted category is an unknown category: then the direction decides, as
    with Onbekend — and not "counts nowhere".
    """
    conn = _conn()
    _save(conn, "ALBERT HEIJN 1234", amount=500.0, hash_="a" * 16)
    _save(conn, "ALBERT HEIJN 1234", amount=-20.0, hash_="b" * 16)
    categorization.relabel(conn)
    conn.cursor().execute("DELETE FROM categories WHERE name = 'Supermarkt'")
    conn.commit()

    on_amount = {r["amount"]: r["type"] for r in bank_transactions.load(conn)}
    assert on_amount[500.0] == "EXPENSE"
    assert on_amount[-20.0] == "INCOME"
    conn.close()


def test_unlabelled_counts_nowhere_yet():
    """Without a category there is no type either; such a row must not silently end
    up in a total. The import labels straight away, so in practice this is only
    the moment in between.
    """
    conn = _conn()
    _save(conn, "ALBERT HEIJN 1234", amount=500.0)
    assert bank_transactions.load(conn)[0]["type"] is None
    conn.close()
