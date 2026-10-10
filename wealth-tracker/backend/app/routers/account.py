"""
The account's own data, for its owner (S10):

    GET    /api/account/export          everything wealth-tracker holds of you, as a zip

Deleting, the password and two-step login are the shared trackerai account's
(packages/accounts: DELETE /api/account for the whole account, DELETE
/api/account/apps/wealth for wealth-tracker only, /api/account/totp/*); its
data then goes through core/accounts.py `purge`. Browser only:
deps.AGENT_BLOCKED keeps agent tokens away from /api/account.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Response

from app.deps import CurrentUser, get_current_user
from app.services import account_data

router = APIRouter(prefix="/api/account", tags=["account"])


@router.get("/export")
def export(user: CurrentUser = Depends(get_current_user)):
    data = account_data.export_zip(user.username)
    name = f"{user.username}-export-{datetime.now():%Y-%m-%d}.zip"
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "Cache-Control": "no-store",
    })
