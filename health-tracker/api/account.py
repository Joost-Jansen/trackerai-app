"""Your own data (GDPR art. 15, 17 and 20):

    GET    /api/account/export     a zip: a JSON file per table of your data and the stored FIT files and screenshots

Deleting is the account's (packages/accounts: DELETE /api/account deletes the whole account, DELETE
/api/account/apps/health only health-tracker); `purge` then deletes health-tracker's part. It revokes the Wahoo
access first, and waits while a sync or an Apple import of the account is running (it would write after the delete).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from api.connections import revoke_wahoo
from api.errors import ApiError
from tools import db

README = """health-tracker export of {username}, made {when} (UTC).

One JSON file per table, as stored (times in UTC unless the field says local):
account.json        the account (no password hash, no two-step secret)
activities.json     every activity with all its sources; activity_streams.json the per-second streams
wellness.json       sleep and recovery per day; intraday.json the series through the day
documents.json, entries.json (log and analyses), plans.json, plan_sessions.json, plan_links.json, routes.json
settings.json       zones, profile and other settings (without the encrypted Garmin and Wahoo sessions)
feedback.json       what you sent and the replies; agent_tokens.json your tokens' names (not the tokens)
fit/                the stored FIT files (the original recordings)
feedback/           screenshots sent with feedback
"""


def write_export(s: db.Scope, username: str, path: str) -> None:
    """The zip at `path`, written table by table and file by file (a large account does not sit in memory)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README.format(username=username, when=datetime.now(UTC).strftime("%Y-%m-%d %H:%M")))
        for name, rows in db.export_tables(s):
            with z.open(f"{name}.json", "w") as f:
                f.write(b"[")
                for i, row in enumerate(rows):
                    f.write((b",\n" if i else b"\n") + json.dumps(row, ensure_ascii=False, default=str).encode())
                f.write(b"\n]\n")
        for name, data in db.export_files(s):
            z.writestr(name, data)


def purge(engine, stores, accounts, key: str, runner=None, apple_imports=None) -> int:
    """Delete health-tracker's data of every account that left it or was deleted; returns how many. One whose sync
    or Apple import is running waits for the next sweep."""
    done = 0
    for p in accounts.pending_purges("health"):
        local = p["local_key"] or ""
        uid = int(local) if local.isdigit() else None
        if uid is not None:
            if (runner is not None and uid in runner.running) or (apple_imports is not None and uid in apple_imports.running):
                continue
            if apple_imports is not None:
                for up in [x for x in apple_imports.uploads.values() if x.user_id == uid]:
                    apple_imports.drop_upload(up)
            row = db.get_user(engine, uid)
            if row:
                revoke_wahoo(db.Scope(engine, uid), key)
                db.delete_user(engine, uid)
                db.add_audit(engine, "system", "delete_account", row["username"])
            stores.drop(uid)
        accounts.purged(p["account_id"], "health")
        done += 1
    return done


def make_router(current_user: Callable) -> APIRouter:
    r = APIRouter(prefix="/api/account")

    def person(u=Depends(current_user)):
        if u.via != "cookie" or u.example:
            raise ApiError(403, "site_login_only")
        return u

    @r.get("/export")
    def export(u=Depends(person)):
        fd, path = tempfile.mkstemp(prefix="export-", suffix=".zip")
        os.close(fd)
        try:
            write_export(u.scope, u.username, path)
        except BaseException:
            os.unlink(path)
            raise
        safe = re.sub(r"[^a-z0-9._-]", "_", u.username)
        name = f"health-tracker-{safe}-{datetime.now(UTC).date().isoformat()}.zip"
        return FileResponse(
            path,
            media_type="application/zip",
            filename=name,
            background=BackgroundTask(os.unlink, path),
            headers={"Cache-Control": "no-store"},
        )

    return r
