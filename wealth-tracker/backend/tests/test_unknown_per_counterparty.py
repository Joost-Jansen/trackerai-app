"""
What has no category yet, per counterparty — and the general rules that came with it.

On a real export of six years a fifth stayed unknown. Most of that was not
random noise but a handful of counterparties that came back hundreds of times:
the canteen, the salary, transfers to the user's own bunq. One rule per
counterparty solves that, but then you do have to see *which*. That is this
list.

The names here are made up and have a digit or "BV", so the rule that
recognises private persons (four words in capitals) does not catch them.
"""


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _account(client) -> int:
    r = client.post("/api/accounts", json={"kind": "bank", "provider": "manual", "name": "Test"})
    assert r.status_code == 201, r.text
    return r.json()["account"]["id"]


def _book(client, account, name, amount, direction="expense", description="", date="2026-01-15", category=None):
    body = {"account_id": account, "date": date, "amount": amount, "direction": direction,
            "name": name, "description": description}
    if category:
        body["category"] = category
    r = client.post("/api/bank-transactions", json=body)
    assert r.status_code == 201, r.text
    return r.json()["transaction"]


def _unknown(client):
    r = client.get("/api/categories/unknown")
    assert r.status_code == 200, r.text
    return r.json()["counterparties"]


# ---------------------------------------------------------------------------
# The list
# ---------------------------------------------------------------------------

def test_the_largest_group_is_on_top(client):
    _login(client)
    acct = _account(client)
    for day in ("2026-01-02", "2026-01-09", "2026-01-16"):
        _book(client, acct, "Xyzzy Werkplaats 12 BV", 5.50, date=day, description="Kantine")
    _book(client, acct, "Qwerty Diensten 7 BV", 80.0)

    items = _unknown(client)
    assert [g["name"] for g in items] == ["Xyzzy Werkplaats 12 BV", "Qwerty Diensten 7 BV"]
    assert items[0]["count"] == 3
    assert items[0]["total"] == 16.5
    assert items[0]["last"] == "2026-01-16"
    assert items[0]["example"] == "Kantine"


def test_an_income_counts_negative_as_everywhere(client):
    _login(client)
    acct = _account(client)
    _book(client, acct, "Qwerty Diensten 7 BV", 100.0, direction="income")
    assert _unknown(client)[0]["total"] == -100.0


def test_what_has_a_category_is_not_in_it(client):
    _login(client)
    acct = _account(client)
    _book(client, acct, "Xyzzy Werkplaats 12 BV", 5.50, category="Supermarkt")
    assert _unknown(client) == []


def test_after_a_rule_the_group_disappears(client):
    """The loop this screen must support: see, make a rule, gone."""
    _login(client)
    acct = _account(client)
    for _ in range(3):
        _book(client, acct, "Xyzzy Werkplaats 12 BV", 5.50)
    r = client.post("/api/categories/rules", json={
        "priority": 25, "field": "N", "pattern": "XYZZY WERKPLAATS 12 BV", "direction": "", "category": "Lunch werk"})
    assert r.status_code == 201, r.text
    client.post("/api/categories/relabel?everything=true")
    assert _unknown(client) == []


def test_everyone_sees_only_their_own_unknowns(client):
    _login(client)
    _book(client, _account(client), "Xyzzy Werkplaats 12 BV", 5.50)
    client.post("/api/auth/logout")
    _login(client, "bob", "bobpw")
    assert _unknown(client) == []


def test_without_a_session_nothing(client):
    assert client.get("/api/categories/unknown").status_code == 401


# ---------------------------------------------------------------------------
# The general rules that were added
# ---------------------------------------------------------------------------

def test_salary_is_recognised_by_the_description(client):
    """The employer differs per person; the word in the description does not."""
    _login(client)
    acct = _account(client)
    for oms in ("Wage/Salary september", "Salaris oktober", "Vakantiegeld 2026"):
        t = _book(client, acct, "Werkgever 123 BV", 2500.0, direction="income", description=oms)
        assert t["category"] == "Salaris", oms


def test_an_expense_with_salary_in_the_description_is_not_salary(client):
    """Paying back an advance is not income."""
    _login(client)
    t = _book(client, _account(client), "Werkgever 123 BV", 100.0, description="Terugbetaling voorschot salaris")
    assert t["category"] != "Salaris"


def test_at_worldpay_the_shop_in_the_description_counts(client):
    """A payment processor is not a shop; the shop is in the description. That is how
    it already worked for Mollie and CCV; Worldpay came back unknown 74 times.
    """
    _login(client)
    t = _book(client, _account(client), "WORLDPAY", 23.10,
              description="Name: WORLDPAY Description: Albert Heijn 1234 Amsterdam")
    assert t["category"] == "Supermarkt"


def test_paying_off_the_credit_card_is_internal(client):
    _login(client)
    t = _book(client, _account(client), "ING Bank N.V. Creditcards", 312.40, description="Extra aflossing")
    assert t["category"] == "Creditcard aflossing"
    assert t["type"] == "INTERNAL"
