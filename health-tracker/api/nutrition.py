"""Nutrition (Voeding): meals per day, their totals against training-aware targets, and food search.

Behind the beta feature `nutrition` (api/betas.py): every route answers 403 nutrition_off for a user without it.

    GET    /api/nutrition/day?day=YYYY-MM-DD   totals, targets, meals with items, the day's training (default today)
    POST   /api/nutrition/meals                save a meal the user confirmed: {day, eaten_at, moment, input, items, note}
    PATCH  /api/nutrition/meals/{id}           change its day, time, moment, note or items (items replace the old ones)
    DELETE /api/nutrition/meals/{id}           the meal, its items and its photo
    GET    /api/nutrition/foods/search?q=      NEVO, cached Open Food Facts and your own foods, best first
    GET    /api/nutrition/foods/barcode/{ean}  a packaged product from Open Food Facts (cached after the first time)
    POST   /api/nutrition/photo                analyse a meal photo (raw JPEG/PNG body): a draft for the review screen;
                                               only the photo is stored, by the user's setting; needs photo analysis on
    GET    /api/nutrition/photos/{id}          a meal photo, own only
    GET    /api/nutrition/again?day=&moment=   favourites and the same moment yesterday, to log again in one tap
    GET/POST/PATCH/DELETE /api/nutrition/templates[/{id}]   favourites
    GET/PUT /api/nutrition/settings            photo analysis on/off, how long photos are kept, an optional kcal target
    GET    /api/nutrition/trends?days=30       per day: energy in and Garmin's burn, carbohydrate and protein per kg
                                               against that day's target, training load, alcohol, salt, saturated fat,
                                               iron, meals (the Trends tab)
    POST   /api/nutrition/admin/nevo           admins: import a NEVO-online release (the CSV or RIVM's zip as the body)

Photo analysis sends the photo (without metadata) to Anthropic: off by default, switched on per user, and only offered
when the server has ANTHROPIC_API_KEY (tools/nutrition/recognize.py).

Items: {food_ref, grams, grams_source?} plus, from a photo, {grams_ai, grams_low, grams_high, confidence}. Nutrient
values always come from the food table (tools/nutrition/foods.py), never from the request.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable

import trackerai_ai
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from api import betas
from api.errors import ApiError
from api.dashboard import max_by_sport, resting_hr
from api.plans import enrich
from tools import db
from tools.nutrition import foods, match, meals, nevo, off, photos, recognize, references, targets, usda
from tools.analytics import fitness_series
from tools.nutrition.nutrients import KCAL_PER_G, energy_split
from trackerai_websec.uploads import UploadTooLarge, read_limited

FEATURE = "nutrition"
NEVO_MAX_BYTES = 40 * 1024 * 1024  # RIVM's zip is about 27 MB (the CSV inside 1.7 MB)
MAX_RANGE_DAYS = 400
SETTINGS_KEY = "nutrition"  # setting: {ai, photos, kcal_target, norms}
DEFAULTS = {"ai": False, "photos": "30d", "kcal_target": None, "norms": None}  # norms: men | women (tools/nutrition/references.py)
PHOTO_KEEP = ("30d", "keep", "never")


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
    photo_id: int | None = None
    ai_run_id: int | None = None


class TemplateItem(BaseModel):
    food_ref: str = Field(max_length=60)
    name: str | None = Field(None, max_length=200)
    grams: float


class TemplateIn(BaseModel):
    name: str | None = Field(None, max_length=100)
    moment: str | None = Field(None, max_length=12)
    items: list[TemplateItem] | None = Field(None, max_length=meals.MAX_ITEMS)
    position: int | None = Field(None, ge=0, le=1000)


class SettingsIn(BaseModel):
    ai: bool | None = None
    photos: str | None = Field(None, max_length=8)
    kcal_target: int | None = Field(None, ge=800, le=8000)
    clear_kcal_target: bool = False
    norms: str | None = Field(None, max_length=8)


class PortionIn(BaseModel):
    grams: float = Field(gt=0, le=meals.MAX_GRAMS)


class UserFoodIn(BaseModel):
    name: str | None = Field(None, max_length=200)
    brand: str | None = Field(None, max_length=100)
    unit: str | None = Field(None, max_length=2)
    default_portion_g: float | None = Field(None, gt=0, le=meals.MAX_GRAMS)
    per_100: dict[str, float | None] | None = None


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


def with_values(scope, templates: list[dict]) -> list[dict]:
    """Favourites with each item's values per 100 from the food table, so the editor can add them up."""
    cache: dict[str, dict | None] = {}
    for t in templates:
        for it in t["items"]:
            if it["food_ref"] not in cache:
                cache[it["food_ref"]] = foods.get(scope, it["food_ref"])
            it["per_100"] = (cache[it["food_ref"]] or {}).get("per_100")
    return templates


