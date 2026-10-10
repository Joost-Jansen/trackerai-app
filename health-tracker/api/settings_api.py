"""Zones and profile (T19): heart-rate zones per sport and basic facts, set by each user on the site.

Zones model: % of max HR per sport. Z2..Z5 start at percentages P (default 70 / 77 / 85 / 92.5). Lower bounds:
Z2 = round(max x P1), Z3..Z5 = round(max x P) + 1 (Garmin's convention: a zone's top is round(max x P), the next zone
starts one beat above). With max 190 this gives 133 / 147 / 163 / 177.
After a change, the time per zone of every activity is recomputed (tools/derive.py).
"""

from __future__ import annotations

from datetime import date, timedelta

import threading
from typing import Callable

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.errors import ApiError
from tools import db
from tools.derive import derive

SPORTS = ("run", "ride", "swim")
DEFAULT_PERCENT = [70.0, 77.0, 85.0, 92.5]
# Without an own max for cycling/swimming: estimate from the running max (HR is usually lower there)
ESTIMATE_OFFSET = {"ride": 7, "swim": 12}


def bounds_for(max_hr: int, percent: list[float]) -> list[int]:
    return [round(max_hr * percent[0] / 100)] + [round(max_hr * p / 100) + 1 for p in percent[1:]]


def suggested_max(activities: list[dict]) -> dict:
    """Per sport: the highest max HR seen, ignoring the top 2% (a wrist sensor spike). None without data."""
    out = {}
    for sport in SPORTS:
        values = sorted(a["max_hr"] for a in activities if a["sport"] == sport and a.get("max_hr"))
        if not values:
            out[sport] = None
        elif len(values) < 10:
            out[sport] = values[-1]
        else:
            out[sport] = values[-(max(1, len(values) // 50) + 1)]
    return out


class SportZones(BaseModel):
    max_hr: int | None = None
    estimate: bool = False


class ZonesIn(BaseModel):
    percent: list[float] = DEFAULT_PERCENT
    sports: dict[str, SportZones]


class ProfileFacts(BaseModel):
    birth_year: int | None = None
    weight_kg: float | None = None
    height_cm: float | None = None
    resting_hr: int | None = None


def make_router(current_user: Callable) -> APIRouter:
    r = APIRouter(prefix="/api/settings")

    @r.get("/zones")
    def get_zones(u=Depends(current_user)):
        zones = u.store.zones
        meta = db.get_setting(u.scope, "zones_model") or {}
        return {
            "percent": meta.get("percent", DEFAULT_PERCENT),
            "zones": zones,
            "suggested_max": suggested_max(u.store.activities),
            "estimate_offset": ESTIMATE_OFFSET,
        }

    @r.put("/zones")
    def put_zones(body: ZonesIn, u=Depends(current_user)):
        p = body.percent
        if len(p) != 4 or not all(40 <= x <= 100 for x in p) or p != sorted(p) or len(set(p)) != 4:
            raise ApiError(422, "zone_percentages")
        zones = {}
        for sport, z in body.sports.items():
            if sport not in SPORTS:
                raise ApiError(422, "unknown_sport", sport=sport)
            if z.max_hr is None:
                continue
            if not 100 <= z.max_hr <= 230:
                raise ApiError(422, "max_hr_range", min=100, max=230)
            zones[sport] = {"max_hr": z.max_hr, "bounds": bounds_for(z.max_hr, p), "estimate": z.estimate}
        db.set_setting(u.scope, "zones", zones)
        db.set_setting(u.scope, "zones_model", {"percent": p})
        u.store.invalidate()
        threading.Thread(target=lambda: (derive(u.scope), u.store.invalidate()), name=f"derive-{u.id}", daemon=True).start()
        return get_zones(u)

    @r.get("/profile")
    def get_profile(u=Depends(current_user)):
        return db.get_setting(u.scope, "profile_facts") or {}

    @r.get("/resting-hr")
    def get_resting_hr(u=Depends(current_user)):
        """The normal resting HR the site calculates now and where it comes from (60d, recent, profile or none), so
        Settings can show that the entered value is only a fallback."""
        from api.readiness import normal_resting_hr

        value, source = normal_resting_hr(u.store.wellness, date.today() + timedelta(days=1), u.store.rhr_fallback)
        return {"value": round(value) if value is not None else None, "source": source}

    @r.put("/profile")
    def put_profile(body: ProfileFacts, u=Depends(current_user)):
        facts = body.model_dump(exclude_none=True)
        limits = {"birth_year": (1900, 2025), "weight_kg": (25, 250), "height_cm": (100, 250), "resting_hr": (25, 120)}
        for k, v in facts.items():
            lo, hi = limits[k]
            if not lo <= v <= hi:
                raise ApiError(422, "profile_range", field=k, min=lo, max=hi)
        db.set_setting(u.scope, "profile_facts", facts)
        return facts

    return r
