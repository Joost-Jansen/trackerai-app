"""
Tests for bank_providers/enablebanking.py and secret_box.py — without Enable Banking itself.

Every request goes to a simulated server; the key is generated per test. No
real request leaves the machine and there is no real key in this repo.
"""

import os
import stat

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from domain import secret_box as secret
from domain.money.bank_providers import enablebanking


@pytest.fixture(scope="module")
def key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return pem, key.public_key()


class _Answer:
    def __init__(self, data, status=200):
        self.status_code, self._data = status, data
        self.content = b"x"
        self.text = str(data)

    def json(self):
        return self._data


class _Server:
    def __init__(self, answers):
        self.answers = list(answers)
        self.requests = []

    def request(self, method, url, headers=None, params=None, json=None, timeout=None):
        self.requests.append({"method": method, "url": url, "headers": headers, "params": params, "json": json})
        return self.answers.pop(0)


# ---------------------------------------------------------------------------
# Signing
# ---------------------------------------------------------------------------


def test_every_request_is_signed_with_the_own_key(key):
    pem, is_public = key
    server = _Server([_Answer({"aspsps": []})])
    enablebanking.Client("app-123", pem, http=server).banks("NL")

    token = server.requests[0]["headers"]["Authorization"].removeprefix("Bearer ")
    assert jwt.get_unverified_header(token)["kid"] == "app-123"
    claims = jwt.decode(token, is_public, algorithms=["RS256"], audience="api.enablebanking.com")
    assert claims["iss"] == "enablebanking.com"
    assert claims["exp"] - claims["iat"] == 3600


def test_an_invalid_key_is_refused_at_once():
    with pytest.raises(ValueError):
        enablebanking.verify_key(b"-----BEGIN NOT A KEY-----\nabc\n-----END NOT A KEY-----\n")


def test_a_refusal_becomes_a_readable_error(key):
    server = _Server([_Answer({"message": "Invalid application"}, status=401)])
    with pytest.raises(enablebanking.ErrorNote, match="Invalid application"):
        enablebanking.Client("app", key[0], http=server).banks("NL")


def test_transactions_come_in_pages(key):
    server = _Server(
        [
            _Answer({"transactions": [{"entry_reference": "1"}], "continuation_key": "k2"}),
            _Answer({"transactions": [{"entry_reference": "2"}], "continuation_key": None}),
        ]
    )
    txs = enablebanking.Client("app", key[0], http=server).transactions("uid-1", "2026-01-01")
    assert [t["entry_reference"] for t in txs] == ["1", "2"]
    assert server.requests[1]["params"]["continuation_key"] == "k2"


# ---------------------------------------------------------------------------
# From Enable Banking to a bank row
# ---------------------------------------------------------------------------


def _tx(**remaining):
    tx = {
        "entry_reference": "ref-1",
        "status": "BOOK",
        "booking_date": "2026-09-10",
        "value_date": "2026-09-10",
        "transaction_amount": {"currency": "EUR", "amount": "42.50"},
        "credit_debit_indicator": "DBIT",
        "creditor": {"name": "SUPERMARKT 1 BV"},
        "creditor_account": {"iban": "NL00BANK0000000001"},
        "debtor": {"name": "A. Voorbeeld"},
        "debtor_account": {"iban": "NL00BANK0000000002"},
        "remittance_information": ["Boodschappen", "week 37"],
    }
    tx.update(remaining)
    return tx


def test_a_debit_is_a_positive_expense_at_the_payee():
    rule = enablebanking.to_rule(_tx(), "NL00BANK0000000002")
    assert rule["amount"] == 42.5
    assert rule["name"] == "SUPERMARKT 1 BV"
    assert rule["counterparty_iban"] == "NL00BANK0000000001"
    assert rule["description"] == "Boodschappen week 37"
    assert rule["date"] == "2026-09-10"


def test_a_credit_is_negative_from_the_payer():
    rule = enablebanking.to_rule(_tx(credit_debit_indicator="CRDT"), "NL00BANK0000000001")
    assert rule["amount"] == -42.5
    assert rule["name"] == "A. Voorbeeld"
    assert rule["counterparty_iban"] == "NL00BANK0000000002"


