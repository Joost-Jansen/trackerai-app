"""Nutrition (Voeding): meals per day, their totals against training-aware targets, and food search.

Behind the beta feature `nutrition` (api/betas.py): every route answers 403 nutrition_off for a user without it.

    GET    /api/nutrition/day?day=YYYY-MM-DD   totals, targets, meals with items, the day's training (default today)
    POST   /api/nutrition/meals                save a meal the user confirmed: {day, eaten_at, moment, input, items, note}
    PATCH  /api/nutrition/meals/{id}           change its day, time, moment, note or items (items replace the old ones)
    DELETE /api/nutrition/meals/{id}           the meal, its items and its photo
    GET    /api/nutrition/foods/search?q=      NEVO, cached Open Food Facts and your own foods, best first
    POST   /api/nutrition/admin/nevo           admins: import a NEVO-online release (the CSV or RIVM's zip as the body)

Items: {food_ref, grams, grams_source?} plus, from a photo, {grams_ai, grams_low, grams_high, confidence}. Nutrient
values always come from the food table (tools/nutrition/foods.py), never from the request.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from api import betas
from api.errors import ApiError
from api.plans import enrich
from tools import db
from tools.nutrition import foods, meals, nevo, targets
from tools.nutrition.nutrients import energy_split
from trackerai_websec.uploads import UploadTooLarge, read_limited

FEATURE = "nutrition"
NEVO_MAX_BYTES = 40 * 1024 * 1024  # RIVM's zip is about 27 MB (the CSV inside 1.7 MB)
MAX_RANGE_DAYS = 400


class ItemIn(BaseModel):
    id: int | None = None  # an existing item of this meal (PATCH): keeps its food and estimate
    food_ref: str | None = Field(None, max_length=60)
    name: str | None = Field(None, max_length=200)
    grams: float | None = None
    grams_source: str | None = Field(None, max_length=10)
    grams_ai: float | None = None
    grams_low: float | None = None
    grams_high: float | None = None
    confidence: float | None = Field(None, ge=0, le=1)


class MealIn(BaseModel):
    day: str = Field(max_length=10)
    eaten_at: str = Field(max_length=5)
    moment: str = Field(max_length=12)
    input: str = Field("search", max_length=10)
    note: str | None = Field(None, max_length=2000)
    items: list[ItemIn] = Field(max_length=meals.MAX_ITEMS)


class MealPatch(BaseModel):
    day: str | None = Field(None, max_length=10)
    eaten_at: str | None = Field(None, max_length=5)
    moment: str | None = Field(None, max_length=12)
    note: str | None = Field(None, max_length=2000)
    items: list[ItemIn] | None = Field(None, max_length=meals.MAX_ITEMS)


def _parse_day(value: str | None, today: date) -> date:
    if not value:
        return today
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError(422, "invalid_date", date=value) from None


def _meal_error(e: meals.MealError) -> ApiError:
    status = 404 if e.code == "food_not_found" else 422
    return ApiError(status, e.code, **e.params)


def weight_of(scope) -> float | None:
    return (db.get_setting(scope, "profile_facts") or {}).get("weight_kg")


def plan_sessions(u, today: date) -> list[dict]:
    plan = db.active_plan(u.scope)
    return enrich(plan, u.store.activities, u.store.routes, today)["sessions"] if plan else []


def day_view(u, day: date, today: date, now_hhmm: str | None = None) -> dict:
    """Everything the Dag tab and Vandaag show of one day."""
    s = u.scope
    logged = meals.between(s, day.isoformat(), day.isoformat())
    totals = meals.day_totals(logged)
    weight = weight_of(s)
    target = targets.for_day(day, today, u.store.activities, plan_sessions(u, today), weight)
    version = nevo.current_version(s.engine)
    others = any(not it["food_ref"].startswith("nevo:") for m in logged for it in m["items"])
    return {
        "day": day.isoformat(),
        "today": today.isoformat(),
        "meals": logged,
        "totals": totals,
        "energy_split": energy_split(totals),
        "per_kg": {"carbs": targets.per_kg(totals["carbs_g"], weight), "protein": targets.per_kg(totals["protein_g"], weight)},
        "targets": target,
        "context": targets.context(target, u.store.activities, now_hhmm) if day == today else None,
        "last_meal": meals.last_meal(logged),
        "burn_kcal": (u.store.wellness.get(day.isoformat()) or {}).get("total_kcal"),  # Garmin's estimate, when synced
        "source": {"version": version, "nl": nevo.attribution(version, "nl", others), "en": nevo.attribution(version, "en", others)},
        "foods_ready": version is not None,
    }


def dashboard_block(u, today: date, now_hhmm: str) -> dict | None:
    """The Voeding vandaag card: None without the beta or before the first meal ever (the card drops out, like other
    cards with nothing to say; the sidebar leads there); `empty` when nothing is logged today yet (one line, no bars)."""
    if not betas.enabled(u.scope.engine, u.id, FEATURE) or not meals.history(u.scope):
        return None
    view = day_view(u, today, today, now_hhmm)
    if not view["meals"]:
        return {"empty": True, "today": today.isoformat(), "targets": view["targets"], "context": view["context"]}
    return {k: view[k] for k in ("today", "meals", "totals", "per_kg", "targets", "context", "last_meal", "burn_kcal")} | {"empty": False}


def make_router(current_user: Callable, today: Callable[[], date], now: Callable[[], datetime]) -> APIRouter:
    r = APIRouter()

    def member(u=Depends(current_user)):
        if not betas.enabled(u.scope.engine, u.id, FEATURE):
            raise ApiError(403, "nutrition_off")
        return u

    def admin(u=Depends(current_user)):
        if u.via != "cookie" or not u.is_admin:
            raise ApiError(403, "admins_only")
        return u

    @r.get("/api/nutrition/day")
    def get_day(day: str | None = None, u=Depends(member)):
        t = today()
        return day_view(u, _parse_day(day, t), t, now().strftime("%H:%M"))

    @r.post("/api/nutrition/meals", status_code=201)
    def create(body: MealIn, u=Depends(member)):
        try:
            return meals.create(u.scope, day=body.day, eaten_at=body.eaten_at, moment=body.moment, input=body.input, note=body.note,
                                items=[i.model_dump(exclude_none=True) for i in body.items])
        except meals.MealError as e:
            raise _meal_error(e) from None

    @r.patch("/api/nutrition/meals/{meal_id}")
    def change(meal_id: int, body: MealPatch, u=Depends(member)):
        fields = body.model_dump(exclude_unset=True, exclude={"items"})
        items = [i.model_dump(exclude_none=True) for i in body.items] if body.items is not None else None
        try:
            out = meals.change(u.scope, meal_id, items=items, **fields)
        except meals.MealError as e:
            raise _meal_error(e) from None
        if out is None:
            raise ApiError(404, "meal_not_found")
        return out

    @r.delete("/api/nutrition/meals/{meal_id}")
    def remove(meal_id: int, u=Depends(member)):
        if not meals.remove(u.scope, meal_id):
            raise ApiError(404, "meal_not_found")
        return {"ok": True}

    @r.get("/api/nutrition/meals")
    def between(start: str = Query(alias="from"), end: str = Query(alias="to"), u=Depends(member)):
        t = today()
        a, b = _parse_day(start, t), _parse_day(end, t)
        if b < a or (b - a).days > MAX_RANGE_DAYS:
            raise ApiError(422, "invalid_date", date=f"{start}..{end}")
        return meals.between(u.scope, a.isoformat(), b.isoformat())

    @r.get("/api/nutrition/foods/search")
    def search(q: str = Query("", max_length=100), limit: int = Query(20, ge=1, le=50), u=Depends(member)):
        found = foods.search(u.scope, q, limit, meals.history(u.scope))
        mine = meals.portions(u.scope, [f["ref"] for f in found])
        return [{**f, "portion_g": (mine.get(f["ref"]) or {}).get("grams") or f.get("default_portion_g")} for f in found]

    @r.get("/api/nutrition/foods/recent")
    def recent(days: int = Query(14, ge=1, le=90), u=Depends(member)):
        """The foods logged lately, most used first, with the usual portion: one tap to add again."""
        t = today()
        counts: dict[str, int] = {}
        for m in meals.between(u.scope, (t - timedelta(days=days)).isoformat(), t.isoformat()):
            for it in m["items"]:
                counts[it["food_ref"]] = counts.get(it["food_ref"], 0) + 1
        mine = meals.portions(u.scope, list(counts))
        out = []
        for ref, n in sorted(counts.items(), key=lambda x: -x[1])[:20]:
            f = foods.get(u.scope, ref)
            if f:
                out.append({**f, "uses": n, "portion_g": (mine.get(ref) or {}).get("grams") or f.get("default_portion_g")})
        return out

    @r.post("/api/nutrition/admin/nevo")
    async def import_nevo(request: Request, u=Depends(admin)):
        try:
            data = await read_limited(request.stream(), NEVO_MAX_BYTES)
        except UploadTooLarge:
            raise ApiError(413, "upload_too_large", max_mb=NEVO_MAX_BYTES // (1024 * 1024)) from None
        if not data:
            raise ApiError(422, "upload_empty")
        try:
            return nevo.import_foods(u.scope.engine, nevo.csv_text(data))
        except (nevo.NevoFormatError, UnicodeDecodeError, ValueError) as e:
            raise ApiError(422, "nevo_format", reason=str(e)[:200]) from None

    @r.get("/api/nutrition/admin/nevo")
    def nevo_status(u=Depends(admin)):
        return {"version": nevo.current_version(u.scope.engine)}

    return r
