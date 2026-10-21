"""
onboarding.py — where a user stands: for the welcome flow and Help.

Two things:

  * **What you track**: investments (DeGiro), money (bank, savings, debts) or
    both — chosen the first time, and changeable later. With the choice the
    tour gets only the steps that apply to you.
  * **Whether the welcome flow is done.** With your account, not in your
    browser: someone who carries on on their phone does not get it again.

Plus your status per part, from your own data: what you have already done and
what is still possible. An existing user with data but without a stored choice
does not need the flow; their choice follows from what they already have.
"""

import json
import sqlite3

from domain import database, db
from domain.i18n import tr
from domain.money import accounts, categorization

CHOICES = ("investments", "money", "both")
# How bank data comes in: exports only, or exports plus the automatic bank
# connection (Enable Banking) on top. The tour's Money part follows it.
BANK_CHOICES = ("upload", "connect")
_KEY = "onboarding"


def _tally(conn: sqlite3.Connection, sql: str) -> int:
    try:
        return conn.execute(sql).fetchone()[0] or 0
    except db.OperationalError:
        return 0  # the table does not exist (yet) in an old database


def status(conn: sqlite3.Connection) -> dict:
    """Per part, what is already there."""
    active = accounts.load_accounts(conn, only_active=True)
    with_balance = {r[0] for r in conn.execute("SELECT DISTINCT account_id FROM account_balances")}
    return {
        "portfolio": {
            "transactions": _tally(conn, "SELECT COUNT(*) FROM transactions"),
            "dividends": _tally(conn, "SELECT COUNT(*) FROM dividends"),
        },
        "money": {
            "accounts": len(active),
            "without_balance": sorted(r["name"] for r in active if r["id"] not in with_balance),
            "bank_transactions": _tally(conn, "SELECT COUNT(*) FROM bank_transactions"),
            "linked": _tally(conn, "SELECT COUNT(*) FROM bank_consents WHERE status = 'active'") > 0,
            "unlabelled": categorization.unknown_count(conn),
        },
    }


def read(conn: sqlite3.Connection) -> dict:
    """{choice, done, status}."""
    st = status(conn)
    stored = database.load_setting(conn, _KEY)
    try:
        stand = json.loads(stored) if stored else None
    except json.JSONDecodeError:
        stand = None
    if not isinstance(stand, dict):
        # Never chosen: someone who already has data is already on their way.
        invests = st["portfolio"]["transactions"] > 0
        funds = st["money"]["bank_transactions"] > 0 or st["money"]["accounts"] > 0
        choice = "both" if invests and funds else "investments" if invests else "money" if funds else None
        stand = {"choice": choice, "done": invests or funds}
    choice = stand.get("choice") if stand.get("choice") in CHOICES else None
    step = stand.get("step") if isinstance(stand.get("step"), int) and stand.get("step") >= 0 else 0
    bank = stand.get("bank") if stand.get("bank") in BANK_CHOICES else None
    return {"choice": choice, "bank": bank, "done": bool(stand.get("done")), "step": step, "status": st}


def put(conn: sqlite3.Connection, **fields) -> None:
    """Updates only the given fields: `choice`, `done` and `step` (where you are in
    the tour, so you carry on where you were).
    """
    current = read(conn)
    new = {"choice": current["choice"], "bank": current["bank"], "done": current["done"], "step": current["step"]}
    if "choice" in fields:
        if fields["choice"] not in (*CHOICES, None):
            raise ValueError(tr("Choose from: {0}.", ", ".join(CHOICES)))
        new["choice"] = fields["choice"]
    if "bank" in fields:
        if fields["bank"] not in (*BANK_CHOICES, None):
            raise ValueError(tr("Choose from: {0}.", ", ".join(BANK_CHOICES)))
        new["bank"] = fields["bank"]
    if "done" in fields:
        new["done"] = bool(fields["done"])
    if "step" in fields:
        if not isinstance(fields["step"], int) or isinstance(fields["step"], bool) or fields["step"] < 0:
            raise ValueError(tr("A step is a number from 0."))
        new["step"] = fields["step"]
    database.save_setting(conn, _KEY, json.dumps(new))
