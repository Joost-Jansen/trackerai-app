"""The shared OAuth identity reaches only its own health MCP tools."""
import secrets
import sys
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import update
from api.main import create_app
from tests.test_api import engine, make_settings  # noqa: F401
from tools import db
from trackerai_accounts import Accounts, Config, connect, crypto
from trackerai_accounts.service import now
from trackerai_accounts.store import oauth_grants

sys.path.append(str(Path(__file__).resolve().parents[2] / 'packages/accounts/tests'))
from oauth_fixtures import seed_token


def health(engine, tmp_path, scope='read'):
    cfg = Config(database_url=f'sqlite:///{tmp_path}/accounts.db', session_secret=secrets.token_urlsafe(32),
        encryption_key=crypto.new_key(), require_totp='off', cookie_secure=False)
    accounts = Accounts(connect(cfg.database_url), cfg)
    app = create_app(engine=engine, accounts=accounts, settings=make_settings())
    token, gid = seed_token(accounts, accounts.by_username('alice'), 'health', scope)
    return TestClient(app, base_url='https://health.example', headers={'Authorization': 'Bearer ' + token}), accounts, token, gid


def rpc(client, method, **params):
    return client.post('/api/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})


def test_read_only_health_and_revocation(engine, tmp_path):
    client, accounts, token, gid = health(engine, tmp_path)
    tools = rpc(client, 'tools/list').json()['result']['tools']
    names = {t['name'] for t in tools}
    assert 'list_activities' in names and not {'add_log', 'create_plan', 'update_doc', 'list_feedback', 'sync_now'} & names
    assert all(t['securitySchemes'] == [{'type': 'oauth2', 'scopes': ['health:read']}] for t in tools)
    read = rpc(client, 'tools/call', name='list_activities', arguments={}).json()['result']
    assert not read['isError'] and 'Ochtendloop' in read['content'][0]['text']
    for name in ['add_log', 'create_plan', 'replace_plan_sessions', 'set_plan_status', 'update_doc', 'sync_now']:
        assert rpc(client, 'tools/call', name=name, arguments={}).json()['result']['isError']
    assert client.get('/api/me').status_code == 403
    assert client.post('/api/mcp/' + token, json={}).status_code == 401
    with accounts.engine.begin() as c:
        c.execute(update(oauth_grants).where(oauth_grants.c.id == gid).values(revoked_at=now()))
    response = rpc(client, 'tools/list')
    assert response.status_code == 401 and 'resource_metadata=' in response.headers['www-authenticate']


def test_health_write_is_scoped_and_has_no_admin(engine, tmp_path):
    client, _, _, _ = health(engine, tmp_path, 'write')
    tools = rpc(client, 'tools/list').json()['result']['tools']
    assert 'add_log' in {t['name'] for t in tools} and 'list_feedback' not in {t['name'] for t in tools}
    assert not rpc(client, 'tools/call', name='add_log', arguments={'title': 'Test', 'body': 'Disposable note'}).json()['result']['isError']
    assert db.list_entries(db.Scope(engine, 1))[0]['author'] == 'agent'


def test_missing_token_advertises_shared_issuer(engine, tmp_path):
    client, _, _, _ = health(engine, tmp_path)
    client.headers.pop('Authorization')
    response = rpc(client, 'initialize')
    assert response.status_code == 401 and 'health.example/.well-known' in response.headers['www-authenticate']
    assert client.get('/.well-known/oauth-protected-resource').json()['authorization_servers'] == ['https://wealth.example']
