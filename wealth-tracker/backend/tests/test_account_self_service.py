"""S10: a user exports all their data and deletes their own account; nobody
else's data is touched."""

import io
import json
import os
import zipfile

import yaml

from app.core import auth_store, config, feedback_store
from app.services import account_data
from domain import database
from tests.test_bank_upload import PAY


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _users():
    return set(yaml.safe_load(open(config.AUTH_CONFIG_PATH))["credentials"]["usernames"])


def _with_data(client, user, pw):
    _login(client, user, pw)
    assert client.post("/api/accounts/import", files={"file": ("pay.csv", PAY, "text/csv")}).status_code == 200
    feedback_store.add(user, "stock", "idea", f'=HYPERLINK("http://x") from {user}', "/x", {}, b"\x89PNG", "image/png")


def test_export_holds_every_table_and_no_secrets(client):
    _with_data(client, "alice", "alicepw")
    conn = database.connect("alice")
    conn.execute("INSERT INTO bank_connections (provider, app_id, key, created_at) VALUES ('enablebanking', 'app', 'gAAAAAsecret', 'now')")
    conn.commit()
    conn.close()
    r = client.get("/api/account/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert {"account.json", "feedback.json", "database/bank_transactions.csv", "database/bank_transactions.json"} <= names
    assert any(n.startswith("feedback/") for n in names)
    account = json.loads(zf.read("account.json"))
    assert account["username"] == "alice" and "password" not in account
    connections = json.loads(zf.read("database/bank_connections.json"))
    assert connections[0]["key"] == "[withheld]"
    everything = b"".join(zf.read(n) for n in names)
    assert b"gAAAAAsecret" not in everything and b"$2b$" not in everything
    # Formula injection is neutralised in CSV.
    assert account_data.csv_safe("=1+1") == "'=1+1" and account_data.csv_safe(-12.5) == -12.5


def test_export_is_not_for_agents(client):
    _login(client)
    token = auth_store.create_agent_token("alice", "t", "read")["token"]
    from tests.test_mcp_agents import _agent

    assert _agent(client, token).get("/api/account/export").status_code == 403


def test_delete_needs_the_password_and_leaves_others_alone(client):
    _with_data(client, "bob", "bobpw")
    client.post("/api/auth/logout")
    _with_data(client, "alice", "alicepw")
    # alice is not an admin in this fixture; give her a token too
    auth_store.create_agent_token("alice", "t", "read")
    r = client.request("DELETE", "/api/account", json={"password": "wrong"})
    assert r.status_code == 403 and r.json()["code"] == "wrong_current_password"
    r = client.request("DELETE", "/api/account", json={"password": "alicepw"})
    assert r.status_code == 200
    assert "alice" not in _users() and "bob" in _users()
    assert not os.path.exists(database.user_data_dir("alice"))
    assert database.has_data("bob")
    assert feedback_store.list_(username="alice") == [] and feedback_store.list_(username="bob")
    # The session is gone with the account.
    assert client.get("/api/auth/me").status_code == 401


def test_the_last_admin_cannot_delete_themselves(client):
    cfg = yaml.safe_load(open(config.AUTH_CONFIG_PATH))
    cfg["admins"] = ["alice"]
    auth_store.save_config(cfg)
    _login(client, "bob", "bobpw")  # someone else has an account too
    client.post("/api/auth/logout")
    _login(client)
    r = client.request("DELETE", "/api/account", json={"password": "alicepw"})
    assert r.status_code == 409 and r.json()["code"] == "last_admin"
    assert "alice" in _users()


def test_delete_revokes_bank_consents(client, monkeypatch):
    revoked = []
    from domain.money import bank_link

    monkeypatch.setattr(bank_link, "delete_everything", lambda conn, http=None: revoked.append(1))
    _with_data(client, "alice", "alicepw")
    assert client.request("DELETE", "/api/account", json={"password": "alicepw"}).status_code == 200
    assert revoked == [1]
