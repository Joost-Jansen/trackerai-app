"""Every tr("…") text in the backend has a Dutch entry with the same placeholders,
and the language follows the X-Locale header."""

import ast
import pathlib
import re

from domain.i18n import current_locale, reset_locale, set_locale, tr
from domain.i18n_nl import NL

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
_PLACEHOLDER = re.compile(r"\{\d+\}")


def _texts():
    for path in _BACKEND.rglob("*.py"):
        if "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                yield node.args[0].value, f"{path.relative_to(_BACKEND)}:{node.lineno}"


def test_every_text_has_a_dutch_entry_with_the_same_placeholders():
    problems = []
    for text, where in _texts():
        dutch = NL.get(text, text)
        if text not in NL and not _PLACEHOLDER.sub("", text).isascii():
            problems.append(f"{where}: no Dutch for {text!r}")
        if sorted(set(_PLACEHOLDER.findall(text))) != sorted(set(_PLACEHOLDER.findall(dutch))):
            problems.append(f"{where}: placeholders differ in {text!r}")
    assert not problems, "\n".join(problems)


def test_every_text_in_code_is_translated():
    missing = sorted({text for text, _ in _texts() if text not in NL})
    assert not missing, f"add these to domain/i18n_nl.py: {missing}"


def test_tr_follows_the_request_locale():
    token = set_locale("en")
    try:
        assert current_locale() == "en"
        assert tr("Account {0} does not exist.", 7) == "Account 7 does not exist."
    finally:
        reset_locale(token)
    token = set_locale("nl")
    try:
        assert tr("Account {0} does not exist.", 7) == "Rekening 7 bestaat niet."
    finally:
        reset_locale(token)
    # anything else is the default, Dutch
    token = set_locale("fr")
    try:
        assert current_locale() == "nl"
    finally:
        reset_locale(token)


def _login(client, username="alice", password="alicepw"):
    assert client.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200


def test_the_api_answers_in_the_language_of_x_locale(client):
    _login(client)
    english = client.get("/api/accounts/999999/balances", headers={"X-Locale": "en"})
    dutch = client.get("/api/accounts/999999/balances", headers={"X-Locale": "nl"})
    assert english.status_code == dutch.status_code == 404
    assert english.json()["detail"] == "Account 999999 does not exist."
    assert dutch.json()["detail"] == "Rekening 999999 bestaat niet."


def test_the_language_is_stored_with_the_account(client):
    _login(client)
    assert client.get("/api/auth/me").json()["locale"] is None
    assert client.put("/api/auth/me/locale", json={"locale": "en"}).status_code == 200
    assert client.get("/api/auth/me").json()["locale"] == "en"
    refused = client.put("/api/auth/me/locale", json={"locale": "fr"}, headers={"X-Locale": "en"})
    assert refused.status_code == 422 and refused.json()["code"] == "invalid_locale"
    assert refused.json()["detail"] == "The language is one of nl, en."
