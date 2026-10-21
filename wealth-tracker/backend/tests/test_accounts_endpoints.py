"""
/api/accounts — the wiring, not the arithmetic.

The rules themselves are pinned down in backend/tests/domain/test_accounts.py
against plain dicts. What is covered here is what only the endpoint can get
wrong: auth, scoping per user, and that an error of the domain layer comes back
as a clean error code instead of as a 500.
"""


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _make(client, **overrides):
    body = {
        "kind": "bank",
        "provider": "ing",
        "name": "ING Betaalrekening",
        "iban": "NL00INGB0000000001",
    }
    body.update(overrides)
    return client.post("/api/accounts", json=body)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_accounts_require_a_session(client):
    assert client.get("/api/accounts").status_code == 401
    assert _make(client).status_code == 401


# ---------------------------------------------------------------------------
# Creating and reading
# ---------------------------------------------------------------------------


def test_an_empty_list_is_not_an_error(client):
    _login(client)
    resp = client.get("/api/accounts")
    assert resp.status_code == 200
    assert resp.json()["accounts"] == []


def test_create_an_account_and_read_it_back(client):
    _login(client)
    resp = _make(client)
    assert resp.status_code == 201, resp.text
    account_id = resp.json()["account"]["id"]

    items = client.get("/api/accounts").json()["accounts"]
    assert len(items) == 1
    assert items[0]["id"] == account_id
    assert items[0]["name"] == "ING Betaalrekening"
    assert items[0]["balance"] is None, "zonder meting is het saldo onbekend, niet nul"


def test_cash_may_have_no_iban(client):
    _login(client)
    resp = _make(client, kind="cash", provider="manual", name="Portemonnee", iban=None)
    assert resp.status_code == 201, resp.text
    assert resp.json()["account"]["iban"] is None


def test_the_same_iban_twice_gives_409(client):
    """A duplicate is not a server error but a conflict, and the UI must be able to see that."""
    _login(client)
    assert _make(client).status_code == 201
    resp = _make(client, name="Andere naam")
    assert resp.status_code == 409
    assert "NL00INGB0000000001" in resp.json()["detail"]


def test_an_unknown_kind_gives_400(client):
    _login(client)
    resp = _make(client, kind="spaarvarken")
    assert resp.status_code == 400


def test_an_account_without_a_name_gives_400(client):
    _login(client)
    assert _make(client, name="   ").status_code == 400


# ---------------------------------------------------------------------------
# Updating and deleting
# ---------------------------------------------------------------------------


def test_update_an_account(client):
    _login(client)
    account_id = _make(client).json()["account"]["id"]

    resp = client.patch(f"/api/accounts/{account_id}", json={"name": "Oude ING", "active": 0})
    assert resp.status_code == 200, resp.text
    assert resp.json()["account"]["name"] == "Oude ING"
    assert resp.json()["account"]["active"] == 0


def test_updating_an_unknown_account_gives_404(client):
    _login(client)
    assert client.patch("/api/accounts/999", json={"name": "x"}).status_code == 404


def test_updating_an_unknown_field_gives_400(client):
    _login(client)
    account_id = _make(client).json()["account"]["id"]
    assert client.patch(f"/api/accounts/{account_id}", json={"nmae": "typo"}).status_code == 400


def test_delete_an_account(client):
    _login(client)
    account_id = _make(client).json()["account"]["id"]
    client.put(f"/api/accounts/{account_id}/balance", json={"date": "2026-01-31", "balance": 1000.0})

    assert client.delete(f"/api/accounts/{account_id}").status_code == 200
    assert client.get("/api/accounts").json()["accounts"] == []
    assert client.get("/api/accounts/total?date=2026-02-01").json()["total"] == 0.0


def test_deleting_an_unknown_account_gives_404(client):
    _login(client)
    assert client.delete("/api/accounts/999").status_code == 404


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


def test_set_a_balance_and_see_it_on_the_account(client):
    _login(client)
    account_id = _make(client).json()["account"]["id"]

    resp = client.put(f"/api/accounts/{account_id}/balance", json={"date": "2026-01-31", "balance": 1234.56})
    assert resp.status_code == 200, resp.text

    account = client.get("/api/accounts").json()["accounts"][0]
    assert account["balance"] == 1234.56
    assert account["balance_date"] == "2026-01-31"