def micros(scope, totals: dict, today: date) -> dict:
    """The Vitamins and minerals table: amounts against the Dutch norms the user chose (men's or women's)."""
    group = settings_of(scope)["norms"]
    years = references.age((db.get_setting(scope, "profile_facts") or {}).get("birth_year"), today)
    return {"group": group, "rows": references.table(totals, group, years), "source": references.SOURCE}


def settings_of(scope) -> dict:
    return {**DEFAULTS, **(db.get_setting(scope, SETTINGS_KEY) or {})}


def ai_on(scope) -> bool:
    """Photo analysis: the user switched it on and the server has a key."""
    return bool(settings_of(scope)["ai"]) and trackerai_ai.available()


def weight_of(scope) -> float | None:
    return (db.get_setting(scope, "profile_facts") or {}).get("weight_kg")


def plan_sessions(u, today: date) -> list[dict]:
    plan = db.active_plan(u.scope)
    return enrich(plan, u.store.activities, u.store.routes, today)["sessions"] if plan else []


def day_view(u, day: date, today: date, now_hhmm: str | None = None, sessions: list[dict] | None = None) -> dict:
    """Everything the Dag tab and Vandaag show of one day. `sessions`: the active plan's sessions as api.plans.enrich
    gives them, when the caller has them already (/api/dashboard)."""
    s = u.scope
    logged = meals.between(s, day.isoformat(), day.isoformat())
    totals = meals.day_totals(logged)
    weight = weight_of(s)
    sessions = plan_sessions(u, today) if sessions is None else sessions
    target = targets.for_day(day, today, u.store.activities, sessions, weight)
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
        "ai": ai_on(s),
        "kcal_target": settings_of(s)["kcal_target"],
        "micros": micros(s, totals, today),
    }


TREND_DAYS = (14, 30, 90)
_loads: dict[tuple, dict[str, float]] = {}  # training load per day, until the next sync (like /api/trends' cache)


def daily_load(u, today: date) -> dict[str, float]:
    store = u.store
    key = (u.id, today, store.last_sync, len(store.activities))
    if key not in _loads:
        if len(_loads) > 64:
            _loads.clear()
        series = fitness_series(store.activities, resting_hr(store.wellness, today, store.rhr_fallback), max_by_sport(store.zones, store.activities), end=today)
        _loads[key] = {r["date"]: r["load"] for r in series}
    return _loads[key]


