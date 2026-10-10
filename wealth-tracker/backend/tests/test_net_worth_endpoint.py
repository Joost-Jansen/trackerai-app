"""
/api/net-worth — the wiring.

The arithmetic is pinned down in backend/tests/domain/test_net_worth.py
against plain dicts. What is covered here is what only the endpoint can miss:
auth, scoping, and that an empty database is not an error but an empty answer.
"""


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _account(client, name="ING", kind="bank", iban=None):
    resp = client.post("/api/accounts", json={
        "kind": kind, "provider": "manual", "name": name, "iban": iban,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["account"]["id"]


def test_net_worth_requires_a_session(client):
    assert client.get("/api/net-worth").status_code == 401


def test_an_empty_database_gives_an_empty_answer_not_an_error(client):
    _login(client)
    resp = client.get("/api/net-worth")
    assert resp.status_code == 200
    body = resp.json()
    assert body["points"] == []
    assert body["months"] == []
    assert body["now"] is None


def test_only_a_bank_balance_already_gives_a_net_worth(client):
    """You do not have to invest to have a net worth."""
    _login(client)
    account_id = _account(client)
    client.put(f"/api/accounts/{account_id}/balance",
               json={"date": "2026-01-31", "balance": 2500.0})

    body = client.get("/api/net-worth").json()
    assert body["now"]["net"] == 2500.0
    assert body["now"]["bank"] == 2500.0
    assert body["now"]["investments"] == 0.0
    assert body["from_date"] == "2026-01-31"


def test_debt_lowers_net_worth(client):
    _login(client)
    bank = _account(client, "ING")
    debt = _account(client, "Studieschuld", kind="debt")
    client.put(f"/api/accounts/{bank}/balance", json={"date": "2026-01-31", "balance": 10000.0})
    client.put(f"/api/accounts/{debt}/balance", json={"date": "2026-01-31", "balance": -39000.0})

    now = client.get("/api/net-worth").json()["now"]
    assert now["debt"] == -39000.0
    assert now["net"] == -29000.0


def test_month_figures_come_from_the_bank_transactions(client):
    _login(client)
    header = ('"Date","Name / Description","Account","Counterparty","Code",'
           '"Debit/credit","Amount (EUR)","Transaction type","Notifications"')
    rows = [
        '"20260105","SUPERMARKT","NL00INGB0000000001","","BA","Debit","100,00","Payment terminal","x"',
        '"20260125","WERKGEVER","NL00INGB0000000001","","OV","Credit","3000,00","Transfer","Name: WERKGEVER"',
    ]
    content = ("\n".join([header, *rows]) + "\n").encode("utf-8")
    assert client.post("/api/accounts/import",
                       files={"file": ("e.csv", content, "text/csv")}).status_code == 200
    client.post("/api/categories/relabel")

    months = client.get("/api/net-worth").json()["months"]
    assert len(months) == 1
    assert months[0]["month"] == "2026-01"
    assert months[0]["spending"] == 100.0
    assert months[0]["income"] == 3000.0
    assert months[0]["remaining"] == 2900.0
    assert months[0]["complete"] is False, "de export begint pas op de 5e"


def test_bob_does_not_see_alices_net_worth(client):
    _login(client, "alice", "alicepw")
    account_id = _account(client)
    client.put(f"/api/accounts/{account_id}/balance",
               json={"date": "2026-01-31", "balance": 2500.0})

    _login(client, "bob", "bobpw")
    body = client.get("/api/net-worth").json()
    assert body["points"] == []
    assert body["now"] is None


def test_the_answer_has_flows(client):
    """The page splits each change with the per-day flows."""
    _login(client)
    assert client.get("/api/net-worth").json()["flows"] == []


def test_shared_costs_setting_defaults_to_holidays_and_can_be_changed(client):
    _login(client)
    client.get("/api/categories")   # a new account gets its default categories here
    assert client.get("/api/spending/shared-costs").json()["category"] == "Vakantie"
    assert client.put("/api/spending/shared-costs", json={"category": None}).json()["category"] is None
    assert client.get("/api/net-worth").json()["shared_costs_category"] is None
    assert client.put("/api/spending/shared-costs", json={"category": "Salaris"}).status_code == 400
    assert client.put("/api/spending/shared-costs", json={"category": "Vakantie"}).json()["category"] == "Vakantie"


def test_bank_transactions_can_include_your_share_of_shared_costs(client):
    """Only on request: the Spending overview asks for it, the list of
    transactions itself shows what really happened on the account."""
    from domain import database
    from domain.money import accounts, bank_transactions, categorization

    _login(client)
    client.get("/api/categories")
    conn = database.connect("alice")
    r = accounts.make_bank_account(conn, kind="bank", provider="manual", name="bunq")
    accounts.set_balance(conn, r, "2026-01-01", 1000.0)
    bank_transactions.save(conn, r, [{
        "date": "2026-03-01", "interest_date": None, "amount": 400.0, "currency": "EUR",
        "name": "Boat", "counterparty_iban": None, "description": "",
        "code": None, "kind": None, "dedup_hash": "b" * 16, "raw": {},
    }])
    conn.execute("UPDATE bank_transactions SET category_auto = ?", (categorization.EXCLUDE,))
    conn.commit()
    conn.close()

    plain = client.get("/api/bank-transactions").json()["transactions"]
    assert [t["source"] for t in plain] == ["import"]
    shared = client.get("/api/bank-transactions?shared_shares=true").json()["transactions"]
    derived = [t for t in shared if t["source"] == "derived"]
    assert [(t["amount"], t["category"], t["type"]) for t in derived] == [(400.0, "Vakantie", "EXPENSE")]
