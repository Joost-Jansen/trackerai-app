"""
Your own share of shared costs.

Money that passes through your hands for a group goes in "Niet meetellen": the
friends pay you ahead, you pay the boat, they get their deposit back. None of it
is income or spending. But inside that pot is your own share: whatever you paid
out more than you received. Without this module it counts nowhere.

The running sum of "Niet meetellen" (spending sign: out positive) tells both
sides apart, the same way net_worth.py does for the debt to friends:

  below zero   you hold money of others: a debt (net_worth.series)
  above zero   you paid more than you got: your own share of the costs

Every change in the part above zero is booked as spending in the category the
user picks in Settings (default: the holiday category, the usual reason for such
a pot), on the day it happens. Paying the boat ahead raises it, friends paying
you back lowers it again, so over the whole pot exactly your share remains.

These are derived rows, not stored transactions: the Spending page and Net worth
read them, labelling and editing never see them.
"""

import sqlite3

from domain import preferences
from domain.i18n import tr
from domain.money import accounts

DEFAULT_CATEGORY = "Vakantie"
PREFERENCE = "shared_costs"


def category(conn: sqlite3.Connection) -> str | None:
    """Where your share goes, or None when it should count nowhere.

    Not set: the default category, if it exists as a spending category. A
    choice that no longer exists (renamed, removed) counts as nowhere rather
    than as a guess."""
    chosen = preferences.read(conn, PREFERENCE)
    name = chosen.get("category") if chosen is not None else DEFAULT_CATEGORY
    if not name:
        return None
    row = conn.execute("SELECT 1 FROM categories WHERE name = ? AND type = 'EXPENSE'", (name,)).fetchone()
    return name if row else None


def _accounts_in_net_worth(conn: sqlite3.Connection) -> list[int]:
    """The accounts net_worth.series counts: active, with a stack and a balance."""
    from domain.money import net_worth   # net_worth imports this module's neighbours

    with_balance = {r["account_id"] for r in conn.execute("SELECT DISTINCT account_id FROM account_balances")}
    return sorted(r["id"] for r in accounts.load_accounts(conn, only_active=True)
                  if net_worth.stack_of(r["kind"]) and r["id"] in with_balance)


def own_share_rows(conn: sqlite3.Connection) -> list[dict]:
    """The derived spending rows, in the same shape as bank_transactions.load.

    One row per day on which your share changed, on the account of that day's
    last pot transaction. Empty when the setting says nowhere."""
    from domain.money.categorization import EXCLUDE

    name = category(conn)
    ids = _accounts_in_net_worth(conn)
    if name is None or not ids:
        return []
    places = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""SELECT date, account_id, amount FROM bank_transactions_typed
            WHERE category_effective = ? AND account_id IN ({places})
            ORDER BY date, id""",
        (EXCLUDE, *ids),
    ).fetchall()
    group = conn.execute("SELECT group_name FROM categories WHERE name = ?", (name,)).fetchone()

    per_day: dict[str, dict] = {}
    running = 0.0
    for r in rows:
        before = max(0.0, running)
        running += r["amount"]
        change = max(0.0, running) - before
        day = per_day.setdefault(r["date"], {"amount": 0.0, "account_id": r["account_id"]})
        day["amount"] += change
        day["account_id"] = r["account_id"]

    out = []
    for i, (d, day) in enumerate(sorted(per_day.items())):
        if abs(day["amount"]) < 0.005:
            continue
        out.append({
            # Negative ids: never a real transaction, and nothing can act on it.
            "id": -(i + 1),
            "account_id": day["account_id"],
            "date": d,
            "amount": round(day["amount"], 2),
            "name": tr("Your share of shared costs"),
            "description": tr("Calculated from “Niet meetellen”: what you paid more than you received."),
            "counterparty_iban": None,
            "category_auto": None,
            "category_manual": None,
            "category_source": None,
            "category": name,
            "group_name": group["group_name"] if group else None,
            "type": "EXPENSE",
            "source": "derived",
            "raw": {},
        })
    return out
