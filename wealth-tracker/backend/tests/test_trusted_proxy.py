"""S4/S13: the client address only comes from forwarding headers sent by a
trusted proxy, and failed agent-token attempts are limited per address."""

from starlette.requests import Request

from app.core import auth_store, throttle
from trackerai_websec.client_ip import trusted_networks


def _request(peer: str, headers: dict) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (peer, 1234),
            "query_string": b"",
        }
    )


def test_forged_cf_header_is_ignored_without_trusted_proxies(monkeypatch):
    monkeypatch.setattr(throttle, "TRUSTED", [])
    assert throttle.client_ip(_request("198.51.100.7", {"CF-Connecting-IP": "1.1.1.1"})) == "198.51.100.7"


def test_cf_header_is_used_from_the_trusted_proxy(monkeypatch):
    monkeypatch.setattr(throttle, "TRUSTED", trusted_networks("172.20.0.0/16"))
    assert throttle.client_ip(_request("172.20.0.3", {"CF-Connecting-IP": "1.1.1.1"})) == "1.1.1.1"
    assert throttle.client_ip(_request("198.51.100.7", {"CF-Connecting-IP": "1.1.1.1"})) == "198.51.100.7"


def test_rotating_a_forged_header_does_not_reset_the_ip_limit(client, monkeypatch):
    """Spraying many accounts with a fresh CF-Connecting-IP each time used to get a
    fresh per-IP allowance every request."""
    monkeypatch.setattr(throttle, "TRUSTED", [])
    codes = [
        client.post(
            "/api/auth/login", json={"username": f"user{i}", "password": "x"}, headers={"CF-Connecting-IP": f"10.0.{i}.1"}
        ).status_code
        for i in range(32)
    ]
    assert codes[:30] == [401] * 30
    assert codes[30:] == [429, 429]
    r = client.post("/api/auth/login", json={"username": "alice", "password": "alicepw"})
    assert r.status_code == 429 and r.json()["code"] == "too_many_attempts"


def test_failed_agent_tokens_are_limited_per_ip(client):
    for _ in range(20):
        assert client.post("/api/mcp/st_wrong", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
    r = client.post("/api/mcp/st_wrong", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 429 and r.json()["code"] == "too_many_attempts"
    # Bearer on the REST API counts against the same budget.
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer st_wrong"}).status_code == 429
    # A real token from that address is refused too until the window passes:
    # the limit is checked before anything is looked up.
    token = auth_store.create_agent_token("alice", "t", "read")["token"]
    assert client.post(f"/api/mcp/{token}", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 429
    throttle.reset_all()
    assert client.post(f"/api/mcp/{token}", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 200