def test_what_is_not_booked_yet_does_not_count():
    assert enablebanking.to_rule(_tx(status="PDNG"), None) is None


def test_without_a_name_the_description_becomes_the_name():
    rule = enablebanking.to_rule(_tx(creditor=None), None)
    assert rule["name"] == "Boodschappen week 37"


def test_the_booked_balance_comes_first():
    balances = [
        {"balance_type": "ITAV", "balance_amount": {"amount": "900.00"}, "reference_date": "2026-09-12"},
        {"balance_type": "CLBD", "balance_amount": {"amount": "1000.00"}, "reference_date": "2026-09-11"},
    ]
    assert enablebanking.chosen_balance(balances) == ("2026-09-11", 1000.0)


def test_an_expected_balance_takes_back_what_is_still_pending():
    """ING only gives XPCD: it already includes card payments that are not booked yet."""
    balances = [{"balance_type": "XPCD", "balance_amount": {"amount": "305.80"}}]
    txs = [
        {"status": "PDNG", "transaction_amount": {"amount": "34.08"}, "credit_debit_indicator": "DBIT"},
        {"status": "PDNG", "transaction_amount": {"amount": "10.00"}, "credit_debit_indicator": "CRDT"},
        {"status": "BOOK", "transaction_amount": {"amount": "4.00"}, "credit_debit_indicator": "DBIT"},
    ]
    assert enablebanking.chosen_balance(balances, "2026-09-14", txs) == ("2026-09-14", 329.88)
    # A booked balance already leaves them out.
    booked = [{"balance_type": "CLBD", "balance_amount": {"amount": "100"}, "reference_date": "2026-09-14"}]
    assert enablebanking.chosen_balance(booked, None, txs) == ("2026-09-14", 100.0)


def test_without_a_date_on_the_balance_today_counts():
    assert enablebanking.chosen_balance([{"balance_type": "OTHR", "balance_amount": {"amount": "5"}}], "2026-09-13") == ("2026-09-13", 5.0)


# ---------------------------------------------------------------------------
# Encrypting
# ---------------------------------------------------------------------------


@pytest.fixture()
def datamap(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("APP_ENCRYPTION_KEY", raising=False)
    return tmp_path


def test_encrypt_and_back(datamap):
    token = secret.encrypt(b"geheime sleutel")
    assert b"geheime sleutel" not in token.encode()
    assert secret.decrypt(token) == b"geheime sleutel"


def test_without_an_environment_key_the_server_makes_one_for_the_owner_only(datamap):
    secret.encrypt(b"x")
    path = datamap / ".encryption_key"
    assert path.exists()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    first = path.read_bytes()
    secret.encrypt(b"y")
    assert path.read_bytes() == first, "hergebruikt, niet elke keer een nieuwe"


def test_a_key_file_with_its_old_name_keeps_working(datamap):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    (datamap / ".versleutelsleutel").write_bytes(key)
    token = Fernet(key).encrypt(b"from before").decode()
    assert secret.decrypt(token) == b"from before"
    assert (datamap / ".encryption_key").read_bytes() == key
    assert not (datamap / ".versleutelsleutel").exists()


def test_a_key_from_the_environment_comes_first(datamap, monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    token = secret.encrypt(b"z")
    assert not (datamap / ".encryption_key").exists()
    assert secret.decrypt(token) == b"z"


def test_with_another_key_it_is_unreadable(datamap, monkeypatch):
    import os

    from cryptography.fernet import Fernet

    from domain import database

    token = secret.encrypt(b"z")
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    # While the old key file is there it is still tried (taking over, see
    # tests/test_encryption_key.py); without it the data is unreadable.
    os.remove(os.path.join(database.data_root(), ".encryption_key"))
    with pytest.raises(secret.Unreadable):
        secret.decrypt(token)


def test_without_iban_the_counterparty_account_number_counts():
    """A savings account at the same bank sometimes has no IBAN in the connection;
    the number is how accounts.py recognises it.
    """
    rule = enablebanking.to_rule(_tx(creditor_account={"other": {"identification": "H12284579", "scheme_name": "BBAN"}}), None)
    assert rule["counterparty_iban"] == "H12284579"
