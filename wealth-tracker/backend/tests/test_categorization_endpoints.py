"""
/api/categories — categories, rules and relabelling from the frontend.

The engine itself is pinned down in backend/tests/domain/test_categorization.py,
including parity with the existing bookkeeping. What is covered here is the
loop the user makes: create a category, add a rule to it, and see the history
get labelled after all — without a manual judgement getting lost.
"""

ING_HEADER = '"Date","Name / Description","Account","Counterparty","Code","Debit/credit","Amount (EUR)","Transaction type","Notifications"'


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _import(client, *names: str):
    """Puts a few bank rows in place through the normal import route."""
    rows = [
        f'"2026021{i}","{name}","NL00INGB0000000001","","BA","Debit","10,00","Payment terminal","Bon {i}"' for i, name in enumerate(names)
    ]
    content = ("\n".join([ING_HEADER, *rows]) + "\n").encode("utf-8")
    resp = client.post("/api/accounts/import", files={"file": ("export.csv", content, "text/csv")})
    assert resp.status_code == 200, resp.text


def _transactions(client):
    return client.get("/api/bank-transactions").json()["transactions"]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_categories_require_a_session(client):
    assert client.get("/api/categories").status_code == 401


# ---------------------------------------------------------------------------
# The taxonomy
# ---------------------------------------------------------------------------


def test_the_default_taxonomy_is_ready_at_once(client):
    """A new user does not have to type 39 categories first."""
    _login(client)
    body = client.get("/api/categories").json()
    assert len(body["categories"]) >= 39
    assert len(body["rules"]) >= 55
    assert {"Supermarkt", "Huur", "Naar spaarrekening"} <= {c["name"] for c in body["categories"]}


def test_create_a_category(client):
    _login(client)
    resp = client.post("/api/categories", json={"group_name": "Wonen", "name": "Oppas", "type": "EXPENSE"})
    assert resp.status_code == 201, resp.text
    assert "Oppas" in {c["name"] for c in client.get("/api/categories").json()["categories"]}


def test_a_category_with_an_unknown_type_gives_400(client):
    _login(client)
    resp = client.post("/api/categories", json={"group_name": "Wonen", "name": "Oppas", "type": "ONZIN"})
    assert resp.status_code == 400


def test_a_duplicate_category_name_gives_409(client):
    _login(client)
    resp = client.post("/api/categories", json={"group_name": "Boodschappen", "name": "Supermarkt", "type": "EXPENSE"})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def test_create_a_rule_and_see_it_back(client):
    _login(client)
    resp = client.post(
        "/api/categories/rules",
        json={
            "priority": 25,
            "field": "N",
            "pattern": "OPPASDIENST",
            "direction": "",
            "category": "Huis & onderhoud",
        },
    )
    assert resp.status_code == 201, resp.text
    patterns = {r["pattern"] for r in client.get("/api/categories").json()["rules"]}
    assert "OPPASDIENST" in patterns


def test_a_broken_pattern_gives_400_and_not_only_when_relabelling(client):
    """Otherwise it falls over when relabelling, and then you do not know which of the 59 it was."""
    _login(client)
    resp = client.post(
        "/api/categories/rules",
        json={
            "priority": 25,
            "field": "N",
            "pattern": "OPPAS(",
            "direction": "",
            "category": "Huur",
        },
    )
    assert resp.status_code == 400
    assert "pattern" in resp.json()["detail"].lower()


def test_an_unknown_field_gives_400(client):
    _login(client)
    resp = client.post(
        "/api/categories/rules",
        json={
            "priority": 25,
            "field": "X",
            "pattern": "OPPAS",
            "direction": "",
            "category": "Huur",
        },
    )
    assert resp.status_code == 400


def test_delete_a_rule(client):
    _login(client)
    rule_id = client.post(
        "/api/categories/rules",
        json={
            "priority": 25,
            "field": "N",
            "pattern": "OPPASDIENST",
            "direction": "",
            "category": "Huur",
        },
    ).json()["rule"]["id"]

    assert client.delete(f"/api/categories/rules/{rule_id}").status_code == 200
    assert client.delete(f"/api/categories/rules/{rule_id}").status_code == 404


# ---------------------------------------------------------------------------
# The loop: import, relabel, correct, make a rule
# ---------------------------------------------------------------------------


def test_relabelling_labels_the_imported_rows(client):
    """An import already labels by itself (see test_bankimport_endpoint), so "Label
    new" afterwards leaves what was recognised alone and only retries what stayed
    unknown — a rule or an own account may have been added since. "Relabel
    everything" recalculates everything — that is what you want after changing a
    rule.
    """
    _login(client)
    _import(client, "ALBERT HEIJN 1234", "ONHERKENBAAR 99999")

    new = client.post("/api/categories/relabel").json()
    assert (new["labelled"], new["unknown"]) == (1, 1), "alleen de onbekende opnieuw"

    report = client.post("/api/categories/relabel?everything=true").json()
    assert report["labelled"] == 2
    assert report["unknown"] == 1
    assert report["coverage"] == 50.0

    on_name = {t["name"]: t for t in _transactions(client)}
    assert on_name["ALBERT HEIJN 1234"]["category"] == "Supermarkt"
    assert on_name["ALBERT HEIJN 1234"]["type"] == "EXPENSE"


