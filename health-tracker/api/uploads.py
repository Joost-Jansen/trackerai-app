"""Upload FIT files: activities that are not on Garmin (a Wahoo bike computer, Zwift, a friend's watch).

One file per request, as the raw body (no multipart dependency): `POST /api/activities/upload?name=<file name>`.
A .fit or a .zip with one inside. An activity that starts within two minutes of one we already have (the same ride
synced from Garmin) is merged into it, not added twice; Garmin's values stay leading, see tools.store priorities.
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, Request

from api.errors import ApiError
from tools import db
from tools.derive import derive
from tools.fit import read_fit_activity
from tools.store import from_fit, same_start
from trackerai_websec.uploads import UploadTooLarge, ZipRejected, check_zip, read_limited

MAX_BYTES = int(os.environ.get("MAX_UPLOAD_MB") or 25) * 1024 * 1024  # a FIT file of a long ride is a few MB
MAX_UNZIPPED = 100 * 1024 * 1024  # a .fit inside a zip: unpacked in memory, so bounded (zip bombs)


def make_router(current_user: Callable) -> APIRouter:
    r = APIRouter()

    @r.post("/api/activities/upload")
    async def upload(request: Request, name: str = Query("activity.fit", max_length=200), recompute: bool = True, u=Depends(current_user)):
        """`recompute=false` skips zones and routes for this file; send it on every file but the last of a batch."""
        try:
            data = await read_limited(request.stream(), MAX_BYTES)  # counted while it streams in, never read whole first
        except UploadTooLarge:
            raise ApiError(413, "upload_too_large", max_mb=MAX_BYTES // (1024 * 1024))
        if not data:
            raise ApiError(400, "upload_empty")
        if data[:2] == b"PK":
            try:
                check_zip(io.BytesIO(data), max_members=100, max_total_uncompressed=MAX_UNZIPPED, max_ratio=200)
            except ZipRejected as err:
                raise ApiError(422, "fit_unreadable") from err
        try:
            activity = read_fit_activity(data)
        except ValueError as err:
            raise ApiError(422, "fit_unreadable") from err

        record = from_fit(activity, filename=name)
        existing = next((a for a in u.store.activities if same_start(a, record)), None)
        aid = db.upsert_activity(u.scope, record)
        db.put_fit(u.scope, f"upload/{aid}", data)
        if not (existing or {}).get("fit_file"):  # a Garmin original stays the file of record
            db.set_derived(u.scope, aid, fit_file=f"upload/{aid}")
        if recompute:
            derive(u.scope)
        u.store.invalidate()
        source = next(iter(record["sources"]))
        return {
            "status": "merged" if existing else "added",
            "id": aid,
            "sport": record["sport"],
            "start_local": record["start_local"],
            "distance_km": record.get("distance_km"),
            "source": source,
            "merged_with": sorted(set((existing or {}).get("sources", {})) - {source}) if existing else [],
        }

    @r.post("/api/activities/recompute")
    def recompute(u=Depends(current_user)):
        """Zones and routes again, after a batch uploaded with recompute=false."""
        out = derive(u.scope)
        u.store.invalidate()
        return out

    return r
