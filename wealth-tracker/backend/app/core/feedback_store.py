"""
Feedback from users: something broken, or an idea. One SQLite file for the
whole installation (data_root()/feedback.db), next to the per-user folders:
the admin reads everything in one place, and a user sees only their own reports
through the API (routers/feedback.py).

The path follows database.data_root(), so a test that redirects that folder
(see conftest.py) redirects this file too.
"""

import json
import os
import sqlite3
from datetime import UTC, datetime

from app.core.accounts import APP, linked_folders
from domain import database  # repo-root module, zie app/__init__.py

KINDS = ("bug", "idea")
STATUSES = ("new", "planned", "fixed", "wontfix")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    app TEXT,
    kind TEXT NOT NULL,
    message TEXT NOT NULL,
    page TEXT,
    context TEXT,
    screenshot BLOB,
    screenshot_type TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    reply TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS feedback_username ON feedback(username);
"""

_COLUMNS = (
    "id, username, app, kind, message, page, context, status, reply, created_at, updated_at, screenshot IS NOT NULL AS has_screenshot"
)


def _path() -> str:
    return os.path.join(database.data_root(), "feedback.db")


def _connect() -> sqlite3.Connection:
    os.makedirs(database.data_root(), exist_ok=True)
    conn = sqlite3.connect(_path())
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _iso(value: str | None) -> str | None:
    """A stored time as ISO 8601 with its timezone; every one written here is UTC."""
    if not value:
        return None
    try:
        t = datetime.fromisoformat(value)
    except ValueError:
        return value
    return t.replace(tzinfo=t.tzinfo or UTC).isoformat()


def _out(rows: list[sqlite3.Row]) -> list[dict]:
    """The items as every tracker returns them (the trackerai.nl admin page reads both): `app` always "wealth"
    (stored is "stock" or "money", from the days of two sites), the sender by trackerai account (`account_id` None
    when it is gone, `username` then the data folder)."""
    senders = linked_folders() if rows else {}
    out = []
    for row in rows:
        folder = row["username"]
        sender = senders.get(folder) or {}
        out.append(
            {
                "id": row["id"],
                "app": APP,
                "kind": row["kind"],
                "message": row["message"],
                "page": row["page"],
                "context": json.loads(row["context"]) if row["context"] else None,
                "status": row["status"],
                "reply": row["reply"],
                "created_at": _iso(row["created_at"]),
                "updated_at": _iso(row["updated_at"]),
                "account_id": sender.get("account_id"),
                "username": sender.get("username") or folder,
                "has_screenshot": bool(row["has_screenshot"]),
            }
        )
    return out


def add(
    username: str,
    app: str | None,
    kind: str,
    message: str,
    page: str | None,
    context: dict | None,
    screenshot: bytes | None = None,
    screenshot_type: str | None = None,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO feedback (username, app, kind, message, page, context, screenshot, screenshot_type, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)",
            (username, app, kind, message, page, json.dumps(context or {}, ensure_ascii=False), screenshot, screenshot_type, _now()),
        )
        return cur.lastrowid


def list_(username: str | None = None, status: str | None = None, limit: int = 200) -> list[dict]:
    """Newest first, without the screenshot itself. username None: from everyone (admins)."""
    where, args = [], []
    if username is not None:
        where.append("username = ?")
        args.append(username)
    if status:
        where.append("status = ?")
        args.append(status)
    sql = f"SELECT {_COLUMNS} FROM feedback" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
    with _connect() as conn:
        rows = conn.execute(sql, (*args, limit)).fetchall()
    return _out(rows)


def get(feedback_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(f"SELECT {_COLUMNS} FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
    return _out([row])[0] if row else None


def screenshot(feedback_id: int) -> tuple[str, bytes, str] | None:
    """(owner, bytes, media type) or None."""
    with _connect() as conn:
        row = conn.execute("SELECT username, screenshot, screenshot_type FROM feedback WHERE id = ?", (feedback_id,)).fetchone()
    return (row[0], row[1], row[2] or "image/png") if row and row[1] else None


def update(feedback_id: int, status: str | None = None, reply: str | None = None) -> bool:
    """Status and/or reply. None leaves a field as it is; an empty reply removes it."""
    sets, args = ["updated_at = ?"], [_now()]
    if status is not None:
        sets.append("status = ?")
        args.append(status)
    if reply is not None:
        sets.append("reply = ?")
        args.append(reply.strip() or None)
    with _connect() as conn:
        return conn.execute(f"UPDATE feedback SET {', '.join(sets)} WHERE id = ?", (*args, feedback_id)).rowcount > 0


def count_since(username: str, since_iso: str) -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM feedback WHERE username = ? AND created_at > ?", (username, since_iso)).fetchone()[0]


def delete_for_user(username: str) -> None:
    """When an account is deleted, its feedback goes with it."""
    with _connect() as conn:
        conn.execute("DELETE FROM feedback WHERE username = ?", (username,))
