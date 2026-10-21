"""
After the rules: learning from your own labels, and then Claude.

The order of certainty: your choice, then the rules, then what you already did
yourself for the same counterparty, and only then a suggestion from Claude —
only if it may help and is certain enough. Claude itself is never called here:
the call is replaced by a fake that says what the test wants.
"""

import pytest

from domain import database, preferences
from domain.money import accounts, ai_labelling, bank_transactions, categorization


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


@pytest.fixture()
def rid(conn):
    return accounts.make_bank_account(conn, kind="bank", provider="manual", name="Bank")


_counter = iter(range(1, 10_000))


def _tx(conn, rid, name, description="", amount=10.0, iban=None):
    n = next(_counter)
    bank_transactions.save(
        conn,
        rid,
        [
            {
                "date": f"2026-03-{n % 28 + 1:02d}",
                "interest_date": None,
                "amount": amount,
                "currency": "EUR",
                "name": name,
                "counterparty_iban": iban,
                "description": description,
                "code": None,
                "kind": None,
                "dedup_hash": f"tx{n}",
                "raw": {},
            }
        ],
    )
    return conn.execute("SELECT MAX(id) FROM bank_transactions").fetchone()[0]


def _row(conn, tid):
    return next(r for r in bank_transactions.load(conn) if r["id"] == tid)


# ---------------------------------------------------------------------------
# Learning from your own labels
# ---------------------------------------------------------------------------


def test_an_own_label_teaches_the_rest_of_that_counterparty(conn, rid):
    first, second = _tx(conn, rid, "Sissi's"), _tx(conn, rid, "Sissi's")
    categorization.relabel(conn)
    assert _row(conn, second)["category"] == categorization.UNKNOWN

    bank_transactions.set_category_manual(conn, first, "Cafe & uitgaan")
    categorization.relabel(conn)
    row = _row(conn, second)
    assert row["category"] == "Cafe & uitgaan" and row["category_source"] == "learned"


def test_branch_number_and_country_code_do_not_count(conn, rid):
    first = _tx(conn, rid, "Tiofli 1 AMSTERDAM NLD")
    second = _tx(conn, rid, "Tiofli 2 AMSTERDAM NLD")
    bank_transactions.set_category_manual(conn, first, "Cafe & uitgaan")
    categorization.relabel(conn)
    assert _row(conn, second)["category"] == "Cafe & uitgaan"


def test_a_friend_becomes_something_else_only_after_three_times_the_same(conn, rid):
    iban = "NL00INGB0000000077"
    ids = [_tx(conn, rid, "JAN DE VRIES", iban=iban) for _ in range(4)]
    bank_transactions.set_category_manual(conn, ids[0], "Huur")
    categorization.relabel(conn)
    assert _row(conn, ids[3])["category"] == "Betaald aan vrienden", "één keer zegt niets"

    for tid in ids[1:3]:
        bank_transactions.set_category_manual(conn, tid, "Huur")
    categorization.relabel(conn)
    assert _row(conn, ids[3])["category"] == "Huur"


def test_a_tikkie_teaches_nothing_about_the_next(conn, rid):
    first = _tx(conn, rid, "Tikkie", "Tikkie ID 1, Van A. Voorbeeld")
    second = _tx(conn, rid, "Tikkie", "Tikkie ID 2, Van B. Voorbeeld")
    bank_transactions.set_category_manual(conn, first, "Vakantie")
    categorization.relabel(conn)
    assert _row(conn, second)["category"] == "Betaald aan vrienden"


def test_exclude_is_one_off_and_does_not_teach(conn, rid):
    first, second = _tx(conn, rid, "Onbekende Zaak 99"), _tx(conn, rid, "Onbekende Zaak 99")
    bank_transactions.set_category_manual(conn, first, categorization.EXCLUDE)
    categorization.relabel(conn)
    assert _row(conn, second)["category"] == categorization.UNKNOWN


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------


