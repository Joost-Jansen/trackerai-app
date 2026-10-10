"""
/api/connections — connecting a bank directly through Enable Banking.

Against a simulated Enable Banking server, with a key generated per test.
Covered: the key never comes out again, consent goes through a one-time state,
accounts are recognised or created by IBAN, fetching duplicates nothing (also
not next to an earlier CSV import), and everyone sees only their own
connection.
"""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from domain.money.bank_providers import enablebanking

IBAN = "NL00BANK0000000009"
APP = "https://app.voorbeeld.nl"


@pytest.fixture(autouse=True)
def _public_origin(monkeypatch):
    """The app's public address, as PUBLIC_ORIGINS sets it in production."""
    from app.core import config

    monkeypatch.setattr(config, "PUBLIC_ORIGINS", [APP])


@pytest.fixture(scope="module")
def pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


@pytest.fixture(autouse=True)
def _own_encryption_key(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())


class _Answer:
    def __init__(self, data, status=200):
        self.status_code, self._data, self.content, self.text = status, data, b"x", str(data)

    def json(self):
        return self._data


def _tx(ref, date, amount, dbit=True, status="BOOK", name="WINKEL 1 BV"):
    return {"entry_reference": ref, "status": status, "booking_date": date,
            "transaction_amount": {"currency": "EUR", "amount": f"{amount:.2f}"},
            "credit_debit_indicator": "DBIT" if dbit else "CRDT",
            "creditor": {"name": name}, "debtor": {"name": "A. VOORBEELD"},
            "remittance_information": [f"betaling {ref}"]}


IBAN2 = "NL00BANK0000000017"
# Per bank the account it hands over after consent.
_ACCOUNT = {"Voorbeeldbank": ("acc-1", IBAN), "Tweede Bank": ("acc-2", IBAN2)}


class _Bank:
    """A simulated Enable Banking with two banks, each with one account."""

    def __init__(self):
        self.requests = []
        self.sessions = 0
        self.last_bank = None
        self.transactions = [
            _tx("1", "2026-09-01", 10.0), _tx("2", "2026-09-02", 20.0),
            _tx("3", "2026-09-03", 5.0, status="PDNG"),
        ]

    def request(self, method, url, headers=None, params=None, json=None, timeout=None):
        path = url.removeprefix(enablebanking.BASE_URL)
        self.requests.append((method, path, params, json))
        if path == "/aspsps":
            return _Answer({"aspsps": [{"name": name, "country": "NL", "maximum_consent_validity": 90 * 86400}
                                         for name in _ACCOUNT]})
        if path == "/auth":
            self.last_bank = json["aspsp"]["name"]
            return _Answer({"url": "https://bank.voorbeeld/toestemming", "authorization_id": "a1"})
        if path == "/sessions":
            self.sessions += 1
            uid, iban = _ACCOUNT[self.last_bank]
            return _Answer({"session_id": f"s{self.sessions}", "access": {"valid_until": "2099-01-01T00:00:00+00:00"},
                              "accounts": [{"uid": uid, "account_id": {"iban": iban}, "currency": "EUR"}]})
        if path.endswith("/balances"):
            return _Answer({"balances": [{"balance_type": "CLBD", "balance_amount": {"amount": "1234.56"},
                                            "reference_date": "2026-09-03"}]})
        if path.endswith("/transactions"):
            from_date = params["date_from"]
            return _Answer({"transactions": [t for t in self.transactions if t["booking_date"] >= from_date]})
        if method == "DELETE":
            return _Answer({})
        return _Answer({"message": "unknown"}, status=404)


@pytest.fixture()
def bank(monkeypatch):
    fake = _Bank()
    monkeypatch.setattr(enablebanking, "requests", fake)
    return fake


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _set_up(client, pem, app_id="app-123"):
    return client.put("/api/connections/enablebanking", data={"app_id": app_id},
                      files={"key": ("app-123.pem", pem, "application/x-pem-file")})


def _link(client, bank="Voorbeeldbank"):
    r = client.post("/api/connections/enablebanking/start",
                    json={"bank": bank, "country": "NL", "origin": APP})
    assert r.status_code == 200, r.text
    state = client._last_state  # set by captured_state
    return client.get(f"/api/connections/enablebanking/callback?state={state}&code=c1", follow_redirects=False)


