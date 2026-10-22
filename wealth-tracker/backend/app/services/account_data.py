"""
A user's own data: everything out (export, S10) and everything gone (deletion).

Export: one zip with each table of the user's database as CSV and JSON, the
account itself (without password or token hashes), their feedback with
screenshots, and any uploads still stored. What only gives access (the
encrypted bank key, the bank session, consent state) is left out: it is
useless outside this server and must not travel in a download.

CSV cells that a spreadsheet would read as a formula (=, +, -, @, tab, CR at
the start of a *text* value) get a leading apostrophe; numbers stay numbers.

Deletion: the bank consents are revoked at Enable Banking first (best effort:
an expired session is gone already), then the data folder, the feedback and
finally the account in auth_config.yaml (with its agent tokens and two-step
secret). Other users are never touched: every path is derived from the one
validated username.
"""

import csv
import io
import json
import os
import sqlite3
import zipfile
from datetime import UTC, datetime

from app.core import audit, auth_store, feedback_store
from domain import database

# Columns that are secrets or one-time state, not the user's data.
_WITHHELD = {
    ("bank_connections", "key"),
    ("bank_consents", "session_id"),
    ("bank_consents", "state"),
}
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """Neutralise spreadsheet formulas in text cells (CSV injection)."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def _jsonable(value):
    if isinstance(value, bytes):
        return {"base64": __import__("base64").b64encode(value).decode()}
    return value


def _tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _rows(conn: sqlite3.Connection, table: str) -> tuple[list[str], list[list]]:
    cur = conn.execute(f'SELECT * FROM "{table}"')  # table names come from sqlite_master
    columns = [d[0] for d in cur.description]
    rows = []
    for row in cur.fetchall():
        rows.append(["[withheld]" if (table, col) in _WITHHELD and row[i] is not None else row[i] for i, col in enumerate(columns)])
    return columns, rows


def _account(username: str) -> dict:
    cfg = auth_store.load_config()
    user = (cfg.get("credentials", {}).get("usernames", {}) or {}).get(username) or {}
    keep = ("name", "created_at", "last_login", "locale", "pw_changed_at")
    return {
        "username": username,
        **{k: user.get(k) for k in keep if k in user},
        "is_admin": auth_store.is_admin(username, cfg),
        "beta_features": auth_store.user_beta_features(username, cfg),
        "two_step_login": bool((user.get("totp") or {}).get("enabled")),
        "agent_tokens": auth_store.list_agent_tokens(username, cfg),
    }


def export_zip(username: str) -> bytes:
    buf = io.BytesIO()
    now = datetime.now(UTC).replace(microsecond=0).isoformat()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "README.txt",
            (
                f"Export of account '{username}', made {now}.\n"
                "database/: every table of your database, as CSV and as JSON.\n"
                "account.json: your account (no password or token hashes).\n"
                "feedback.json and feedback/: what you sent as feedback.\n"
                "uploads/: imported files that are still stored (normally none: they are deleted after import).\n"
                "Withheld: the encrypted bank key and bank session (secrets, useless elsewhere).\n"
            ),
        )
        zf.writestr("account.json", json.dumps(_account(username), indent=2, ensure_ascii=False))

        if database.has_data(username):
            conn = database.connect(username)
            try:
                for table in _tables(conn):
                    columns, rows = _rows(conn, table)
                    text = io.StringIO()
                    writer = csv.writer(text)
                    writer.writerow(columns)
                    writer.writerows([[csv_safe(v) for v in r] for r in rows])
                    zf.writestr(f"database/{table}.csv", text.getvalue())
                    zf.writestr(
                        f"database/{table}.json",
                        json.dumps([{c: _jsonable(v) for c, v in zip(columns, r)} for r in rows], indent=1, ensure_ascii=False),
                    )
            finally:
                conn.close()

        items = feedback_store.list_(username=username, limit=100_000)
        zf.writestr("feedback.json", json.dumps(items, indent=2, ensure_ascii=False))
        for f in items:
            if f.get("has_screenshot"):
                shot = feedback_store.screenshot(f["id"])
                if shot and shot[0] == username:
                    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(shot[2], "bin")
                    zf.writestr(f"feedback/{f['id']}.{ext}", shot[1])

        upload_dir = os.path.join(database.user_data_dir(username), "uploads")
        if os.path.isdir(upload_dir):
            for name in sorted(os.listdir(upload_dir)):
                path = os.path.join(upload_dir, name)
                if os.path.isfile(path) and not os.path.islink(path):
                    zf.write(path, f"uploads/{name}")
    return buf.getvalue()


def revoke_bank_connections(username: str) -> None:
    """Revoke every consent at Enable Banking. Best effort, never raises."""
    if not database.has_data(username):
        return
    try:
        from domain.money import bank_link

        conn = database.connect(username)
        try:
            database.init_db(conn)
            bank_link.delete_everything(conn)
        finally:
            conn.close()
    except Exception:
        pass


def remove_data(username: str) -> None:
    """Everything stored for `username` outside auth_config.yaml."""
    revoke_bank_connections(username)
    database.delete_user_data(username)
    feedback_store.delete_for_user(username)


def delete_own_account(username: str) -> None:
    """The user deletes themselves (password already checked by the caller)."""
    auth_store.delete_own_account(username)  # refuses the last admin; nothing removed yet then
    remove_data(username)
    audit.log(username, "delete_own_account", target=username)
