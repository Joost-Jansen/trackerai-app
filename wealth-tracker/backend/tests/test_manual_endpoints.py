"""
Manual input through the API: removing measurements, and spending or income
that is in no export. The amount always comes in positive, with the direction
separately — nobody needs to know that an expense is stored as positive in the
database.
"""


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _account(client, name="Contant", kind="cash"):
    return client.post(
        "/api/accounts",
        json={
            "kind": kind,
            "provider": "manual",
            "name": name,
            "iban": None,
        },
    ).json()["account"]["id"]


def _add(client, **fields):
    body = {"date": "2026-03-01", "amount": 12.5, "direction": "expense", "name": "Markt"}
    body.update(fields)
    return client.post("/api/bank-transactions", json=body)


def test_manual_requires_a_session(client):
    assert _add(client, account_id=1).status_code == 401


def test_an_expense_is_positive_and_an_income_negative(client):
    _login(client)
    r = _account(client)
    off = _add(client, account_id=r)
    assert off.status_code == 201, off.text
    assert off.json()["transaction"]["amount"] == 12.5
    assert off.json()["transaction"]["source"] == "manual"

    inn = _add(client, account_id=r, direction="income", amount=50, name="Tikkie terug")
    assert inn.json()["transaction"]["amount"] == -50.0


def test_without_a_category_the_rules_decide_it(client):
    _login(client)
    row = _add(client, account_id=_account(client), name="ALBERT HEIJN").json()["transaction"]
    assert row["category"] == "Supermarkt"


def test_with_a_category_your_choice_wins(client):
    _login(client)
    row = _add(client, account_id=_account(client), name="ALBERT HEIJN", category="Cadeaus & goede doelen").json()["transaction"]
    assert row["category"] == "Cadeaus & goede doelen"
    assert row["category_auto"] == "Supermarkt", "wat de regels vonden staat erbij"


def test_it_counts_in_the_list_and_the_totals(client):
    _login(client)
    _add(client, account_id=_account(client), name="ALBERT HEIJN", amount=40)
    rows = client.get("/api/bank-transactions").json()["transactions"]
    assert len(rows) == 1 and rows[0]["type"] == "EXPENSE"


def test_nonsense_gives_400(client):
    _login(client)
    r = _account(client)
    assert _add(client, account_id=r, amount=0).status_code == 400
    assert _add(client, account_id=r, amount=-5).status_code == 400
    assert _add(client, account_id=r, direction="misschien").status_code == 400
    assert _add(client, account_id=r, date="1-3-2026").status_code == 400
    assert _add(client, account_id=r, category="Bestaat Niet").status_code == 400
    assert _add(client, account_id=r, name="  ").status_code == 400


def test_an_unknown_account_gives_404(client):
    _login(client)
    assert _add(client, account_id=999).status_code == 404


def test_delete(client):
    _login(client)
    tid = _add(client, account_id=_account(client)).json()["transaction"]["id"]
    assert client.delete(f"/api/bank-transactions/{tid}").status_code == 200
    assert client.get("/api/bank-transactions").json()["transactions"] == []
    assert client.delete(f"/api/bank-transactions/{tid}").status_code == 404


def test_an_imported_transaction_cannot_be_deleted(client):
    _login(client)
    header = '"Date","Name / Description","Account","Counterparty","Code","Debit/credit","Amount (EUR)","Transaction type","Notifications"'
    row = '"20260219","WINKEL","NL00INGB0000000001","","BA","Debit","5,00","Payment terminal","x"'
    client.post("/api/accounts/import", files={"file": ("e.csv", f"{header}\n{row}\n".encode(), "text/csv")})
    tid = client.get("/api/bank-transactions").json()["transactions"][0]["id"]
    resp = client.delete(f"/api/bank-transactions/{tid}")
    assert resp.status_code == 400
    assert "import" in resp.json()["detail"]


def test_delete_a_measurement(client):
    _login(client)
    r = _account(client)
    client.put(f"/api/accounts/{r}/balance", json={"date": "2026-01-31", "balance": 100})
    client.put(f"/api/accounts/{r}/balance", json={"date": "2026-02-28", "balance": 200})

    resp = client.delete(f"/api/accounts/{r}/balance/2026-02-28")
    assert resp.status_code == 200, resp.text
    assert resp.json()["account"]["balance"] == 100
    assert client.delete(f"/api/accounts/{r}/balance/2026-02-28").status_code == 404
    assert client.delete(f"/api/accounts/{r}/balance/28-02-2026").status_code == 400


def test_bob_cannot_delete_anything_of_alices(client):
    _login(client, "alice", "alicepw")
    r = _account(client)
    tid = _add(client, account_id=r).json()["transaction"]["id"]
    client.put(f"/api/accounts/{r}/balance", json={"date": "2026-01-31", "balance": 100})

    _login(client, "bob", "bobpw")
    assert client.delete(f"/api/bank-transactions/{tid}").status_code == 404
    assert client.delete(f"/api/accounts/{r}/balance/2026-01-31").status_code == 404
