"""Gear: shoes, a bike, anything an activity wears out, and when it is due for replacement.

Gear comes from Garmin Connect (the sync, tools/sync.py GarminClient.gear) or is added on the site. Which activity
used what: what the user chose on it, else what Garmin says, else the default gear of its sport (tools/db.py
gear_links and apply_gear_defaults).

Distance = start_km (use before it was tracked anywhere) + what Garmin counted on it from activities that are not
here (Garmin's total minus the activities linked through Garmin) + the activities linked here. So moving an activity
to other gear moves its kilometres, also for Garmin gear.

    GET    /api/gear                       every item with distance and state, the defaults, the sports
    POST   /api/gear                       add one
    PATCH  /api/gear/{id}                  change one (also retire: retired_on; default_for: sports)
    DELETE /api/gear/{id}                  only gear added here; Garmin's comes back at the next sync, retire it
    GET    /api/gear/{id}/activities       what it was used on, newest first
    PUT    /api/activities/{id}/gear       {"gear_ids": [...]} the user's choice, [] none, null automatic again
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.errors import ApiError
from tools import db

# Replace at, when neither the user nor Garmin set a limit: running shoes last 500-800 km; a bike has no such number.
DEFAULT_MAX_KM = {"shoes": 700.0}
SOON = 0.85  # from this share of the limit: "replace soon"


class GearIn(BaseModel):
    kind: str | None = None
    name: str | None = Field(None, max_length=100)
    brand: str | None = Field(None, max_length=60)
    model: str | None = Field(None, max_length=80)
    start_km: float | None = Field(None, ge=0, le=100000)
    max_km: float | None = Field(None, gt=0, le=100000)
    since: str | None = None
    retired_on: str | None = None
    notes: str | None = Field(None, max_length=2000)
    default_for: list[str] | None = None  # sports this gear is the default for (replaces what it was before)


class ActivityGearIn(BaseModel):
    gear_ids: list[int] | None


def _day(value: str | None, field: str) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        raise ApiError(422, "invalid_date", date=value) from None


def summarize(items: list[dict], links: list[dict], activities: list[dict], defaults: dict, today: date) -> list[dict]:
    """Per item: distance, uses, first and last use, the last 30 days, the limit and the state."""
    by_id = {a["id"]: a for a in activities}
    month_ago = (today - timedelta(days=30)).isoformat()
    out = []
    for g in items:
        mine = [(by_id[link["activity_id"]], link["source"]) for link in links if link["gear_id"] == g["id"] and link["activity_id"] in by_id]
        km = lambda acts: round(sum(a.get("distance_km") or 0 for a in acts), 1)  # noqa: E731
        linked = km(a for a, _ in mine)
        via_garmin = km(a for a, src in mine if src == "garmin")
        garmin = g.get("garmin") or {}
        history = max(0.0, round((garmin.get("total_km") or 0) - via_garmin, 1))
        total = round((g.get("start_km") or 0) + history + linked, 1)
        limit = g.get("max_km") or garmin.get("max_km") or DEFAULT_MAX_KM.get(g["kind"])
        share = total / limit if limit else None
        state = "retired" if g.get("retired_on") else "replace" if share is not None and share >= 1 else "soon" if share is not None and share >= SOON else "ok"
        days = sorted(a["start_local"][:10] for a, _ in mine)
        out.append({
            **{k: g.get(k) for k in ("id", "kind", "name", "brand", "model", "start_km", "max_km", "since", "retired_on", "notes")},
            "source": "garmin" if g.get("garmin_uuid") else "manual",
            "total_km": total,
            "linked_km": linked,
            "before_km": round((g.get("start_km") or 0) + history, 1),  # what was on it before the activities here
            "limit_km": limit,
            "limit_from": "own" if g.get("max_km") else "garmin" if garmin.get("max_km") else "default" if limit else None,
            "left_km": round(limit - total, 1) if limit else None,
            "share": round(share, 3) if share is not None else None,
            "state": state,
            "uses": len(mine) + max(0, (garmin.get("activities") or 0) - sum(1 for _, src in mine if src == "garmin")),
            "first_used": days[0] if days else g.get("since"),
            "last_used": days[-1] if days else None,
            "km_30d": km(a for a, _ in mine if a["start_local"][:10] >= month_ago),
            "default_for": sorted(sport for sport, gid in defaults.items() if gid == g["id"]),
        })
    order = {"replace": 0, "soon": 1, "ok": 2, "retired": 3}
    return sorted(out, key=lambda x: (order[x["state"]], x["state"] == "retired" and x["retired_on"] or "", -(x["km_30d"] or 0), x["name"].lower()))


def gear_of(links: list[dict], items: list[dict], aid: str) -> list[dict]:
    """The gear an activity used, for its page and the agent."""
    names = {g["id"]: g for g in items}
    return [{"id": link["gear_id"], "name": names[link["gear_id"]]["name"], "kind": names[link["gear_id"]]["kind"], "source": link["source"]}
            for link in links if link["activity_id"] == aid and link["gear_id"] in names]


def overview(scope, activities: list[dict], today: date) -> dict:
    defaults = db.get_setting(scope, db.GEAR_DEFAULTS_KEY) or {}
    gear = summarize(db.list_gear(scope), db.gear_links(scope), activities, defaults, today)
    sports = sorted({a["sport"] for a in activities})
    return {"gear": gear, "defaults": defaults, "sports": sports}


def make_router(current_user: Callable, today: Callable[[], date]) -> APIRouter:
    r = APIRouter()

    def _apply(u, gid: int, body: GearIn) -> None:
        if body.default_for is not None:
            defaults = {k: v for k, v in (db.get_setting(u.scope, db.GEAR_DEFAULTS_KEY) or {}).items() if v != gid}
            for sport in body.default_for:
                defaults[str(sport)[:40]] = gid  # one default per sport: this one takes it over
            db.set_setting(u.scope, db.GEAR_DEFAULTS_KEY, defaults)
        db.apply_gear_defaults(u.scope)
        u.store.invalidate()

    def _fields(body: GearIn) -> dict:
        fields = body.model_dump(exclude_unset=True, exclude={"default_for"})
        if "kind" in fields and fields["kind"] not in db.GEAR_KINDS:
            raise ApiError(422, "invalid_choice", options=", ".join(db.GEAR_KINDS))
        if "name" in fields and not (fields["name"] or "").strip():
            raise ApiError(422, "gear_name_required")
        if "name" in fields:
            fields["name"] = fields["name"].strip()
        for k in ("since", "retired_on"):
            if k in fields:
                fields[k] = _day(fields[k], k)
        return fields

    @r.get("/api/gear")
    def list_(u=Depends(current_user)):
        return overview(u.scope, u.store.activities, today())

    @r.post("/api/gear", status_code=201)
    def create(body: GearIn, u=Depends(current_user)):
        fields = _fields(body)
        if not fields.get("name") or not fields.get("kind"):
            raise ApiError(422, "gear_name_required")
        g = db.create_gear(u.scope, **fields)
        _apply(u, g["id"], body)
        return next(x for x in overview(u.scope, u.store.activities, today())["gear"] if x["id"] == g["id"])

    @r.patch("/api/gear/{gid}")
    def change(gid: int, body: GearIn, u=Depends(current_user)):
        if not db.update_gear(u.scope, gid, **_fields(body)):
            raise ApiError(404, "gear_not_found")
        _apply(u, gid, body)
        return next(x for x in overview(u.scope, u.store.activities, today())["gear"] if x["id"] == gid)

    @r.delete("/api/gear/{gid}")
    def remove(gid: int, u=Depends(current_user)):
        g = db.get_gear(u.scope, gid)
        if not g:
            raise ApiError(404, "gear_not_found")
        if g.get("garmin_uuid"):
            raise ApiError(409, "garmin_gear")
        db.delete_gear(u.scope, gid)
        db.apply_gear_defaults(u.scope)
        u.store.invalidate()
        return {"ok": True}

    @r.get("/api/gear/{gid}/activities")
    def used_on(gid: int, u=Depends(current_user)):
        if not db.get_gear(u.scope, gid):
            raise ApiError(404, "gear_not_found")
        mine = {link["activity_id"]: link["source"] for link in db.gear_links(u.scope) if link["gear_id"] == gid}
        acts = sorted((a for a in u.store.activities if a["id"] in mine), key=lambda a: a["start_local"], reverse=True)
        return [{**{k: a.get(k) for k in ("id", "start_local", "sport", "name", "distance_km", "moving_time_s")}, "source": mine[a["id"]]} for a in acts]

    @r.put("/api/activities/{aid}/gear")
    def choose(aid: str, body: ActivityGearIn, u=Depends(current_user)):
        if not any(a["id"] == aid for a in u.store.activities):
            raise ApiError(404, "activity_not_found")
        db.set_activity_gear(u.scope, aid, body.gear_ids)
        db.apply_gear_defaults(u.scope)
        u.store.invalidate()
        return {"gear": gear_of(db.gear_links(u.scope), db.list_gear(u.scope), aid), "automatic": body.gear_ids is None}

    return r
