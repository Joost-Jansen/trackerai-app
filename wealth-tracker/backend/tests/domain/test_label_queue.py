"""
To label as one queue: everything that needs a decision in one shape, and
processing those decisions in one go. Claude is never called: fake answers.
"""

import pytest

from domain.money import ai_labelling
from domain.money import bank_transactions
from domain.money import categorization
from domain import database
from domain.money import label_queue
from domain.money import accounts
from domain import preferences


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


@pytest.fixture()
def claude(conn, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    preferences.put(conn, "ai_labelling", {"on": True})
    fake = {"answers": {}}

    def _ask(items, categories, **_):
        return [{"id": i["id"], "category": c, "confidence": z, "reason": "fake"}
                for i in items if (c_z := fake["answers"].get(i["id"])) for c, z in [c_z]]

    monkeypatch.setattr(ai_labelling, "_ask_claude", _ask)
    monkeypatch.setattr(ai_labelling, "_ask_patterns", lambda groups: [{"id": g["id"], "pattern": "TIOFLI"} for g in groups])
    return fake


_counter = iter(range(1, 10_000))


def _tx(conn, rid, name, description="", amount=10.0, iban=None):
    n = next(_counter)
    bank_transactions.save(conn, rid, [{
        "date": f"2026-04-{n % 28 + 1:02d}", "interest_date": None, "amount": amount, "currency": "EUR",
        "name": name, "counterparty_iban": iban, "description": description, "code": None, "kind": None,
        "dedup_hash": f"w{n}", "raw": {},
    }])
    return conn.execute("SELECT MAX(id) FROM bank_transactions").fetchone()[0]


def _category(conn, tid):
    return next(r for r in bank_transactions.load(conn) if r["id"] == tid)["category"]


def _kind(conn, kind):
    return [i for i in label_queue.queue(conn)["items"] if i["kind"] == kind]


def test_without_claude_only_what_the_rules_do_not_know(conn, rid):
    small = _tx(conn, rid, "Zaak Klein 9", amount=5.0)
    large = [_tx(conn, rid, "Zaak Groot 9", amount=300.0 + i) for i in range(2)]
    categorization.relabel(conn)
    w = label_queue.queue(conn)
    assert w["claude"] is False and w["tellers"]["doubt"] == 0 and w["tellers"]["rule"] == 0
    assert [i["title"] for i in w["items"]] == ["Zaak Groot 9", "Zaak Klein 9"], "grootste bedrag eerst"
    assert w["items"][0]["ids"] == sorted(large) and w["items"][1]["ids"] == [small]
    assert w["waiting"] == 2


def test_an_unknown_counterparty_as_a_rule(conn, rid):
    ids = [_tx(conn, rid, "Tiofli 1 AMSTERDAM NLD", amount=10.0 + i) for i in range(2)]
    categorization.relabel(conn)
    [item] = _kind(conn, "unknown")
    label_queue.decision(conn, [{"kind": "unknown", "choice": "otherwise", "ids": item["ids"],
                                  "category": "Cafe & uitgaan", "rule": True}])
    assert all(_category(conn, i) == "Cafe & uitgaan" for i in ids)
    new = _tx(conn, rid, "Tiofli 1 AMSTERDAM NLD", amount=99.0)
    categorization.relabel(conn)
    assert _category(conn, new) == "Cafe & uitgaan"
    assert _kind(conn, "unknown") == []


def test_later_does_nothing(conn, rid):
    _tx(conn, rid, "Zaak Later 9")
    categorization.relabel(conn)
    [item] = _kind(conn, "unknown")
    label_queue.decision(conn, [{"kind": "unknown", "choice": "reject", "ids": item["ids"]}])
    assert len(_kind(conn, "unknown")) == 1


def test_doubt_agree_and_reject(conn, rid, claude):
    a, b = _tx(conn, rid, "Borisov Amsterdam NLD"), _tx(conn, rid, "Moonflower 9")
    categorization.relabel(conn)
    claude["answers"] = {a: ("Uit eten & bezorgen", 0.6), b: ("Cafe & uitgaan", 0.5)}
    ai_labelling.analyse(conn)
    doubt = {i["title"]: i for i in _kind(conn, "doubt")}
    assert set(doubt) == {"Borisov Amsterdam NLD", "Moonflower 9"}
    assert doubt["Borisov Amsterdam NLD"]["reason"] == "fake"
    assert _kind(conn, "unknown") == [], "wat in twijfel staat staat er niet dubbel"

    label_queue.decision(conn, [
        {"kind": "doubt", "choice": "agreed", "ids": doubt["Borisov Amsterdam NLD"]["ids"], "category": "Uit eten & bezorgen"},
        {"kind": "doubt", "choice": "reject", "ids": doubt["Moonflower 9"]["ids"]},
    ])
    assert _category(conn, a) == "Uit eten & bezorgen"
    assert _kind(conn, "doubt") == []
    assert [i["title"] for i in _kind(conn, "unknown")] == ["Moonflower 9"]


def test_disagree_and_rule_suggestion(conn, rid, claude):
    ah = [_tx(conn, rid, "ALBERT HEIJN 1234", amount=20.0 + i) for i in range(2)]
    tiofli = [_tx(conn, rid, "Tiofli 1 AMSTERDAM NLD", amount=5.0 + i) for i in range(2)]
    for t in tiofli:
        bank_transactions.set_category_manual(conn, t, "Cafe & uitgaan")
    categorization.relabel(conn)
    claude["answers"] = {i: ("Uit eten & bezorgen", 0.9) for i in ah}
    ai_labelling.verify(conn)
    ai_labelling.make_rule_suggestions(conn)

    [disagree] = _kind(conn, "disagree")
    [rule] = _kind(conn, "rule")
    assert (disagree["now"], disagree["suggestion"]) == ("Supermarkt", "Uit eten & bezorgen")
    assert (rule["title"], rule["suggestion"]) == ("TIOFLI", "Cafe & uitgaan")

    label_queue.decision(conn, [
        {"kind": "disagree", "choice": "reject", "ids": disagree["ids"]},
        {"kind": "rule", "choice": "agreed", "ids": [], "rule_id": rule["rule_id"]},
    ])
    assert all(_category(conn, i) == "Supermarkt" for i in ah), "origineel klopt"
    assert _kind(conn, "disagree") == [] and _kind(conn, "rule") == []
    assert any(r["pattern"] == "TIOFLI" for r in categorization.load_rules(conn))


def test_own_account_is_right_as_is(conn):
    accounts.make_bank_account(conn, kind="bank", provider="manual", name="ING", iban="NL00INGB0000000001")
    bunq = accounts.make_bank_account(conn, kind="bank", provider="manual", name="bunq", iban="NL00BUNQ0000000002")
    _tx(conn, bunq, "J. de Vries", amount=-500.0, iban="NL00INGB0000000001")
    without = _tx(conn, bunq, "J. de Vries", amount=-900.0)
    categorization.relabel(conn)
    [item] = _kind(conn, "own")
    assert item["ids"] == [without] and item["suggestion"] == "Eigen rekeningen"
    label_queue.decision(conn, [{"kind": "own", "choice": "reject", "ids": item["ids"], "category": item["now"]}])
    assert _kind(conn, "own") == []
    assert _category(conn, without) == item["now"]


def test_nonsense_decisions(conn):
    with pytest.raises(ValueError):
        label_queue.decision(conn, [])
    with pytest.raises(ValueError):
        label_queue.decision(conn, [{"kind": "unknown", "choice": "misschien", "ids": [1]}])
    with pytest.raises(ValueError):
        label_queue.decision(conn, [{"kind": "unknown", "choice": "otherwise", "ids": [1], "category": "Bestaat niet"}])


def test_money_coming_in_is_never_paid_to_friends(conn, rid, claude):
    """Claude put received money on "Betaald aan vrienden"; and an expense cannot be
    salary.
    """
    within = _tx(conn, rid, "Zaak Binnen 9", "voor het weekend", amount=-50.0)
    off = _tx(conn, rid, "Zaak Uit 9", amount=40.0)
    categorization.relabel(conn)
    claude["answers"] = {within: ("Betaald aan vrienden", 0.9), off: ("Salaris", 0.95)}
    ai_labelling.analyse(conn)
    stored = {r["transaction_id"]: r["category"] for r in conn.execute("SELECT * FROM ai_suggestions")}
    assert stored[within] == "Ontvangen van vrienden"
    assert stored[off] == categorization.UNKNOWN
    assert _category(conn, off) == categorization.UNKNOWN


def test_an_old_suggestion_in_the_wrong_direction_is_corrected(conn, rid, claude):
    """From before the direction check: received money as "paid to friends"."""
    tid = _tx(conn, rid, "Zaak Oud 9", amount=-60.0)
    off = _tx(conn, rid, "Zaak Uit 9", amount=60.0)
    categorization.relabel(conn)
    conn.executemany("INSERT INTO ai_suggestions (transaction_id, category, confidence, created_at) "
                     "VALUES (?, ?, 0.6, '2026-01-01')", [(tid, "Betaald aan vrienden"), (off, "Salaris")])
    conn.commit()
    [item] = _kind(conn, "doubt")
    assert item["ids"] == [tid] and item["suggestion"] == "Ontvangen van vrienden"


def test_certain_but_not_yet_applied_is_applied_after_all(conn, rid, claude):
    tid = _tx(conn, rid, "Zaak Zeker 9")
    categorization.relabel(conn)
    conn.execute("INSERT INTO ai_suggestions (transaction_id, category, confidence, created_at) "
                 "VALUES (?, 'Vakantie', 0.95, '2026-01-01')", (tid,))
    conn.commit()
    assert _category(conn, tid) == categorization.UNKNOWN
    w = label_queue.queue(conn)
    assert _category(conn, tid) == "Vakantie"
    assert not any(tid in i["ids"] for i in w["items"] if i["kind"] in ("doubt", "unknown"))


def test_a_readable_explanation():
    ing = label_queue.readable(
        "Name: P. Visser Description: Betaling van P. Visser NL00RABO0000000045 Borg kamer "
        "IBAN: NL00RABO0000000045 Reference: 13-11-2024 13:55 1234567890123456 Value date: 13/11/2024",
        "P. Visser")
    assert "Borg kamer" in ing
    assert not any(noise in ing for noise in ("NL00RABO", "Name", "IBAN", "13:55", "Visser", "Reference"))
    assert label_queue.readable("Card sequence no.: 900 26/06/2024 12:08 Transaction: W00082 Term: 9DHT", "X") == ""


def test_a_long_explanation_is_not_cut_off():
    lang = "Name: Reisbureau Description: " + " ".join(f"woord{i}" for i in range(60)) + " slotwoord"
    assert label_queue.readable(lang, "Reisbureau").endswith("slotwoord")
