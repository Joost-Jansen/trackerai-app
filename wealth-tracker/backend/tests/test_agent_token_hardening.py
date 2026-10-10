"""S8: agent tokens can expire, show when they were last used, default to read;
user-supplied rule patterns cannot hang the server (ReDoS)."""

import time

import yaml

from app.core import auth_store, config
from domain import database
from domain.money import categorization, safe_regex

from tests.test_mcp_agents import _agent, _call, _login, _seed_bank


def _make(client, **body):
    return client.post("/api/agent-tokens", json={"name": "t", **body})


def test_a_token_is_read_only_unless_asked(client):
    _login(client)
    r = _make(client)
    assert r.status_code == 201 and r.json()["scope"] == "read"


def test_expiry_is_stored_and_listed(client):
    _login(client)
    r = _make(client, expires_days=30)
    assert r.status_code == 201
    assert r.json()["expires_at"] and r.json()["expired"] is False
    listed = client.get("/api/agent-tokens").json()["tokens"][0]
    assert listed["expires_at"] == r.json()["expires_at"]
    assert _make(client, expires_days=0).status_code == 400
    assert _make(client, expires_days=1000).status_code == 400
    assert _make(client, expires_days=None).json()["expires_at"] is None


def test_an_expired_token_stops_working(client):
    _login(client)
    made = _make(client, expires_days=1).json()
    agent = _agent(client, made["token"])
    assert agent.get("/api/auth/me").status_code == 200
    # Move its end date into the past.
    cfg = yaml.safe_load(open(config.AUTH_CONFIG_PATH))
    for t in cfg["credentials"]["usernames"]["alice"]["agent_tokens"]:
        t["expires_at"] = "2020-01-01T00:00:00+00:00"
    auth_store.save_config(cfg)
    assert agent.get("/api/auth/me").status_code == 401
    r = agent.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 401
    assert client.get("/api/agent-tokens").json()["tokens"][0]["expired"] is True


def test_last_used_is_recorded(client):
    _login(client)
    made = _make(client).json()
    assert _agent(client, made["token"]).get("/api/auth/me").status_code == 200
    assert client.get("/api/agent-tokens").json()["tokens"][0]["last_used"]


# --- ReDoS ---------------------------------------------------------------------


def test_backtracking_patterns_are_refused(client):
    _login(client)
    for pattern in ("(a|aa)+$", "(a+)+", r"(\w+\s?)*$", "(.*,){20}", "x" * 501):
        r = client.post("/api/categories/rules", json={
            "priority": 30, "field": "N", "pattern": pattern, "direction": "", "category": "Huur",
        })
        assert r.status_code == 400, pattern
    ok = client.post("/api/categories/rules", json={
        "priority": 30, "field": "N", "pattern": r"ALBERT HEIJN|\bJUMBO\b|AH TO GO \d+", "direction": "", "category": "Huur",
    })
    assert ok.status_code == 201


def test_a_bad_rule_already_in_the_database_cannot_hang_relabelling(client):
    """Rules from before the check still run, with a timeout per match."""
    _login(client)
    _seed_bank(client)
    conn = database.connect("alice")
    conn.execute("UPDATE bank_transactions SET name = ?", ("a" * 40 + "!",))
    conn.execute("INSERT INTO rules (priority, field, pattern, direction, category) VALUES (1, 'N', '(a|aa)+$', '', 'Huur')")
    conn.commit()
    started = time.monotonic()
    categorization.relabel(conn)
    assert time.monotonic() - started < 5
    conn.close()


def test_mcp_add_category_rule_is_guarded(client):
    _login(client)
    token = client.post("/api/agent-tokens", json={"name": "c", "scope": "write"}).json()["token"]
    res = _call(_agent(client, token), "add_category_rule", {"pattern": "(x+x+)+y", "category": "Huur"})
    assert res["isError"] is True


def test_search_keeps_re_semantics():
    assert safe_regex.search("albert heijn", "ALBERT HEIJN 1427")
    assert safe_regex.search(r"\bH ?& ?M\b", "H&M AMSTERDAM")
    assert not safe_regex.search("JUMBO", "ALBERT HEIJN")
    assert not safe_regex.search("(", "anything")  # broken: no match, no crash