@pytest.fixture()
def captured_state(client, bank):
    """Remembers the state the app sends to the (fake) bank, as the real bank sends
    it back after consent.
    """
    original = bank.request

    def trap(method, url, **kw):
        if url.endswith("/auth"):
            client._last_state = kw["json"]["state"]
        return original(method, url, **kw)

    bank.request = trap
    return client


# ---------------------------------------------------------------------------

def test_without_a_session_nothing(client):
    assert client.get("/api/connections").status_code == 401


def test_the_key_never_comes_out_again(client, pem):
    _login(client)
    r = _set_up(client, pem)
    assert r.status_code == 200, r.text
    text = r.text + client.get("/api/connections").text
    assert "PRIVATE KEY" not in text and "key" not in r.json()
    assert r.json()["configured"] is True and r.json()["app_id"] == "app-123"


def test_an_invalid_file_is_refused(client):
    _login(client)
    assert _set_up(client, b"geen sleutel").status_code == 400


def test_without_an_app_id_refused(client, pem):
    _login(client)
    assert _set_up(client, pem, app_id="  ").status_code == 400


def test_connecting_without_setup_says_what_is_missing(client, bank):
    _login(client)
    r = client.post("/api/connections/enablebanking/start", json={"bank": "Voorbeeldbank", "origin": APP})
    assert r.status_code == 409


def test_the_bank_redirects_to_the_apps_own_address(client, pem, bank):
    _login(client)
    _set_up(client, pem)
    r = client.post("/api/connections/enablebanking/start", json={"bank": "Voorbeeldbank", "country": "NL", "origin": APP})
    assert r.json()["url"] == "https://bank.voorbeeld/toestemming"
    auth = next(v for v in bank.requests if v[1] == "/auth")[3]
    assert auth["redirect_url"] == f"{APP}/api/connections/enablebanking/callback"
    assert auth["access"]["valid_until"]


def test_a_foreign_address_is_refused(client, pem, bank):
    _login(client)
    _set_up(client, pem)
    r = client.post("/api/connections/enablebanking/start",
                    json={"bank": "Voorbeeldbank", "origin": "http://kwaadwillend.example/path"})
    assert r.status_code == 400


def test_back_from_the_bank_links_the_account_and_fetches(captured_state, pem, bank):
    client = captured_state
    _login(client)
    _set_up(client, pem)
    r = _link(client)
    assert r.status_code == 303
    assert r.headers["location"].startswith(f"{APP}/accounts/connect?gelukt=1")

    account = next(x for x in client.get("/api/accounts").json()["accounts"] if x["iban"] == IBAN)
    assert account["balance"] == 1234.56
    txs = [t for t in client.get("/api/bank-transactions").json()["transactions"] if t["account_id"] == account["id"]]
    assert sorted(t["amount"] for t in txs) == [10.0, 20.0], "de nog niet geboekte telt niet"

    status = client.get("/api/connections").json()["consents"][0]
    assert status["status"] == "active" and status["accounts"][0]["id"] == account["id"]
    assert status["valid_until"].startswith("2099-01-01"), "wat de bank zegt, niet wat we vroegen"
    assert "state" not in status and "session_id" not in status


def test_fetching_again_duplicates_nothing(captured_state, pem, bank):
    client = captured_state
    _login(client)
    _set_up(client, pem)
    _link(client)
    bank.transactions.append(_tx("4", "2026-09-04", 7.5))
    report = client.post("/api/connections/enablebanking/fetch").json()
    assert report["added"] == 1
    assert client.post("/api/connections/enablebanking/fetch").json()["added"] == 0


