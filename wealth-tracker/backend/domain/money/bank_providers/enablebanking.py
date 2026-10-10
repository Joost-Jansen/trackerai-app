"""
Enable Banking: account information through the European payment services
directive (PSD2).

Enable Banking is a licensed provider that, on your behalf and with your
consent, fetches balances and transactions at your bank. Every user of this
app registers their own application there (the free restricted mode can only
reach the accounts of whoever registered it) and gives the app their app ID
and private key. That key signs every request; here it is only used, it is
stored in bank_link.py.

The flow, as Enable Banking prescribes it:

    GET  /aspsps                        which banks there are
    POST /auth                          start consent → an address at the bank
    (the user approves at their bank and comes back with a `code`)
    POST /sessions                      code → session with the accounts
    GET  /accounts/{uid}/balances       balances
    GET  /accounts/{uid}/transactions   transactions, in pages
    DELETE /sessions/{id}               revoke consent

Read-only: this file has no payment function at all.
"""

import os
import time
from urllib.parse import quote
from datetime import date

import jwt
import requests
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from domain.money.bank_providers import base
from domain.i18n import tr

PROVIDER = "enablebanking"
BASE_URL = os.environ.get("ENABLEBANKING_API_URL", "https://api.enablebanking.com")

# Preference when there are several balances: the booked closing balance first,
# then the booked interim balance, and only after that what is available (that
# counts an overdraft or a reserved payment differently from your account itself).
_BALANCE_PREFERENCE = ("CLBD", "ITBD", "CLAV", "ITAV", "XPCD", "OPBD", "OTHR", "INFO")


class ErrorNote(Exception):
    """Enable Banking or the bank refused; the message says why."""


def verify_key(pem: bytes) -> None:
    """ValueError if this is not a usable RSA private key."""
    try:
        key = load_pem_private_key(pem, password=None)
    except Exception as e:
        raise ValueError(tr("This is not a valid private key. Upload the .pem file Enable Banking downloaded when you registered your application.")) from e
    if key.key_size < 2048:
        raise ValueError(tr("This key is too short."))


class Client:
    def __init__(self, app_id: str, private_key_pem: bytes, http=None):
        self.app_id = app_id
        self._key = private_key_pem
        # The module itself, unless a test puts something else in its place.
        self._http = http or requests

    def _token(self) -> str:
        now = int(time.time())
        return jwt.encode(
            {"iss": "enablebanking.com", "aud": "api.enablebanking.com", "iat": now, "exp": now + 3600},
            self._key, algorithm="RS256", headers={"kid": self.app_id},
        )

    def _ask(self, method: str, path: str, **kwargs) -> dict:
        try:
            answer = self._http.request(
                method, f"{BASE_URL}{path}",
                headers={"Authorization": f"Bearer {self._token()}"}, timeout=30, **kwargs,
            )
        except requests.RequestException as e:
            raise ErrorNote(tr("Enable Banking can't be reached: {0}", e)) from e
        if answer.status_code >= 400:
            try:
                content = answer.json()
                message = content.get("message") or content.get("detail") or content.get("error") or answer.text
            except ValueError:
                message = answer.text
            raise ErrorNote(f"Enable Banking antwoordde {answer.status_code}: {message}")
        return answer.json() if answer.content else {}

    def banks(self, country: str) -> list[dict]:
        return self._ask("GET", "/aspsps", params={"country": country, "psu_type": "personal"}).get("aspsps", [])

    def start(self, *, bank: str, country: str, redirect_url: str, state: str, valid_until: str) -> dict:
        return self._ask("POST", "/auth", json={
            "access": {"valid_until": valid_until},
            "aspsp": {"name": bank, "country": country},
            "state": state,
            "redirect_url": redirect_url,
            "psu_type": "personal",
        })

    def session(self, code: str) -> dict:
        return self._ask("POST", "/sessions", json={"code": code})

    def balances(self, uid: str) -> list[dict]:
        return self._ask("GET", f"/accounts/{quote(str(uid), safe='')}/balances").get("balances", [])

    def transactions(self, uid: str, from_date: str) -> list[dict]:
        off: list[dict] = []
        follow_up = None
        while True:
            params = {"date_from": from_date}
            if follow_up:
                params["continuation_key"] = follow_up
            page = self._ask("GET", f"/accounts/{quote(str(uid), safe='')}/transactions", params=params)
            off.extend(page.get("transactions", []))
            follow_up = page.get("continuation_key")
            if not follow_up:
                return off

    def stop(self, session_id: str) -> None:
        self._ask("DELETE", f"/sessions/{quote(str(session_id), safe='')}")


