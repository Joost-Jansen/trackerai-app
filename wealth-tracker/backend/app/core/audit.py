"""
Append-only audit log of admin actions — who did what, to whom, when.

Kept as JSON-lines in a file of its own rather than inside auth_config.yaml:
the config is rewritten in full on every change (by both this backend and the
old Streamlit app), which is the worst place to keep an ever-growing log. A
plain append is also naturally tolerant of the concurrent writers the config
lock guards against — os-level appends of small lines don't interleave.

The path is derived from database's data root so a test that redirects that
root (see conftest.py) also redirects the audit log, keeping runs isolated.
"""

import json
import os
from datetime import UTC, datetime

from domain import database  # repo-root module, see app/__init__.py for the sys.path setup


def _audit_path() -> str:
    return os.path.join(database.data_root(), "admin_audit.log")


def log(actor: str, action: str, target: str | None = None, detail: str | None = None) -> None:
    """Record one admin action. Best-effort: auditing must never break the action."""
    entry = {
        "ts": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "actor": actor,
        "action": action,
        "target": target,
        "detail": detail,
    }
    try:
        os.makedirs(database.data_root(), exist_ok=True)
        with open(_audit_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def tail(n: int = 100) -> list[dict]:
    """The most recent `n` entries, newest first."""
    path = _audit_path()
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    entries = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    entries.reverse()
    return entries