def test_next_to_an_earlier_csv_import_nothing_doubles(captured_state, pem, bank):
    """First an export uploaded up to and including the 2nd, then connected: the 2nd
    itself does not come in again, what came after does.
    """
    client = captured_state
    _login(client)
    header = '"Date","Interest Date","Amount","Account","Counterparty","Name","Description"'
    csv = "\n".join([header, f'"2026-09-02","2026-09-02","-20,00","{IBAN}","","WINKEL 1","andere omschrijving"']) + "\n"
    assert client.post("/api/uploads/bank", files=[("files", ("bank.csv", csv.encode(), "text/csv"))]).status_code == 200
    bank.transactions.append(_tx("4", "2026-09-04", 7.5))
    _set_up(client, pem)
    _link(client)

    account = next(x for x in client.get("/api/accounts").json()["accounts"] if x["iban"] == IBAN)
    amounts = sorted(t["amount"] for t in client.get("/api/bank-transactions").json()["transactions"]
                      if t["account_id"] == account["id"])
    assert amounts == [7.5, 20.0], "de 2e één keer, de 1e ligt vóór de export en de 4e is nieuw"


def test_a_csv_after_connecting_adds_only_what_was_not_there_yet(captured_state, pem, bank):
    """The other way round: first connected, then an export of the same account with
    an overlap and an older booking. The overlap does not come twice, the older one
    does come.
    """
    client = captured_state
    _login(client)
    _set_up(client, pem)
    _link(client)
    header = '"Date","Interest Date","Amount","Account","Counterparty","Name","Description"'
    csv = "\n".join([header,
                     f'"2026-08-20","2026-08-20","-3,00","{IBAN}","","KOFFIE 1","ouder"',
                     f'"2026-09-01","2026-09-01","-10,00","{IBAN}","","WINKEL 1","andere tekst"',
                     f'"2026-09-02","2026-09-02","-20,00","{IBAN}","","WINKEL 1","andere tekst"']) + "\n"
    r = client.post("/api/uploads/bank", files=[("files", ("bank.csv", csv.encode(), "text/csv"))])
    res = r.json()["results"][0]
    assert (res["saved"], res["skipped"]) == (1, 2)

    account = next(x for x in client.get("/api/accounts").json()["accounts"] if x["iban"] == IBAN)
    amounts = sorted(t["amount"] for t in client.get("/api/bank-transactions").json()["transactions"]
                      if t["account_id"] == account["id"])
    assert amounts == [3.0, 10.0, 20.0]


def test_refusing_at_the_bank_comes_back_cleanly(captured_state, pem, bank):
    client = captured_state
    _login(client)
    _set_up(client, pem)
    client.post("/api/connections/enablebanking/start", json={"bank": "Voorbeeldbank", "country": "NL", "origin": APP})
    r = client.get(f"/api/connections/enablebanking/callback?state={client._last_state}&error=access_denied"
                   "&error_description=Geweigerd", follow_redirects=False)
    assert r.status_code == 303 and "error=Geweigerd" in r.headers["location"]
    assert client.get("/api/connections").json()["consents"][0]["status"] == "error"


def test_an_unknown_state_links_nothing(client, pem, bank):
    _login(client)
    _set_up(client, pem)
    r = client.get("/api/connections/enablebanking/callback?state=verzonnen&code=c1", follow_redirects=False)
    assert r.status_code == 303 and "error=" in r.headers["location"]
    assert not [x for x in client.get("/api/accounts").json()["accounts"] if x["iban"] == IBAN]


def test_revoking_reports_it_to_the_bank_and_keeps_the_data(captured_state, pem, bank):
    client = captured_state
    _login(client)
    _set_up(client, pem)
    _link(client)
    tid = client.get("/api/connections").json()["consents"][0]["id"]
    assert client.delete(f"/api/connections/enablebanking/consents/{tid}").status_code == 200
    assert ("DELETE", "/sessions/s1", None, None) in bank.requests
    assert client.get("/api/connections").json()["consents"] == []
    assert any(x["iban"] == IBAN for x in client.get("/api/accounts").json()["accounts"])


def test_on_open_only_what_is_outdated_is_fetched(captured_state, pem, bank):
    """Opening the app fetches with a threshold: just fetched → nothing asked at the
    bank. The button always fetches.
    """
    client = captured_state
    _login(client)
    _set_up(client, pem)
    _link(client)                     # fetches right away
    before = len(bank.requests)

    quiet = client.post("/api/connections/enablebanking/fetch?only_if_older_than_hours=6").json()
    assert quiet["skipped"] == 1 and quiet["accounts"] == 0
    assert len(bank.requests) == before, "geen verzoek aan de bank"

    button = client.post("/api/connections/enablebanking/fetch").json()
    assert button["skipped"] == 0 and button["accounts"] == 1