def to_rule(tx: dict, account_iban: str | None) -> dict | None:
    """An Enable Banking transaction as a normalised bank row (see bank_providers/base.py).

    None for what is not booked yet: a reservation can still change or lapse,
    and would then stay there twice or wrong.
    """
    if tx.get("status") not in (None, "BOOK"):
        return None
    try:
        amount = abs(float((tx.get("transaction_amount") or {}).get("amount")))
    except (TypeError, ValueError):
        return None
    off = tx.get("credit_debit_indicator") == "DBIT"
    # Spending positive, as everywhere in the books.
    amount = amount if off else -amount

    counterparty = (tx.get("creditor") if off else tx.get("debtor")) or {}
    counter_account = (tx.get("creditor_account") if off else tx.get("debtor_account")) or {}
    description = " ".join(s for s in (tx.get("remittance_information") or []) if s).strip()
    if not description:
        description = tx.get("note") or ((tx.get("bank_transaction_code") or {}).get("description")) or ""
    name = (counterparty.get("name") or "").strip() or description[:80]
    date = tx.get("booking_date") or tx.get("value_date") or tx.get("transaction_date")
    if not date:
        return None
    balance_after = (tx.get("balance_after_transaction") or {}).get("amount")

    return {
        "date": date[:10],
        "interest_date": tx.get("value_date"),
        "amount": amount,
        "currency": (tx.get("transaction_amount") or {}).get("currency") or base.CURRENCY,
        "name": name,
        # Without an IBAN (a savings account at the same bank) the account number the
        # bank does give: that is how accounts.py recognises the savings account.
        "counterparty_iban": base.normalise_iban(
            counter_account.get("iban") or (counter_account.get("other") or {}).get("identification")
            or counter_account.get("bban")),
        "description": description,
        "account_iban": account_iban,
        "code": (tx.get("bank_transaction_code") or {}).get("code"),
        "kind": (tx.get("bank_transaction_code") or {}).get("description"),
        "balance_after": float(balance_after) if balance_after not in (None, "") else None,
        # A reference from the bank keeps two equal bookings on one day apart the next
        # time they are fetched.
        "hash_extra": f"eb:{tx.get('entry_reference') or tx.get('transaction_id') or ''}",
        "raw": tx,
    }


def chosen_balance(balances: list[dict], today: str | None = None,
                  transactions: list[dict] | None = None) -> tuple[str, float] | None:
    """(date, amount) of the balance that best says what is on the account.

    The "expected" balance (XPCD) counts payments that are still pending — ING
    gives nothing else. The app only stores booked transactions, and those only
    come in on the day of booking. A card payment from last night was then
    already in the balance and only tomorrow in the transactions, and the balance
    did not match the transactions for a day. If the bank includes the payments
    that are still pending (`transactions` with status PDNG), they are counted
    back here, so the stored balance is the booked one. If it does not include
    them, accounts.restore_pending corrects the balance once they are booked.
    """
    rang = {kind: i for i, kind in enumerate(_BALANCE_PREFERENCE)}
    candidates = [s for s in balances if (s.get("balance_amount") or {}).get("amount") not in (None, "")]
    if not candidates:
        return None
    best = min(candidates, key=lambda s: rang.get(s.get("balance_type"), len(rang)))
    on_date = (best.get("reference_date") or today or date.today().isoformat())[:10]
    amount = float(best["balance_amount"]["amount"])
    if best.get("balance_type") == "XPCD":
        amount = round(amount + _pending(transactions or []), 2)
    return on_date, amount


def _pending(transactions: list[dict]) -> float:
    """What not yet booked transactions did to the balance, reversed: a debit that
    is pending comes back onto the booked balance.
    """
    back = 0.0
    for tx in transactions:
        if tx.get("status") != "PDNG":
            continue
        try:
            amount = abs(float((tx.get("transaction_amount") or {}).get("amount")))
        except (TypeError, ValueError):
            continue
        back += amount if tx.get("credit_debit_indicator") == "DBIT" else -amount
    return back