@pytest.fixture()
def claude(conn, monkeypatch):
    """Claude may help, and answers what the test puts in `answers`."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    preferences.put(conn, "ai_labelling", {"on": True})
    fake = {"asked": [], "answers": {}}

    def _ask(items, categories, **_):
        fake["asked"].extend(i["id"] for i in items)
        return [{"id": i["id"], "category": c, "confidence": z} for i in items if (c_z := fake["answers"].get(i["id"])) for c, z in [c_z]]

    monkeypatch.setattr(ai_labelling, "_ask_claude", _ask)
    return fake


def test_without_key_or_consent_nothing_goes_out(conn, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ai_labelling.AiError):
        ai_labelling.analyse(conn)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    with pytest.raises(ai_labelling.AiError):
        ai_labelling.analyse(conn)  # not turned on yet


def test_claude_labels_what_is_open_when_it_is_sure(conn, rid, claude):
    sure = _tx(conn, rid, "Undercurrent AMSTERDAM NLD")
    doubt = _tx(conn, rid, "Borisov Amsterdam NLD")
    shop = _tx(conn, rid, "ALBERT HEIJN 1234")
    categorization.relabel(conn)
    claude["answers"] = {sure: ("Cafe & uitgaan", 0.92), doubt: ("Uit eten & bezorgen", 0.5)}

    ai_labelling.analyse(conn)
    assert shop not in claude["asked"], "wat een regel weet gaat niet naar buiten"
    assert _row(conn, sure)["category"] == "Cafe & uitgaan" and _row(conn, sure)["category_source"] == "ai"
    assert _row(conn, doubt)["category"] == categorization.UNKNOWN
    assert [t["id"] for t in ai_labelling.by_ai(conn)] == [sure]

    claude["asked"].clear()
    ai_labelling.analyse(conn)
    assert claude["asked"] == [], "elke transactie maar één keer"


def test_turning_it_off_removes_its_labels_again(conn, rid, claude):
    tid = _tx(conn, rid, "Undercurrent AMSTERDAM NLD")
    claude["answers"] = {tid: ("Cafe & uitgaan", 0.95)}
    ai_labelling.analyse(conn)
    preferences.put(conn, "ai_labelling", {"on": False})
    categorization.relabel(conn, everything=True)
    assert _row(conn, tid)["category"] == categorization.UNKNOWN


def test_a_rule_and_an_own_label_come_before_claude(conn, rid, claude):
    own, learned = _tx(conn, rid, "Moonflower"), _tx(conn, rid, "Moonflower")
    bank_transactions.set_category_manual(conn, own, "Sport & hobby")
    categorization.relabel(conn)
    claude["answers"] = {learned: ("Cafe & uitgaan", 0.99)}
    ai_labelling.analyse(conn)
    assert _row(conn, own)["category"] == "Sport & hobby"
    assert _row(conn, learned)["category"] == "Sport & hobby"


def test_for_friends_without_a_target_claude_may_suggest_something_better(conn, rid, claude):
    tid = _tx(conn, rid, "JAN DE VRIES", "voor zaterdag")
    categorization.relabel(conn)
    assert _row(conn, tid)["category"] == "Betaald aan vrienden"
    claude["answers"] = {tid: ("Uitjes & evenementen", 0.85)}
    ai_labelling.analyse(conn)
    assert _row(conn, tid)["category"] == "Uitjes & evenementen"


def test_numbers_are_removed_before_sending():
    ing = ai_labelling.mask("Name: Smit Description: lustrum IBAN: NL00ABNA0000000063 Value date: 24/10/2023")
    assert "NL63" not in ing and "0844327875" not in ing and "24/10" not in ing
    assert "Smit" in ing and "lustrum" in ing
    card = ai_labelling.mask("Card sequence no.: 900 26/06/2024 12:08 Transaction: W00082 Term: 9DHT")
    assert "W00082" not in card and "9DHT" not in card
    assert "Studiefinanciering" in ai_labelling.mask("Maandbetaling Studiefinanciering 2000000000000001")
    assert "2000000000000001" not in ai_labelling.mask("Maandbetaling Studiefinanciering 2000000000000001")


# ---------------------------------------------------------------------------
# Check everything
# ---------------------------------------------------------------------------


def _supermarket_that_food_is(conn, rid, claude, n=3):
    ids = [_tx(conn, rid, "ALBERT HEIJN 1234") for _ in range(n)]
    categorization.relabel(conn)
    claude["answers"] = {i: ("Uit eten & bezorgen", 0.9) for i in ids}
    ai_labelling.verify(conn)
    return ids


def test_checking_asks_equal_counterparties_once_and_changes_nothing(conn, rid, claude):
    netflix = _tx(conn, rid, "NETFLIX.COM")
    open_ = _tx(conn, rid, "Moonflower 9")
    own = _tx(conn, rid, "ALBERT HEIJN 9999")
    bank_transactions.set_category_manual(conn, own, "Supermarkt")
    claude["answers"] = {netflix: ("Media & software", 0.95)}
    ah = _supermarket_that_food_is(conn, rid, claude)

    assert len(claude["asked"]) == 2, "drie keer dezelfde supermarkt is één vraag"
    assert open_ not in claude["asked"] and own not in claude["asked"]
    [a] = ai_labelling.deviations(conn)
    assert (a["now"], a["suggestion"], sorted(a["ids"])) == ("Supermarkt", "Uit eten & bezorgen", sorted(ah))
    assert all(_row(conn, i)["category"] == "Supermarkt" for i in ah), "niets vanzelf"

    claude["asked"].clear()
    ai_labelling.verify(conn)
    assert claude["asked"] == []


def test_the_suggestion_as_a_rule_also_applies_to_what_is_still_coming(conn, rid, claude):
    _supermarket_that_food_is(conn, rid, claude)
    [a] = ai_labelling.deviations(conn)
    ai_labelling.decision(conn, ids=a["ids"], choice="suggestion", category=a["suggestion"], rule=True)
    assert all(_row(conn, i)["category"] == "Uit eten & bezorgen" and _row(conn, i)["category_manual"] is None for i in a["ids"])
    assert ai_labelling.deviations(conn) == []
    new = _tx(conn, rid, "ALBERT HEIJN 1234")
    categorization.relabel(conn)
    assert _row(conn, new)["category"] == "Uit eten & bezorgen"


def test_the_original_is_right_leaves_everything(conn, rid, claude):
    _supermarket_that_food_is(conn, rid, claude)
    [a] = ai_labelling.deviations(conn)
    ai_labelling.decision(conn, ids=a["ids"], choice="original")
    assert all(_row(conn, i)["category"] == "Supermarkt" and _row(conn, i)["category_manual"] is None for i in a["ids"])
    assert ai_labelling.deviations(conn) == []


def test_something_else_without_a_rule_is_an_own_label(conn, rid, claude):
    _supermarket_that_food_is(conn, rid, claude)
    [a] = ai_labelling.deviations(conn)
    ai_labelling.decision(conn, ids=a["ids"], choice="otherwise", category="Cadeaus & goede doelen")
    assert all(_row(conn, i)["category_manual"] == "Cadeaus & goede doelen" for i in a["ids"])
    with pytest.raises(ValueError):
        ai_labelling.decision(conn, ids=a["ids"], choice="misschien")


def test_without_a_key_its_labels_fall_back(conn, rid, claude, monkeypatch):
    tid = _tx(conn, rid, "Undercurrent AMSTERDAM NLD")
    claude["answers"] = {tid: ("Cafe & uitgaan", 0.95)}
    ai_labelling.analyse(conn)
    assert _row(conn, tid)["category_source"] == "ai"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    categorization.relabel(conn, everything=True)
    assert _row(conn, tid)["category"] == categorization.UNKNOWN
    assert ai_labelling.status(conn)["available"] is False


def test_claude_may_not_choose_anything_internal(conn, rid, claude):
    """A refund through a processor is not "exclude": that is your choice."""
    tid = _tx(conn, rid, "PPRO PAYMENT SERVICES SA", "REFUND", amount=-20.0)
    categorization.relabel(conn)
    claude["answers"] = {tid: (categorization.EXCLUDE, 0.95)}
    ai_labelling.analyse(conn)
    assert _row(conn, tid)["category"] == categorization.UNKNOWN


def test_a_tikkie_without_a_target_is_not_guessed(conn, rid, claude):
    tid = _tx(conn, rid, "de Groot via Tikkie", "001000000070 0031012345678901")
    categorization.relabel(conn)
    claude["answers"] = {tid: ("Cafe & uitgaan", 0.85)}
    ai_labelling.analyse(conn)
    assert tid not in claude["asked"]
    assert _row(conn, tid)["category"] == "Betaald aan vrienden"


@pytest.mark.parametrize(
    "name, description, expected",
    [
        ("GH DEKKER CJ", "Name: GH DEKKER CJ Description: Betaling van GH DEKKER CJ IBAN: NL55ABNA0123456789", False),
        ("de Groot via Tikkie", "Name: de Groot via Tikkie Description: 001000000070 0031012345678901", False),
        ("Hr T Mulder", "Name: Hr T Mulder Description: Tapas IBAN: NL07INGB0001234567", True),
    ],
)
def test_target_text(name, description, expected):
    assert categorization.has_target_text(name, description) is expected


# ---------------------------------------------------------------------------
# Regelvoorstellen
# ---------------------------------------------------------------------------


@pytest.fixture()
def patterns(claude, monkeypatch):
    """Claude comes up with patterns; `make` says which, per group."""
    fake = {"asked": 0, "make": lambda group_name: "TIOFLI"}

    def _ask(groups):
        fake["asked"] += len(groups)
        return [{"id": g["id"], "pattern": fake["make"](g)} for g in groups]

    monkeypatch.setattr(ai_labelling, "_ask_patterns", _ask)
    return fake


def _tiofli(conn, rid):
    a, b = _tx(conn, rid, "Tiofli 1 AMSTERDAM NLD"), _tx(conn, rid, "Tiofli 2 AMSTERDAM NLD")
    for tid in (a, b):
        bank_transactions.set_category_manual(conn, tid, "Cafe & uitgaan")
    categorization.relabel(conn)
    return a, b


def test_what_you_labelled_the_same_each_time_becomes_a_rule(conn, rid, patterns):
    _tiofli(conn, rid)
    elsewhere = _tx(conn, rid, "Tiofli 3 ROTTERDAM NLD")
    categorization.relabel(conn)
    assert ai_labelling.status(conn)["rule_candidates"] == 1

    ai_labelling.make_rule_suggestions(conn)
    [v] = ai_labelling.rule_suggestions(conn)
    assert (v["pattern"], v["category"], v["touches"], v["changes"]) == ("TIOFLI", "Cafe & uitgaan", 3, 1)

    ai_labelling.rule_suggestion_decision(conn, ids=[v["id"]], accept=True)
    assert _row(conn, elsewhere)["category"] == "Cafe & uitgaan" and _row(conn, elsewhere)["category_source"] == "rule"
    assert ai_labelling.rule_suggestions(conn) == []
    new = _tx(conn, rid, "TIOFLI 7 UTRECHT NLD")
    categorization.relabel(conn)
    assert _row(conn, new)["category"] == "Cafe & uitgaan"


def test_a_too_broad_pattern_falls_back_to_the_name(conn, rid, patterns):
    _tiofli(conn, rid)
    otherwise = _tx(conn, rid, "Sissis 1 AMSTERDAM NLD")
    bank_transactions.set_category_manual(conn, otherwise, "Uit eten & bezorgen")
    patterns["make"] = lambda group_name: "AMSTERDAM"  # also finds Sissis: clashes with your own label
    ai_labelling.make_rule_suggestions(conn)
    [v] = ai_labelling.rule_suggestions(conn)
    assert v["pattern"] == "TIOFLI.*AMSTERDAM" and v["clashes"] == 0


def test_rejected_does_not_come_back(conn, rid, patterns):
    _tiofli(conn, rid)
    ai_labelling.make_rule_suggestions(conn)
    [v] = ai_labelling.rule_suggestions(conn)
    ai_labelling.rule_suggestion_decision(conn, ids=[v["id"]], accept=False)
    asked = patterns["asked"]
    ai_labelling.make_rule_suggestions(conn)
    assert patterns["asked"] == asked and ai_labelling.rule_suggestions(conn) == []
    assert ai_labelling.status(conn)["rule_candidates"] == 0


def test_what_the_rules_already_know_is_not_a_candidate(conn, rid, patterns):
    for tid in (_tx(conn, rid, "ALBERT HEIJN 1234"), _tx(conn, rid, "ALBERT HEIJN 1234")):
        bank_transactions.set_category_manual(conn, tid, "Supermarkt")
    categorization.relabel(conn)
    assert ai_labelling.status(conn)["rule_candidates"] == 0


def test_rule_suggestions_only_with_claude(conn, rid, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ai_labelling.AiError):
        ai_labelling.make_rule_suggestions(conn)


def test_a_round_is_short_and_says_what_it_did(conn, rid, claude):
    """One request to Claude per call: the website does not wait forever. The page
    repeats until `rest` is zero, and shows `items`.
    """
    # Each its own amount: the same day and the same amount counts as a duplicate in the import.
    ids = [_tx(conn, rid, f"Zaak {i} 99", amount=10.0 + i) for i in range(ai_labelling.PER_RUN + 5)]
    categorization.relabel(conn)
    claude["answers"] = {i: ("Cafe & uitgaan", 0.9) for i in ids}
    v = ai_labelling.analyse(conn)
    assert (v["asked"], v["rest"], v["labelled"]) == (ai_labelling.PER_RUN, 5, ai_labelling.PER_RUN)
    assert all(i["applied"] and i["category"] == "Cafe & uitgaan" for i in v["items"])
    assert ai_labelling.analyse(conn)["rest"] == 0


def test_a_check_round_names_what_it_found(conn, rid, claude):
    ids = [_tx(conn, rid, "ALBERT HEIJN 1234") for _ in range(2)]
    categorization.relabel(conn)
    claude["answers"] = {i: ("Uit eten & bezorgen", 0.9) for i in ids}
    v = ai_labelling.verify(conn)
    assert v["deviating"] == 1
    assert v["items"][0] | {"confidence": 0} == {
        "name": "ALBERT HEIJN 1234",
        "now": "Supermarkt",
        "suggestion": "Uit eten & bezorgen",
        "confidence": 0,
        "count": 2,
        "reason": None,
    }


def test_not_right_removes_the_label_and_does_not_ask_again(conn, rid, claude):
    tid = _tx(conn, rid, "Undercurrent AMSTERDAM NLD")
    claude["answers"] = {tid: ("Cafe & uitgaan", 0.95)}
    ai_labelling.analyse(conn)
    assert _row(conn, tid)["category"] == "Cafe & uitgaan"

    ai_labelling.reject(conn, [tid])
    assert _row(conn, tid)["category"] == categorization.UNKNOWN
    assert ai_labelling.by_ai(conn) == []
    claude["asked"].clear()
    ai_labelling.analyse(conn)
    assert claude["asked"] == []
    with pytest.raises(ValueError):
        ai_labelling.reject(conn, [])


def test_review_again_but_not_what_you_rejected(conn, rid, claude):
    knows_not, doubt, rejected = (_tx(conn, rid, f"Zaak {n} 99", amount=10.0 + n) for n in range(3))
    categorization.relabel(conn)
    claude["answers"] = {doubt: ("Cafe & uitgaan", 0.5), rejected: ("Vakantie", 0.95)}
    ai_labelling.analyse(conn)
    ai_labelling.reject(conn, [rejected])
    # Asking again with the same instruction gives the same answer: not offered.
    assert ai_labelling.to_ask(conn) == [] and ai_labelling.status(conn)["again"] == 0

    # Asked with an older instruction: offered.
    conn.execute("UPDATE ai_suggestions SET model = 'claude-oud', created_at = '2026-01-01T00:00:00+00:00'")
    conn.commit()
    assert ai_labelling.status(conn)["again"] == 2
    v = ai_labelling.ask_again(conn)
    assert v["released"] == 2
    assert {r["id"] for r in ai_labelling.to_ask(conn)} == {knows_not, doubt}

    ai_labelling.analyse(conn)
    assert ai_labelling.status(conn)["again"] == 0, "één keer per instructie"


def test_thorough_reviews_what_haiku_did_not_know_with_more_context(conn, rid, claude, monkeypatch):
    ids = [_tx(conn, rid, "Zaak Diep 9", f"bon {i}", amount=10.0 + i) for i in range(3)]
    categorization.relabel(conn)
    ai_labelling.analyse(conn)  # Haiku does not know
    status = ai_labelling.status(conn)
    assert (status["to_ask"], status["again"], status["thorough"]) == (0, 0, 1)

    seen = {}

    def deep(items, categories, *, extra="", model=ai_labelling.MODEL):
        seen.update(model=model, extra=extra, items=items)
        return [{"id": items[0]["id"], "category": "Cafe & uitgaan", "confidence": 0.9, "reason": "fake"}]

    monkeypatch.setattr(ai_labelling, "_ask_claude", deep)
    v = ai_labelling.thorough(conn)
    assert seen["model"] == ai_labelling.MODEL_THOROUGH
    assert len(seen["items"]) == 1 and len(seen["items"][0]["examples"]) == 3
    assert v["labelled"] == 1 and all(_row(conn, i)["category"] == "Cafe & uitgaan" for i in ids)
    status = ai_labelling.status(conn)
    assert (status["thorough"], status["again"]) == (0, 0), "één keer per tegenpartij"