def test_two_banks_each_their_own_consent_and_accounts(captured_state, pem, bank):
    client = captured_state
    _login(client)
    _set_up(client, pem)
    _link(client, "Voorbeeldbank")
    _link(client, "Tweede Bank")
    consents = client.get("/api/connections").json()["consents"]
    assert {t["bank"]: t["status"] for t in consents} == {"Voorbeeldbank": "active", "Tweede Bank": "active"}
    assert {t["bank"]: [r["iban"] for r in t["accounts"]] for t in consents} == {
        "Voorbeeldbank": [IBAN], "Tweede Bank": [IBAN2]}


def test_back_from_the_bank_says_which_bank_it_was(captured_state, pem, bank):
    client = captured_state
    _login(client)
    _set_up(client, pem)
    assert "bank=Tweede+Bank" in _link(client, "Tweede Bank").headers["location"]


def test_reconnecting_replaces_the_old_consent_at_that_bank(captured_state, pem, bank):
    client = captured_state
    _login(client)
    _set_up(client, pem)
    _link(client)
    _link(client)
    consents = client.get("/api/connections").json()["consents"]
    assert [t["status"] for t in consents] == ["active"]
    assert consents[0]["accounts"][0]["iban"] == IBAN
    assert ("DELETE", "/sessions/s1", None, None) in bank.requests, "de oude sessie is bij de bank ingetrokken"
    assert ("DELETE", "/sessions/s2", None, None) not in bank.requests


def test_if_the_bank_does_not_say_until_when_what_we_asked_applies(captured_state, pem, bank):
    client = captured_state
    original = bank.request

    def without_end_date(method, url, **kw):
        answer = original(method, url, **kw)
        if url.endswith("/sessions"):
            answer._data.pop("access")
        return answer

    bank.request = without_end_date
    _login(client)
    _set_up(client, pem)
    _link(client)
    t = client.get("/api/connections").json()["consents"][0]
    from datetime import datetime, timedelta, timezone
    remaining = datetime.fromisoformat(t["valid_until"]) - datetime.now(timezone.utc)
    assert timedelta(days=89) < remaining <= timedelta(days=90), "de 90 dagen van de bank, niet de 180 van de EU"


def test_retrying_cleans_up_the_failed_attempt(captured_state, pem, bank):
    client = captured_state
    _login(client)
    _set_up(client, pem)
    client.post("/api/connections/enablebanking/start", json={"bank": "Voorbeeldbank", "country": "NL", "origin": APP})
    client.get(f"/api/connections/enablebanking/callback?state={client._last_state}&error=access_denied",
               follow_redirects=False)
    _link(client)
    assert [t["status"] for t in client.get("/api/connections").json()["consents"]] == ["active"]


def test_an_aborted_attempt_disappears_from_the_overview(client, pem, bank, monkeypatch):
    from domain.money import bank_link
    from datetime import timedelta

    _login(client)
    _set_up(client, pem)
    client.post("/api/connections/enablebanking/start", json={"bank": "Voorbeeldbank", "country": "NL", "origin": APP})
    assert client.get("/api/connections").json()["consents"][0]["status"] == "waiting"

    later = bank_link._now() + timedelta(hours=1)
    monkeypatch.setattr(bank_link, "_now", lambda: later)
    assert client.get("/api/connections").json()["consents"] == []


def test_everyone_their_own_connection(client, pem):
    _login(client)
    _set_up(client, pem)
    client.post("/api/auth/logout")
    _login(client, "bob", "bobpw")
    assert client.get("/api/connections").json()["configured"] is False


def test_the_return_address_must_be_this_site(client, pem, bank, captured_state):
    _login(client)
    _set_up(client, pem)
    r = client.post("/api/connections/enablebanking/start",
                    json={"bank": "Voorbeeldbank", "country": "NL", "origin": "https://evil.example"})
    assert r.status_code == 400
    # The host the request came to also counts (same origin, no PUBLIC_ORIGINS needed).
    r = client.post("/api/connections/enablebanking/start",
                    json={"bank": "Voorbeeldbank", "country": "NL", "origin": "https://testserver"})
    assert r.status_code == 200, r.text