def test_a_balance_fills_forward_in_the_total(client):
    """The same rule as in the domain layer, but here through the endpoint."""
    _login(client)
    account_id = _make(client).json()["account"]["id"]
    client.put(f"/api/accounts/{account_id}/balance", json={"date": "2026-01-31", "balance": 1000.0})

    for date, expected in [("2026-01-31", 1000.0), ("2026-06-01", 1000.0), ("2025-12-31", 0.0)]:
        resp = client.get(f"/api/accounts/total?date={date}")
        assert resp.status_code == 200
        assert resp.json()["total"] == expected, date


def test_balance_history_of_an_account(client):
    _login(client)
    account_id = _make(client).json()["account"]["id"]
    client.put(f"/api/accounts/{account_id}/balance", json={"date": "2026-02-28", "balance": 1100.0})
    client.put(f"/api/accounts/{account_id}/balance", json={"date": "2026-01-31", "balance": 1000.0})

    balances = client.get(f"/api/accounts/{account_id}/balances").json()["balances"]
    assert [s["date"] for s in balances] == ["2026-01-31", "2026-02-28"]


def test_a_malformed_date_gives_400(client):
    _login(client)
    account_id = _make(client).json()["account"]["id"]
    resp = client.put(f"/api/accounts/{account_id}/balance", json={"date": "31-01-2026", "balance": 1.0})
    assert resp.status_code == 400


def test_a_balance_for_an_unknown_account_gives_404(client):
    _login(client)
    resp = client.put("/api/accounts/999/balance", json={"date": "2026-01-31", "balance": 1.0})
    assert resp.status_code == 404


def test_total_without_a_date_uses_today(client):
    _login(client)
    account_id = _make(client).json()["account"]["id"]
    client.put(f"/api/accounts/{account_id}/balance", json={"date": "2020-01-01", "balance": 42.0})

    resp = client.get("/api/accounts/total")
    assert resp.status_code == 200
    assert resp.json()["total"] == 42.0


# ---------------------------------------------------------------------------
# Separation between users
# ---------------------------------------------------------------------------


def test_bob_does_not_see_alices_accounts(client):
    """Every endpoint is scoped only by the session cookie; that must hold here too."""
    _login(client, "alice", "alicepw")
    account_id = _make(client).json()["account"]["id"]
    client.put(f"/api/accounts/{account_id}/balance", json={"date": "2026-01-31", "balance": 1000.0})

    _login(client, "bob", "bobpw")
    assert client.get("/api/accounts").json()["accounts"] == []
    assert client.get("/api/accounts/total?date=2026-02-01").json()["total"] == 0.0
    assert client.get(f"/api/accounts/{account_id}/balances").status_code == 404
    assert client.delete(f"/api/accounts/{account_id}").status_code == 404


# ---------------------------------------------------------------------------
# Stacks
# ---------------------------------------------------------------------------


def test_every_account_says_which_stack_it_belongs_to(client):
    """The page groups by stack; that split belongs in one place (net_worth.py) and
    not once more in the frontend.
    """
    _login(client)
    _make(client)
    _make(client, kind="cash", provider="manual", name="Portemonnee", iban=None)
    _make(client, kind="broker", provider="manual", name="Coinbase", iban=None)
    _make(client, kind="debt", provider="manual", name="Studieschuld", iban=None)

    stack = {r["name"]: r["stack"] for r in client.get("/api/accounts").json()["accounts"]}
    assert stack == {
        "ING Betaalrekening": "bank",
        "Portemonnee": "bank",
        "Coinbase": "investments",
        "Studieschuld": "debt",
    }


def test_a_debt_entered_positive_comes_back_negative(client):
    _login(client)
    account_id = _make(client, kind="debt", provider="manual", name="Studieschuld", iban=None).json()["account"]["id"]
    body = client.put(f"/api/accounts/{account_id}/balance", json={"date": "2026-01-31", "balance": 39000.0}).json()
    assert body["account"]["balance"] == -39000.0
