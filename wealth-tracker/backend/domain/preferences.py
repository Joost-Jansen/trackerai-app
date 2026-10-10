"""
preferences.py — how you set up a screen, stored with your account.

For now one thing: which charts are on Spending → Overview, in which order, and
with which settings per chart. With your account and not in your browser, so
your phone shows the same overview as your laptop.

Only known keys, and the content is a JSON object of limited size: what the
frontend puts in, it reads back itself. No setting here changes a number; it
is only the display.
"""

import json
import sqlite3

from domain import database
from domain.i18n import tr

# ai_labelling: {"on": bool} — whether Claude may help with what the rules do
# not recognise (ai_labelling.py). Off by default: it sends data out.
# shared_costs: {"category": str | None} — where your own share of the
# "Niet meetellen" pot counts as spending (shared_costs.py); None is nowhere.
KEYS = ("spending_overview", "ai_labelling", "shared_costs")
MAX_BYTES = 16 * 1024
_PREFIX = "preference:"


class UnknownKey(KeyError):
    pass


def read(conn: sqlite3.Connection, key: str) -> dict | None:
    if key not in KEYS:
        raise UnknownKey(key)
    raw = database.load_setting(conn, _PREFIX + key)
    try:
        value = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def put(conn: sqlite3.Connection, key: str, value: dict | None) -> None:
    """Stores the preference; None removes it (back to the default)."""
    if key not in KEYS:
        raise UnknownKey(key)
    if value is None:
        conn.execute("DELETE FROM settings WHERE key = ?", (_PREFIX + key,))
        conn.commit()
        return
    if not isinstance(value, dict):
        raise ValueError(tr("A preference is an object."))
    text = json.dumps(value, ensure_ascii=False)
    if len(text.encode()) > MAX_BYTES:
        raise ValueError(tr("This preference is too large."))
    database.save_setting(conn, _PREFIX + key, text)