def trends(u, today: date, days: int) -> dict:
    """One row per day for the last `days` days up to today (the Trends tab)."""
    s, store = u.scope, u.store
    start = today - timedelta(days=days - 1)
    weight = weight_of(s)
    sessions = plan_sessions(u, today)
    load = daily_load(u, today)
    paces = targets.pace_by_sport(store.activities, today)
    by_day: dict[str, list[dict]] = {}
    for m in meals.between(s, start.isoformat(), today.isoformat()):
        by_day.setdefault(m["day"], []).append(m)
    rows = []
    for i in range(days):
        day = start + timedelta(days=i)
        iso = day.isoformat()
        logged = by_day.get(iso, [])
        t = meals.day_totals(logged)
        target = targets.for_day(day, today, store.activities, sessions, weight, paces)
        kcal = t["energy_kcal"]
        rows.append({
            "day": iso, "meals": len(logged), "covered": len(logged) >= 2,
            "kcal": kcal if logged else None, "burn_kcal": (store.wellness.get(iso) or {}).get("total_kcal"),
            "carbs_per_kg": targets.per_kg(t["carbs_g"], weight) if logged else None,
            "protein_per_kg": targets.per_kg(t["protein_g"], weight) if logged else None,
            "carbs_target": target["carbs_per_kg"], "protein_target": target["protein_per_kg"], "day_type": target["day_type"],
            "load": load.get(iso, 0.0),
            "alcohol_g": t["alcohol_g"] if logged else None, "salt_g": t["salt_g"] if logged else None,
            "sat_fat_share": round(t["sat_fat_g"] * KCAL_PER_G["fat_g"] / kcal, 3) if logged and kcal else None,
            "unsat_fat_share": round((t["mufa_g"] + t["pufa_g"]) * KCAL_PER_G["fat_g"] / kcal, 3) if logged and kcal else None,
            "iron_mg": t["iron_mg"] if logged else None,
        })
    group = settings_of(s)["norms"]
    iron = references.norm("iron_mg", group, references.age((db.get_setting(s, "profile_facts") or {}).get("birth_year"), today))
    return {"days": rows, "weight_kg": weight, "covered": sum(r["covered"] for r in rows), "iron_reference": iron[1] if iron else None}


