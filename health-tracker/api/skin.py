"""The skin diary (tools/skin.py): a private feature, only for the accounts in SKIN_DIARY_USERS (api/betas.py).

For everyone else these routes do not exist: not logged in, the example account or not on the list, every request gets
the same 404 as a path that was never there, and the routes are left out of the OpenAPI schema.

    GET    /api/skin/day?day=YYYY-MM-DD        the day's entry (or null) and its context: activities, Garmin's night
    PUT    /api/skin/day/{day}                 save fields of the day (merges: a field left out keeps its value)
    DELETE /api/skin/day/{day}                 the day and its photo
    POST   /api/skin/photo?day=YYYY-MM-DD      the day's photo (raw JPEG/PNG body), replacing an earlier one
    DELETE /api/skin/photo?day=YYYY-MM-DD      only the photo
    GET    /api/skin/photos/{id}               a photo, own only
    GET    /api/skin/overview?from=&to=        the days, per week the skin next to sleep and training, comparisons
    GET    /api/skin/export.csv?from=&to=      for the dermatologist: one row per day, Dutch columns
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from api import betas
from api.dashboard import max_by_sport, resting_hr
from api.errors import ApiError
from tools import skin
from tools.nutrition import photos
from trackerai_accounts import AccountError
from trackerai_websec.uploads import UploadTooLarge, read_limited

FEATURE = "skin"
DEFAULT_DAYS = 90


class EntryIn(BaseModel):
    """Any of tools/skin.py FIELDS; checked there. Unknown fields are an error, not ignored."""

    model_config = ConfigDict(extra="allow")


def _range(start: str | None, end: str | None, today: date) -> tuple[str, str]:
    try:
        b = skin.parse_day(end) if end else today
        a = skin.parse_day(start) if start else b - timedelta(days=DEFAULT_DAYS - 1)
    except skin.SkinError:
        raise ApiError(422, "invalid_day") from None
    if a > b or (b - a).days >= skin.MAX_RANGE_DAYS:
        raise ApiError(422, "invalid_range", max=skin.MAX_RANGE_DAYS)
    return a.isoformat(), b.isoformat()


def _day(value: str) -> date:
    try:
        return skin.parse_day(value)
    except skin.SkinError:
        raise ApiError(422, "invalid_day") from None


def _error(e: skin.SkinError) -> ApiError:
    return ApiError(422, e.code, **e.params)


def make_router(current_user: Callable, today: Callable[[], date]) -> APIRouter:
    r = APIRouter(include_in_schema=False)

    def member(request: Request, response: Response):
        # Not logged in reads as "no such page" too: a 401 would tell that the route exists.
        try:
            u = current_user(request, response)
        except (HTTPException, AccountError):
            raise HTTPException(404) from None
        if u.example or not betas.enabled(u.scope.engine, u.id, FEATURE):
            raise HTTPException(404)
        return u

    def context(u, day: str) -> dict:
        return skin.day_context(day, u.store.activities, u.store.wellness)

    @r.get("/api/skin/day")
    def get_day(day: str | None = None, u=Depends(member)):
        t = today()
        d = _day(day) if day else t
        return {
            "day": d.isoformat(),
            "today": t.isoformat(),
            "entry": skin.get(u.scope, d.isoformat()),
            "context": context(u, d.isoformat()),
        }

    @r.put("/api/skin/day/{day}")
    def put_day(day: str, body: EntryIn, u=Depends(member)):
        d = _day(day)
        if d > today():
            raise ApiError(422, "invalid_day")
        fields = body.model_dump()
        fields.pop("photo_id", None)  # a photo arrives through /api/skin/photo only
        try:
            entry = skin.save(u.scope, d, fields)
        except skin.SkinError as e:
            raise _error(e) from None
        return {"day": d.isoformat(), "today": today().isoformat(), "entry": entry, "context": context(u, d.isoformat())}

    @r.delete("/api/skin/day/{day}", status_code=204)
    def delete_day(day: str, u=Depends(member)):
        if not skin.remove(u.scope, _day(day).isoformat()):
            raise ApiError(404, "entry_not_found")
        return Response(status_code=204)

    @r.post("/api/skin/photo")
    async def put_photo(request: Request, day: str, u=Depends(member)):
        d = _day(day)
        try:
            data = await read_limited(request.stream(), photos.MAX_BYTES)
            mime, image = photos.clean(data)
        except UploadTooLarge:
            raise ApiError(413, "upload_too_large", max_mb=photos.MAX_BYTES // (1024 * 1024)) from None
        except photos.PhotoError:
            raise ApiError(422, "photo_invalid") from None
        return {"day": d.isoformat(), "entry": skin.set_photo(u.scope, d, mime, image)}

    @r.delete("/api/skin/photo")
    def delete_photo(day: str, u=Depends(member)):
        d = _day(day)
        return {"day": d.isoformat(), "entry": skin.drop_photo(u.scope, d.isoformat())}

    @r.get("/api/skin/photos/{photo_id}")
    def photo_file(photo_id: int, u=Depends(member)):
        found = skin.photo(u.scope, photo_id)
        if found is None:
            raise ApiError(404, "photo_not_found")
        mime, data = found
        return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})

    @r.get("/api/skin/overview")
    def overview(start: str | None = Query(None, alias="from"), end: str | None = Query(None, alias="to"), u=Depends(member)):
        a, b = _range(start, end, today())
        s = u.store
        entries = skin.between(u.scope, a, b)
        rhr = resting_hr(s.wellness, today(), s.rhr_fallback)
        return {
            "from": a,
            "to": b,
            "entries": entries,
            "weeks": skin.weeks(entries, s.activities, s.wellness, rhr, max_by_sport(s.zones, s.activities)),
            "comparisons": skin.comparisons(entries, s.activities, s.wellness),
            "sleep": {d: (s.wellness.get(d) or {}).get("sleep_h") for d in (e["day"] for e in entries)},
        }

    @r.get("/api/skin/export.csv")
    def export_csv(start: str | None = Query(None, alias="from"), end: str | None = Query(None, alias="to"), u=Depends(member)):
        a, b = _range(start, end, today())
        body = skin.to_csv(skin.between(u.scope, a, b), u.store.wellness)
        return Response(
            body,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="huiddagboek-{a}-{b}.csv"', "Cache-Control": "no-store"},
        )

    return r