def test_a_manual_correction_wins_and_keeps_winning(client):
    """The whole point of three columns: your judgement survives every rule round."""
    _login(client)
    _import(client, "ALBERT HEIJN 1234")
    client.post("/api/categories/relabel")

    transaction_id = _transactions(client)[0]["id"]
    resp = client.put(f"/api/bank-transactions/{transaction_id}/category", json={"category": "Cadeaus & goede doelen"})
    assert resp.status_code == 200, resp.text

    client.post("/api/categories/relabel?everything=true")

    row = _transactions(client)[0]
    assert row["category_auto"] == "Supermarkt"
    assert row["category"] == "Cadeaus & goede doelen"


def test_undoing_a_correction_restores_the_automatic_category(client):
    _login(client)
    _import(client, "ALBERT HEIJN 1234")
    client.post("/api/categories/relabel")
    transaction_id = _transactions(client)[0]["id"]

    client.put(f"/api/bank-transactions/{transaction_id}/category", json={"category": "Cadeaus & goede doelen"})
    client.put(f"/api/bank-transactions/{transaction_id}/category", json={"category": None})

    assert _transactions(client)[0]["category"] == "Supermarkt"


def test_a_new_category_plus_rule_labels_the_history_too(client):
    """The loop the user makes in the frontend, from start to finish."""
    _login(client)
    _import(client, "OPPASDIENST 4471")
    client.post("/api/categories/relabel")
    assert _transactions(client)[0]["category"] == "Onbekend"

    client.post("/api/categories", json={"group_name": "Wonen", "name": "Oppas", "type": "EXPENSE"})
    client.post(
        "/api/categories/rules",
        json={
            "priority": 25,
            "field": "N",
            "pattern": "OPPASDIENST",
            "direction": "",
            "category": "Oppas",
        },
    )
    assert client.post("/api/categories/relabel?everything=true").json()["labelled"] == 1

    row = _transactions(client)[0]
    assert row["category"] == "Oppas"
    assert row["type"] == "EXPENSE"


def test_setting_an_unknown_category_gives_400(client):
    """A typo here makes a transaction impossible to find in any overview."""
    _login(client)
    _import(client, "ALBERT HEIJN 1234")
    transaction_id = _transactions(client)[0]["id"]

    resp = client.put(f"/api/bank-transactions/{transaction_id}/category", json={"category": "Bestaat Niet"})
    assert resp.status_code == 400


def test_setting_a_category_on_an_unknown_transaction_gives_404(client):
    _login(client)
    assert client.put("/api/bank-transactions/999/category", json={"category": "Supermarkt"}).status_code == 404


# ---------------------------------------------------------------------------
# Separation between users
# ---------------------------------------------------------------------------


def test_alices_rules_do_not_apply_to_bob(client):
    _login(client, "alice", "alicepw")
    client.post("/api/categories", json={"group_name": "Wonen", "name": "Oppas", "type": "EXPENSE"})

    _login(client, "bob", "bobpw")
    assert "Oppas" not in {c["name"] for c in client.get("/api/categories").json()["categories"]}


def test_a_category_type_can_be_changed_except_where_the_app_relies_on_it(client):
    """The type decides where a category counts (spending, income, or Bank & cash
    on Net worth). The user may choose it, except for the categories the app's
    own logic depends on."""
    _login(client)
    cats = {c["name"]: c for c in client.get("/api/categories").json()["categories"]}
    gifts = cats["Giften & schenkingen"]
    assert not gifts["type_locked"]
    resp = client.put(f"/api/categories/{gifts['id']}/type", json={"type": "INCOME"})
    assert resp.status_code == 200
    assert {c["name"]: c["type"] for c in resp.json()["categories"]}["Giften & schenkingen"] == "INCOME"

    own = cats["Eigen rekeningen"]
    assert own["type_locked"]
    assert client.put(f"/api/categories/{own['id']}/type", json={"type": "EXPENSE"}).status_code == 400
    assert client.put(f"/api/categories/{gifts['id']}/type", json={"type": "SOMETHING"}).status_code == 400


def test_a_credit_card_repayment_can_count_as_spending(client):
    """Without the card's purchases in the app, the monthly repayment is the only
    trace of that spending: then it belongs in Saved, not in Bank & cash."""
    _login(client)
    card = {c["name"]: c for c in client.get("/api/categories").json()["categories"]}["Creditcard aflossing"]
    assert card["type"] == "INTERNAL" and card["role"] == "debt" and not card["type_locked"]
    resp = client.put(f"/api/categories/{card['id']}/type", json={"type": "EXPENSE"})
    assert resp.status_code == 200
    after = {c["name"]: c for c in resp.json()["categories"]}["Creditcard aflossing"]
    assert after["type"] == "EXPENSE" and after["role"] == "spending"


def test_categories_carry_their_role_on_net_worth():
    from domain.money import categorization as c

    assert c.role_of("Supermarkt", "EXPENSE") == "spending"
    assert c.role_of("Salaris", "INCOME") == "income"
    assert c.role_of(c.INVESTMENT_CATEGORY, "INTERNAL") == "investments"
    assert c.role_of("Creditcard aflossing", "INTERNAL") == "debt"
    assert c.role_of(c.OWN_ACCOUNT_CATEGORY, "INTERNAL") == "own"
    assert c.role_of(c.EXCLUDE, "INTERNAL") == "others"
    assert c.role_of(c.GIFTS, "INTERNAL") == "bank"