def dashboard_block(u, today: date, now_hhmm: str, sessions: list[dict]) -> dict | None:
    """The Voeding vandaag card: None without the beta or before the first meal ever (the card drops out, like other
    cards with nothing to say; the sidebar leads there); `empty` when nothing is logged today yet (one line, no bars)."""
    if not betas.enabled(u.scope.engine, u.id, FEATURE) or not meals.history(u.scope):
        return None
    view = day_view(u, today, today, now_hhmm, sessions)
    if not view["meals"]:
        return {"empty": True, "today": today.isoformat(), "targets": view["targets"], "context": view["context"], "ai": view["ai"]}
    return {k: view[k] for k in ("today", "meals", "totals", "per_kg", "targets", "context", "last_meal", "burn_kcal", "ai")} | {"empty": False}


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
        if body.photo_id is not None and not photos.owns(u.scope, body.photo_id):
            raise ApiError(404, "photo_not_found")
        run_id = body.ai_run_id if body.ai_run_id is not None and recognize.owns_run(u.scope, body.ai_run_id) else None
        try:
            meal = meals.create(u.scope, day=body.day, eaten_at=body.eaten_at, moment=body.moment, input=body.input, note=body.note,
                                items=[i.model_dump(exclude_none=True) for i in body.items], photo_id=body.photo_id, ai_run_id=run_id)
        except meals.MealError as e:
            raise _meal_error(e) from None
        if body.photo_id is not None:
            photos.attach(u.scope, body.photo_id, settings_of(u.scope)["photos"])
        return meal

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

    @r.get("/api/nutrition/trends")
    def get_trends(days: int = 30, u=Depends(member)):
        if days not in TREND_DAYS:
            raise ApiError(422, "invalid_choice", options=", ".join(map(str, TREND_DAYS)))
        return trends(u, today(), days)

    @r.get("/api/nutrition/meals")
    def between(start: str = Query(alias="from"), end: str = Query(alias="to"), u=Depends(member)):
        t = today()
        a, b = _parse_day(start, t), _parse_day(end, t)
        if b < a or (b - a).days > MAX_RANGE_DAYS:
            raise ApiError(422, "invalid_date", date=f"{start}..{end}")
        return meals.between(u.scope, a.isoformat(), b.isoformat())

    @r.get("/api/nutrition/foods/search")
    def search(q: str = Query("", max_length=100), limit: int = Query(20, ge=1, le=50), u=Depends(member)):
        history = meals.history(u.scope)
        found = foods.search(u.scope, q, limit, history)
        if len(found) < usda.FEW and usda.fill(u.scope, q):  # NEVO lacks it: USDA, when the server has a key
            found = foods.search(u.scope, q, limit, history)
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

    @r.get("/api/nutrition/foods/barcode/{ean}")
    def barcode(ean: str, u=Depends(member)):
        if not off.valid_ean(ean):
            raise ApiError(422, "invalid_barcode")
        try:
            food = off.lookup(u.scope, ean)
        except off.LookupFailed:
            raise ApiError(502, "barcode_lookup_failed") from None
        except off.NoNutrients:
            raise ApiError(404, "barcode_no_nutrients") from None
        if food is None:
            raise ApiError(404, "barcode_not_found")
        mine = meals.portions(u.scope, [food["ref"]])
        return {**food, "portion_g": (mine.get(food["ref"]) or {}).get("grams") or food.get("default_portion_g")}

    @r.post("/api/nutrition/photo")
    async def photo(request: Request, u=Depends(member)):
        if not trackerai_ai.available():
            raise ApiError(403, "nutrition_ai_unavailable")
        mine = settings_of(u.scope)
        if not mine["ai"]:
            raise ApiError(403, "nutrition_ai_off")
        if recognize.runs_last_day(u.scope) >= recognize.daily_limit():
            raise ApiError(429, "nutrition_ai_limit", max=recognize.daily_limit())
        try:
            data = await read_limited(request.stream(), photos.MAX_BYTES)
            mime, image = photos.clean(data)
        except UploadTooLarge:
            raise ApiError(413, "upload_too_large", max_mb=photos.MAX_BYTES // (1024 * 1024)) from None
        except photos.PhotoError:
            raise ApiError(422, "photo_invalid") from None
        photo_id = photos.save(u.scope, mime, image, mine["photos"])
        try:
            run_id, answer = recognize.recognise(u.scope, mime, image)
        except trackerai_ai.AiError as e:
            # the photo is kept: the review screen falls back to search with it
            return {"photo_id": photo_id, "ai_run_id": None, "failed": e.code, "items": [], "hidden_extras": [], "moment_guess": None}
        return {"photo_id": photo_id, "ai_run_id": run_id, "failed": None, **match.draft(u.scope, answer)}

    @r.get("/api/nutrition/photos/{photo_id}")
    def photo_file(photo_id: int, u=Depends(member)):
        found = photos.load(u.scope, photo_id)
        if found is None:
            raise ApiError(404, "photo_not_found")
        mime, data = found
        return Response(data, media_type=mime, headers={"Cache-Control": "private, max-age=86400"})

    @r.get("/api/nutrition/again")
    def again(day: str | None = None, moment: str = Query("breakfast", max_length=12), u=Depends(member)):
        if moment not in meals.MOMENTS:
            raise ApiError(422, "invalid_choice", options=", ".join(meals.MOMENTS))
        out = meals.again(u.scope, _parse_day(day, today()).isoformat(), moment)
        return {**out, "favourites": with_values(u.scope, out["favourites"])}

    @r.get("/api/nutrition/templates")
    def list_templates(u=Depends(member)):
        return with_values(u.scope, meals.templates(u.scope))

    @r.post("/api/nutrition/templates", status_code=201)
    def add_template(body: TemplateIn, u=Depends(member)):
        try:
            return meals.create_template(u.scope, name=body.name or "", moment=body.moment,
                                         items=[i.model_dump(exclude_none=True) for i in body.items or []])
        except meals.MealError as e:
            raise _meal_error(e) from None

    @r.patch("/api/nutrition/templates/{tid}")
    def change_template(tid: int, body: TemplateIn, u=Depends(member)):
        try:
            out = meals.change_template(u.scope, tid, name=body.name, moment=body.moment, position=body.position,
                                        items=[i.model_dump(exclude_none=True) for i in body.items] if body.items is not None else None)
        except meals.MealError as e:
            raise _meal_error(e) from None
        if out is None:
            raise ApiError(404, "template_not_found")
        return out

    @r.delete("/api/nutrition/templates/{tid}")
    def remove_template(tid: int, u=Depends(member)):
        if not meals.delete_template(u.scope, tid):
            raise ApiError(404, "template_not_found")
        return {"ok": True}

    def settings_view(u) -> dict:
        weight = weight_of(u.scope)
        return {**settings_of(u.scope), "ai_available": trackerai_ai.available(), "weight_kg": weight,
                "day_types": {k: {"carbs_per_kg": list(v["carbs"]), "protein_per_kg": list(v["protein"])} for k, v in targets.DAY_TYPES.items()}}

    @r.get("/api/nutrition/settings")
    def get_settings(u=Depends(member)):
        return settings_view(u)

    @r.put("/api/nutrition/settings")
    def put_settings(body: SettingsIn, u=Depends(member)):
        current = settings_of(u.scope)
        new = dict(current)
        if body.ai is not None:
            if body.ai and not trackerai_ai.available():
                raise ApiError(403, "nutrition_ai_unavailable")
            new["ai"] = body.ai
        if body.photos is not None:
            if body.photos not in PHOTO_KEEP:
                raise ApiError(422, "invalid_choice", options=", ".join(PHOTO_KEEP))
            new["photos"] = body.photos
        if body.kcal_target is not None:
            new["kcal_target"] = body.kcal_target
        if body.clear_kcal_target:
            new["kcal_target"] = None
        if body.norms is not None:
            if body.norms not in (*references.GROUPS, "none"):
                raise ApiError(422, "invalid_choice", options="men, women, none")
            new["norms"] = None if body.norms == "none" else body.norms
        db.set_setting(u.scope, SETTINGS_KEY, new)
        if new["photos"] != current["photos"]:
            photos.retention_changed(u.scope, new["photos"])
        return settings_view(u)

    # --- My foods: your usual portions, your own products, what you scanned ---

    @r.get("/api/nutrition/portions")
    def list_portions(u=Depends(member)):
        out = []
        for ref, p in sorted(meals.portions(u.scope).items(), key=lambda x: -x[1]["uses"]):
            f = foods.get(u.scope, ref)
            if f:
                out.append({"ref": ref, "name": f["name"], "name_en": f.get("name_en"), "source": f["source"], "unit": f["unit"], **p})
        return out

    @r.put("/api/nutrition/portions/{ref}")
    def set_portion(ref: str, body: PortionIn, u=Depends(member)):
        if foods.get(u.scope, ref) is None:
            raise ApiError(404, "food_not_found", ref=ref)
        meals.set_portion(u.scope, ref, body.grams)
        return {"ok": True}

    @r.delete("/api/nutrition/portions/{ref}")
    def reset_portion(ref: str, u=Depends(member)):
        meals.reset_portion(u.scope, ref)
        return {"ok": True}

    @r.get("/api/nutrition/user-foods")
    def list_user_foods(u=Depends(member)):
        mine = foods.user_foods(u.scope)
        scanned = [f for ref in meals.history(u.scope) if ref.startswith("off:") for f in [foods.get(u.scope, ref)] if f]
        return {"own": mine, "scanned": sorted(scanned, key=lambda f: f["name"].lower())}

    @r.post("/api/nutrition/user-foods", status_code=201)
    def add_user_food(body: UserFoodIn, u=Depends(member)):
        try:
            return foods.create_user_food(u.scope, **body.model_dump(exclude_none=True))
        except foods.FoodError as e:
            raise ApiError(422, e.code, **e.params) from None

    @r.patch("/api/nutrition/user-foods/{fid}")
    def change_user_food(fid: int, body: UserFoodIn, u=Depends(member)):
        try:
            out = foods.change_user_food(u.scope, fid, **body.model_dump(exclude_unset=True))
        except foods.FoodError as e:
            raise ApiError(422, e.code, **e.params) from None
        if out is None:
            raise ApiError(404, "food_not_found", ref=f"user:{fid}")
        return out

    @r.delete("/api/nutrition/user-foods/{fid}")
    def remove_user_food(fid: int, u=Depends(member)):
        if not foods.delete_user_food(u.scope, fid):
            raise ApiError(404, "food_not_found", ref=f"user:{fid}")
        return {"ok": True}  # logged meals keep their snapshot

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
