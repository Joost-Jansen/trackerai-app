"""health-tracker on the admin hub at trackerai.nl/admin, which reaches every tracker through /api/hub/{app}/...
(the same answers in every tracker, see the hub's contract):

    GET   /api/admin/tracker                       beta features, workouts per week, per account its workouts, betas
                                                   and stored activity files (`disk_bytes`, as the users list's files_bytes),
                                                   and `facts`: key figures (Voeding's photo analysis, tools/nutrition/accuracy.py)
    PATCH /api/admin/tracker/betas/{account_id}    one beta feature on or off for an account

Admins only, logged in on the site (like the other admin routes). Accounts are the shared trackerai accounts' ids;
users without a linked account are left out.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api import betas
from api.errors import ApiError
from api.users import APP
from tools import db
from tools.nutrition import accuracy as nutrition_accuracy
from trackerai_accounts import Accounts

WEEKS = 12
MEASURE = {"en": "workouts", "nl": "trainingen"}


class BetaPatch(BaseModel):
    feature: str
    enabled: bool


def weekly(per_day: dict[str, int], today: date) -> list[dict]:
    """The last WEEKS ISO weeks up to and including today's, oldest first, each by its Monday; empty weeks count 0."""
    first = today - timedelta(days=today.weekday()) - timedelta(weeks=WEEKS - 1)
    counts = {first + timedelta(weeks=i): 0 for i in range(WEEKS)}
    for day, n in per_day.items():
        try:
            d = date.fromisoformat(day)
        except ValueError:
            continue
        monday = d - timedelta(days=d.weekday())
        if monday in counts:
            counts[monday] += n
    return [{"week": monday.isoformat(), "value": n} for monday, n in counts.items()]


def _utc_iso(start_utc: str | None) -> str | None:
    """A stored start_utc ("2026-10-08T06:02:11Z") as ISO with its zone."""
    if not start_utc:
        return None
    try:
        t = datetime.fromisoformat(start_utc.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=UTC)).isoformat()


def make_router(engine, accounts: Accounts, current_user: Callable, today: Callable[[], date]) -> APIRouter:
    r = APIRouter()

    def admin(u=Depends(current_user)):
        if u.via != "cookie" or not u.is_admin:
            raise ApiError(403, "admins_only")
        return u

    def entry(account_id: int, user_id: int, stored: list[str], totals: dict, files: dict) -> dict:
        count, last = totals.get(user_id, (0, None))
        return {
            "account_id": account_id,
            "betas": [f for f in betas.ids() if f in stored],
            "count": count,
            "last_at": _utc_iso(last),
            "disk_bytes": files.get(user_id, 0),
        }

    @r.get("/api/admin/tracker")
    def tracker(a=Depends(admin)):
        day = today()
        stored, totals, files = db.all_user_betas(engine), db.activity_totals(engine), db.files_bytes(engine)
        linked = sorted(
            (x["id"], int(x["local_keys"][APP])) for x in accounts.list_accounts() if (x["local_keys"].get(APP) or "").isdigit()
        )
        return {
            "app": APP,
            "betas": betas.BETA_FEATURES,
            "measure": MEASURE,
            "weekly": weekly(db.activities_per_day(engine, day - timedelta(days=day.weekday(), weeks=WEEKS - 1)), day),
            "accounts": [entry(aid, uid, stored[uid], totals, files) for aid, uid in linked if uid in stored],
            "facts": nutrition_accuracy.facts(engine, day),  # Voeding: photo analyses this month and how accurate they are
            "disk_bytes_total": sum(files.values()),  # every user's, like `weekly`
        }

    @r.patch("/api/admin/tracker/betas/{account_id}")
    def set_beta(account_id: int, body: BetaPatch, a=Depends(admin)):
        key = accounts.local_key(account_id, APP)
        if not key or not key.isdigit() or not db.get_user(engine, int(key)):
            raise ApiError(404, "account_not_found")
        if body.feature not in betas.ids():
            raise ApiError(422, "unknown_beta", options=betas.ids())
        uid = int(key)
        now = db.set_user_beta(engine, uid, body.feature, body.enabled)
        account = accounts.get(account_id) or {}
        db.add_audit(
            engine,
            a.username,
            "set_beta",
            account.get("username") or f"account {account_id}",
            f"{body.feature} {'on' if body.enabled else 'off'}",
        )
        return entry(account_id, uid, now, db.activity_totals(engine), db.files_bytes(engine))

    return r
