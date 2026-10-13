"""
Agent tokens and the MCP server.

What matters is what a token can *not* do: see someone else's data, change
something with read rights only, or with "write" do more than labelling,
budgets and rules. And that the tools work from start to finish.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _token(client, scope="read", name="Claude"):
    r = client.post("/api/agent-tokens", json={"name": name, "scope": scope})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _agent(client, token):
    from app.main import app

    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _seed_bank(client):
    """One account with three transactions this month, through the browser API."""
    r = client.post("/api/accounts", json={"kind": "bank", "provider": "ing", "name": "Betaal", "iban": "NL00TEST0123456789"})
    assert r.status_code == 201, r.text
    rid = r.json()["account"]["id"]
    today = date.today().isoformat()
    ids = []
    for name, amount, direction in [("ALBERT HEIJN 1427", 42.5, "expense"), ("WINKEL XYZ", 19.99, "expense"), ("WERKGEVER BV", 2500, "income")]:
        r = client.post("/api/bank-transactions", json={"account_id": rid, "date": today, "amount": amount, "direction": direction, "name": name})
        assert r.status_code == 201, r.text
        ids.append(r.json()["transaction"]["id"])
    return ids


def _mcp(agent, method, params=None, path="/api/mcp"):
    r = agent.post(path, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()


def _call(agent, name, args=None):
    res = _mcp(agent, "tools/call", {"name": name, "arguments": args or {}})["result"]
    return res


# --- tokens ------------------------------------------------------------------


def test_token_is_shown_once_and_stored_as_hash(client):
    _login(client)
    token = _token(client)
    assert token.startswith("st_")
    items = client.get("/api/agent-tokens").json()["tokens"]
    assert [t["name"] for t in items] == ["Claude"] and "hash" not in items[0] and "token" not in items[0]

    from app.core import auth_store, config
    assert token not in open(config.AUTH_CONFIG_PATH).read()
    assert auth_store.resolve_agent_token(token)[0] == "alice"


def test_bearer_token_reads_only_its_own_account(client):
    _login(client)
    _seed_bank(client)
    token = _token(client)
    _login(client, "bob", "bobpw")
    bob_token = _token(client)

    alice = _agent(client, token)
    assert alice.get("/api/auth/me").json()["username"] == "alice"
    assert alice.get("/api/bank-transactions").json()["count"] == 3
    bob = _agent(client, bob_token)
    assert bob.get("/api/auth/me").json()["username"] == "bob"
    assert bob.get("/api/bank-transactions").json()["count"] == 0


def test_unknown_or_deleted_token_is_rejected(client):
    _login(client)
    token = _token(client)
    assert _agent(client, "st_nope").get("/api/auth/me").status_code == 401
    tid = client.get("/api/agent-tokens").json()["tokens"][0]["id"]
    assert client.delete(f"/api/agent-tokens/{tid}").json() == {"ok": True}
    assert _agent(client, token).get("/api/auth/me").status_code == 401


def test_suspended_account_token_stops_working(client, _accounts):
    from trackerai_accounts.store import accounts as table

    _login(client)
    token = _token(client)
    with _accounts.engine.begin() as c:
        c.execute(table.update().where(table.c.username == "alice").values(suspended=True))
    assert _agent(client, token).get("/api/auth/me").status_code == 401


def test_read_token_changes_nothing(client):
    _login(client)
    ids = _seed_bank(client)
    agent = _agent(client, _token(client, "read"))
    assert agent.put("/api/budget/Boodschappen", json={"amount": 300}).status_code == 403
    assert agent.put("/api/bank-transactions/category", json={"ids": ids[:1], "category": "Boodschappen"}).status_code == 403
    assert agent.delete(f"/api/bank-transactions/{ids[0]}").status_code == 403


def test_bookkeeping_token_may_only_do_bookkeeping(client):
    _login(client)
    ids = _seed_bank(client)
    agent = _agent(client, _token(client, "write"))
    assert agent.put("/api/budget/Boodschappen", json={"amount": 300}).status_code == 200
    assert agent.put("/api/bank-transactions/category", json={"ids": ids[1:2], "category": "Supermarkt"}).status_code == 200
    # not: deleting, uploading, accounts, categories themselves
    assert agent.delete(f"/api/bank-transactions/{ids[0]}").status_code == 403
    assert agent.post("/api/accounts", json={"kind": "bank", "provider": "ing", "name": "X"}).status_code == 403
    assert agent.post("/api/categories", json={"name": "Nieuw", "group_name": "Shoppen", "type": "EXPENSE"}).status_code == 403
    assert agent.post("/api/uploads/transactions").status_code == 403


def test_token_never_reaches_tokens_admin_or_bank_connection(client):
    from app.core import auth_store

    with auth_store._locked_update() as cfg:
        cfg["admins"] = ["alice"]
    _login(client)
    agent = _agent(client, _token(client, "write"))
    assert agent.get("/api/agent-tokens").status_code == 403
    assert agent.post("/api/agent-tokens", json={"scope": "write"}).status_code == 403
    assert agent.get("/api/admin/tracker").status_code == 403
    assert agent.get("/api/connections").status_code == 403
    assert agent.get("/api/auth/me").json()["is_admin"] is False


def test_refreshing_needs_write_and_reaches_no_more_of_the_bank_connection(client):
    """Prices and a fetch through the existing bank connection: what the Update button does. Never the
    connection itself (its keys, consents and overview)."""
    _login(client)
    read = _agent(client, _token(client, "read"))
    assert read.post("/api/prices/refresh").status_code == 403
    assert read.post("/api/connections/enablebanking/fetch").status_code == 403
    write = _agent(client, _token(client, "write"))
    assert write.post("/api/prices/refresh").status_code == 200
    assert write.post("/api/connections/enablebanking/fetch").status_code != 403  # no connection yet: not a 403
    assert write.get("/api/connections").status_code == 403
    assert write.delete("/api/connections/enablebanking").status_code == 403


def test_mcp_refresh_data_refreshes_prices_and_says_why_the_bank_was_not(client):
    import json

    _login(client)
    write = _agent(client, _token(client, "write"))
    res = _call(write, "refresh_data")
    out = json.loads(res["content"][0]["text"])
    assert "updated_count" in out["prices"]
    assert "error" in out["bank"]  # nothing connected in this test


def test_unknown_scope_is_refused(client):
    _login(client)
    assert client.post("/api/agent-tokens", json={"scope": "everything"}).status_code == 400


# --- MCP ---------------------------------------------------------------------


def test_mcp_initialize_and_tool_list_follow_the_scope(client):
    _login(client)
    read = _agent(client, _token(client, "read"))
    init = _mcp(read, "initialize", {"protocolVersion": "2025-06-18"})["result"]
    assert init["serverInfo"]["name"] == "stock-tracker" and "may only read" in init["instructions"]
    names = {t["name"] for t in _mcp(read, "tools/list")["result"]["tools"]}
    assert {"get_overview", "get_spending", "list_transactions"} <= names
    assert {"get_net_worth_split", "get_settings", "get_fixed_costs", "list_categories",
            "get_bank_corrections", "list_balances"} <= names
    writes = {"label_transactions", "set_budget", "add_category_rule", "delete_rule", "set_category_type",
              "rename_category", "move_category", "set_month_layout", "set_shared_costs_category",
              "set_fixed_cost", "set_balance", "add_transaction", "delete_balance", "refresh_data"}
    assert not names & writes

    write = _agent(client, _token(client, "write"))
    names = {t["name"] for t in _mcp(write, "tools/list")["result"]["tools"]}
    assert writes <= names


def test_mcp_speaks_to_any_client(client):
    """Clients differ in protocol version, header or URL token, and notifications."""
    _login(client)
    token = _token(client, "read")
    agent = _agent(client, token)
    for asked, got in [("2025-11-25", "2025-11-25"), ("2024-11-05", "2024-11-05"), ("1999-01-01", "2025-11-25")]:
        assert _mcp(agent, "initialize", {"protocolVersion": asked})["result"]["protocolVersion"] == got
    # A client that only takes a URL: the token in the path, no header.
    from app.main import app

    r = TestClient(app).post(f"/api/mcp/{token}", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 200 and r.json()["result"]["tools"]
    # A notification gets no answer, and there is no SSE stream to open.
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers).status_code == 202
    assert client.get("/api/mcp", headers=headers).status_code == 405


def test_mcp_needs_a_valid_token(client):
    from app.main import app

    anon = TestClient(app)
    assert anon.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
    assert anon.post("/api/mcp/st_nope", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401


def test_mcp_read_tools_on_real_data(client):
    import json

    _login(client)
    _seed_bank(client)
    token = _token(client, "read")
    from app.main import app
    agent = TestClient(app)  # token in the path, like the claude.ai connector

    path = f"/api/mcp/{token}"
    remaining = _mcp(agent, "tools/call", {"name": "get_overview", "arguments": {}}, path)["result"]
    assert not remaining["isError"], remaining
    data = json.loads(remaining["content"][0]["text"])
    assert data["this_month"]["spending"] == pytest.approx(62.49)
    assert data["this_month"]["income"] == pytest.approx(2500)

    tx = json.loads(_mcp(agent, "tools/call", {"name": "list_transactions", "arguments": {"search": "heijn"}}, path)["result"]["content"][0]["text"])
    assert tx["found"] == 1 and tx["transactions"][0]["name"] == "ALBERT HEIJN 1427"

    acc = json.loads(_mcp(agent, "tools/call", {"name": "list_accounts"}, path)["result"]["content"][0]["text"])
    assert acc[0]["account_number"] == "…6789" and "iban" not in acc[0]

    # with read rights a write tool refuses
    res = _mcp(agent, "tools/call", {"name": "set_budget", "arguments": {"group_name": "Boodschappen", "amount": 1}}, path)["result"]
    assert res["isError"] and "read access" in res["content"][0]["text"]


def test_mcp_bookkeeping_tools(client):
    import json

    _login(client)
    ids = _seed_bank(client)
    agent = _agent(client, _token(client, "write"))

    res = _call(agent, "label_transactions", {"ids": [ids[1]], "category": "Supermarkt"})
    assert not res["isError"], res
    tx = client.get("/api/bank-transactions").json()["transactions"]
    assert next(t for t in tx if t["id"] == ids[1])["category"] == "Supermarkt"

    assert not _call(agent, "set_budget", {"group_name": "Eten & vrije tijd", "amount": 125})["isError"]
    budget = client.get("/api/budget?months=1").json()["groups"]
    assert next(g for g in budget if g["group_name"] == "Eten & vrije tijd")["budget"] == 125

    res = _call(agent, "add_category_rule", {"pattern": "WINKEL XYZ", "category": "Sport & hobby"})
    assert not res["isError"], res
    assert json.loads(res["content"][0]["text"])["rule"]["category"] == "Sport & hobby"

    error = _call(agent, "label_transactions", {"ids": [ids[0]], "category": "Bestaat niet"})
    assert error["isError"]


def _json(res):
    import json

    assert not res["isError"], res
    return json.loads(res["content"][0]["text"])


def test_write_token_may_keep_categories_settings_and_balances_but_not_more(client):
    _login(client)
    ids = _seed_bank(client)
    agent = _agent(client, _token(client, "write"))
    read = _agent(client, _token(client, "read"))
    cats = {c["name"]: c["id"] for c in client.get("/api/categories").json()["categories"]}
    account_id = client.get("/api/accounts").json()["accounts"][0]["id"]
    for path, method, body in [
        (f"/api/categories/{cats['Supermarkt']}/type", "put", {"type": "EXPENSE"}),
        ("/api/month-periods", "put", {"mode": "calendar"}),
        ("/api/spending/shared-costs", "put", {"category": None}),
        (f"/api/accounts/{account_id}/balance", "put", {"date": date.today().isoformat(), "balance": 10}),
    ]:
        assert getattr(read, method)(path, json=body).status_code == 403, path
        assert getattr(agent, method)(path, json=body).status_code == 200, path
    # still not: deleting a category, a transaction or an account
    assert agent.delete(f"/api/categories/{cats['Supermarkt']}").status_code == 403
    assert agent.delete(f"/api/bank-transactions/{ids[0]}").status_code == 403
    assert agent.delete(f"/api/accounts/{account_id}").status_code == 403


def test_mcp_net_worth_split_settings_and_fixed_costs(client):
    _login(client)
    _seed_bank(client)
    agent = _agent(client, _token(client, "write"))

    first = date.today().replace(day=1)
    before = date.fromordinal(first.toordinal() - 1)
    # A payment last month, so the series starts before this month, and a balance
    # today: the balances in between follow from the transactions.
    _json(_call(agent, "add_transaction", {"account": "Betaal", "amount": 100, "name": "HUUR", "date": before.isoformat()}))
    bal = _json(_call(agent, "set_balance", {"account": "Betaal", "balance": 3437.51}))
    assert bal["account"]["account_number"] == "…6789" and "iban" not in bal["account"]
    assert bal["account"]["balance"] == pytest.approx(3437.51)

    split = _json(_call(agent, "get_net_worth_split", {"start": first.isoformat()}))
    assert split["month_layout"] == "calendar"
    month = split["months"][-1]
    assert month["month"] == date.today().isoformat()[:7]
    assert month["change"] == pytest.approx(2437.51)
    assert month["saved"] == pytest.approx(2437.51)   # 2500 in, 62.49 out
    assert month["saved"] + month["market"] + month["bank"] + month["debt"] == pytest.approx(month["change"])
    assert set(month["detail"]) == {"friends", "unlabelled", "corrections", "transfers", "listed", "other_half"}
    assert month["detail"]["listed"] + month["detail"]["corrections"] + month["detail"]["other_half"] == pytest.approx(month["bank"])
    assert (split["period"]["from"], split["period"]["to"]) == (before.isoformat(), date.today().isoformat())
    assert split["period"]["saved"] == pytest.approx(2437.51)
    assert len(_json(_call(agent, "get_net_worth_split", {"months": 1}))["months"]) == 1
    assert _call(agent, "get_net_worth_split", {"start": "2026-02-30"})["isError"]

    settings = _json(_call(agent, "get_settings"))
    assert settings["month_layout"]["mode"] == "calendar"
    assert "shared_costs_category" in settings

    changed = _json(_call(agent, "set_month_layout", {"mode": "salary", "day": 21}))
    assert changed["month_layout"]["mode"] == "salary" and changed["month_layout"]["day_configured"] == 21
    assert _json(_call(agent, "set_month_layout", {"mode": "calendar", "day": None}))["month_layout"]["day_configured"] is None
    assert _call(agent, "set_month_layout", {"mode": "weekly"})["isError"]

    assert _json(_call(agent, "set_shared_costs_category", {"category": "Supermarkt"}))["shared_costs_category"] == "Supermarkt"
    assert client.get("/api/spending/shared-costs").json()["category"] == "Supermarkt"
    assert _json(_call(agent, "set_shared_costs_category", {"category": None}))["shared_costs_category"] is None
    assert _call(agent, "set_shared_costs_category", {"category": "Salaris"})["isError"]   # not spending

    fixed = _json(_call(agent, "get_fixed_costs"))
    assert set(fixed) == {"per_month", "is_fixed", "candidates", "excluded"}
    out = _json(_call(agent, "set_fixed_cost", {"name": "WINKEL XYZ", "is_fixed": False}))
    assert any(v["name"].upper() == "WINKEL XYZ" for v in out["fixed_costs"]["excluded"])
    out = _json(_call(agent, "set_fixed_cost", {"name": "WINKEL XYZ", "is_fixed": None}))
    assert not any(v["name"].upper() == "WINKEL XYZ" for v in out["fixed_costs"]["excluded"])


def test_mcp_category_tools(client):
    _login(client)
    _seed_bank(client)
    agent = _agent(client, _token(client, "write"))

    listed = _json(_call(agent, "list_categories"))
    salaris = next(c for c in listed["categories"] if c["name"] == "Salaris")
    assert salaris["role"] == "income" and salaris["type_locked"] is True

    out = _json(_call(agent, "set_category_type", {"category": "Sport & hobby", "type": "INTERNAL"}))
    assert out["category"]["type"] == "INTERNAL" and out["category"]["role"] == "bank"
    refused = _call(agent, "set_category_type", {"category": "Salaris", "type": "EXPENSE"})
    assert refused["isError"] and "locked" in refused["content"][0]["text"]
    assert _call(agent, "set_category_type", {"category": "Bestaat niet", "type": "EXPENSE"})["isError"]

    out = _json(_call(agent, "rename_category", {"category": "Sport & hobby", "new_name": "Sport"}))
    assert out["category"]["name"] == "Sport"
    out = _json(_call(agent, "move_category", {"category": "Sport", "group_name": "Vrije tijd"}))
    assert out["category"]["group_name"] == "Vrije tijd"

    rule = _json(_call(agent, "add_category_rule", {"pattern": "WINKEL XYZ", "category": "Sport"}))["rule"]
    assert _json(_call(agent, "delete_rule", {"id": rule["id"]}))["deleted_rule"] == rule["id"]
    assert not any(r["id"] == rule["id"] for r in client.get("/api/categories").json()["rules"])
    assert _call(agent, "delete_rule", {"id": rule["id"]})["isError"]


def test_mcp_add_transaction_follows_the_sign_convention(client):
    _login(client)
    _seed_bank(client)
    agent = _agent(client, _token(client, "write"))

    spent = _json(_call(agent, "add_transaction", {"account": "Betaal", "amount": 12.5, "name": "MARKT KRAAM", "category": "Supermarkt"}))["transaction"]
    assert spent["amount"] == pytest.approx(12.5) and spent["category"] == "Supermarkt"
    got = _json(_call(agent, "add_transaction", {"account": "betaal", "amount": -40, "name": "OMA"}))["transaction"]
    assert got["amount"] == pytest.approx(-40)
    assert client.get("/api/bank-transactions").json()["count"] == 5
    assert _call(agent, "add_transaction", {"account": "Betaal", "amount": 0, "name": "X"})["isError"]
    assert _call(agent, "add_transaction", {"account": "Nergens", "amount": 1, "name": "X"})["isError"]

    read = _agent(client, _token(client, "read"))
    res = _call(read, "add_transaction", {"account": "Betaal", "amount": 1, "name": "X"})
    assert res["isError"] and "read access" in res["content"][0]["text"]


def test_mcp_finds_and_removes_a_wrong_balance(client):
    """A balance on a savings account without transactions is a correction in
    Bank & cash; the agent sees it per account, and may delete a wrong one."""
    _login(client)
    rid = client.post("/api/accounts", json={"kind": "bank", "provider": "ing", "name": "Spaar"}).json()["account"]["id"]
    for d, v in [("2026-01-01", 1000), ("2026-01-15", 9000), ("2026-02-01", 1000)]:
        assert client.put(f"/api/accounts/{rid}/balance", json={"date": d, "balance": v, "source": "sync"}).status_code == 200
    agent = _agent(client, _token(client, "write"))
    read = _agent(client, _token(client, "read"))

    out = _json(_call(read, "get_bank_corrections", {"from": "2026-01-10", "to": "2026-01-20"}))
    assert out["total"] == 8000
    assert out["accounts"][0]["events"] == [{"date": "2026-01-15", "kind": "measurement", "source": "sync",
                                             "balance": 9000.0, "amount": 8000.0}]
    balances = _json(_call(read, "list_balances", {"account": "Spaar"}))
    assert [b["date"] for b in balances["balances"]] == ["2026-01-01", "2026-01-15", "2026-02-01"]
    assert _call(read, "get_bank_corrections", {"from": "2026-01-20", "to": "2026-01-10"})["isError"]

    # read rights may not delete; write rights may
    assert _call(read, "delete_balance", {"account": "Spaar", "date": "2026-01-15"})["isError"]
    assert _json(_call(agent, "delete_balance", {"account": "Spaar", "date": "2026-01-15"}))["deleted"]["date"] == "2026-01-15"
    assert _json(_call(read, "get_bank_corrections", {"from": "2026-01-10", "to": "2026-01-20"}))["total"] == 0
    assert _call(agent, "delete_balance", {"account": "Spaar", "date": "2026-01-15"})["isError"]  # gone already
