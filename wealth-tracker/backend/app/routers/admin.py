"""
wealth-tracker's part of the shared admin page (packages/marketing Admin.tsx, at
trackerai.nl/admin and at /admin here): its beta features, figures per account
and its feedback (routers/feedback.py). Accounts themselves, sign-up and
invitations are the shared account's (packages/accounts, /api/trackerai/admin).
Beta changes are written to the audit log.
"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from app.core import audit, auth_store
from app.core.accounts import APP, linked_folders
from app.deps import CurrentUser, require_admin
from app.schemas.admin import TrackerBetaRequest

from domain import database  # repo-root module, see app/__init__.py for the sys.path setup
from domain.i18n import tr
from domain.i18n_nl import NL

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- the trackerai.nl admin page (packages/marketing Admin.tsx, through /api/hub/wealth/...) ---
#
# The same shape in every tracker: its betas, what it counts (here bank transactions), that count per week, and
# per account the betas granted here, the count, the newest booking date and the database's size on disk (as the
# panel's `stats.db_size_bytes`). Accounts by their trackerai id.

WEEKS = 12


def _both(text: str) -> dict:
    """English and Dutch at once: the page shows the one of its own language."""
    return {"en": text, "nl": NL.get(text, text)}


def _weeks() -> list[date]:
    """The Mondays of the last WEEKS ISO weeks, the current one included, oldest first."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return [monday - timedelta(weeks=n) for n in range(WEEKS - 1, -1, -1)]


def _tracker_account(account_id: int | None, folder: str, since: date, cfg: dict) -> tuple[dict, dict]:
    """(the page's entry for one account, its bank transactions per booking date from `since`)."""
    activity = database.bank_activity(folder, since.isoformat()) or {"count": 0, "last": None, "per_day": {}}
    entry = {"account_id": account_id, "betas": auth_store.granted_betas(folder, cfg),
             "count": activity["count"], "last_at": activity["last"], "disk_bytes": database.db_size_bytes(folder)}
    return entry, activity["per_day"]


@router.get("/tracker")
def tracker(user: CurrentUser = Depends(require_admin)):
    """wealth-tracker for the trackerai.nl admin page. Every user database is opened read-only, with two small
    queries; the weekly figure counts every real user (the tour's example folders not), linked to an account or
    not, while `accounts` lists only those with an account; so does `disk_bytes_total`."""
    weeks = _weeks()
    cfg = auth_store.load_config_or_empty()
    linked = linked_folders()
    folders = set(linked) | {f for f in auth_store.users_or_empty() if not f.startswith("_")}
    per_week = {w: 0 for w in weeks}
    entries, disk = [], 0
    for folder in sorted(folders):
        try:
            entry, per_day = _tracker_account((linked.get(folder) or {}).get("account_id"), folder, weeks[0], cfg)
        except ValueError:
            continue  # not a valid folder name: nothing on disk under it
        disk += entry["disk_bytes"]
        for day, n in per_day.items():
            try:
                d = date.fromisoformat(day)
            except ValueError:
                continue
            monday = d - timedelta(days=d.weekday())
            if monday in per_week:
                per_week[monday] += n
        if folder in linked:
            entries.append(entry)
    return {
        "app": APP,
        "betas": [{"id": key, "name": _both(label)} for key, label in auth_store.BETA_FEATURES.items()],
        "measure": _both("bank transactions"),
        "weekly": [{"week": w.isoformat(), "value": per_week[w]} for w in weeks],
        "accounts": sorted(entries, key=lambda e: e["account_id"]),
        "disk_bytes_total": disk,
    }


@router.patch("/tracker/betas/{account_id}")
def set_tracker_beta(account_id: int, body: TrackerBetaRequest, user: CurrentUser = Depends(require_admin)):
    """One beta on or off for one account, in the same grants as the panel's (PUT /beta-features); returns the
    account's entry as GET /tracker lists it."""
    if body.feature not in auth_store.BETA_FEATURES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, tr("Unknown beta feature(s): {0}", body.feature))
    folder = next((f for f, a in linked_folders().items() if a["account_id"] == account_id), None)
    if folder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, tr("No such account: {0}.", account_id))
    try:
        auth_store.set_beta(user.username, folder, body.feature, body.enabled)
    except auth_store.AuthError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    audit.log(user.username, "beta_feature", target=folder, detail=f"{body.feature} {'on' if body.enabled else 'off'}")
    return _tracker_account(account_id, folder, _weeks()[0], auth_store.load_config_or_empty())[0]
