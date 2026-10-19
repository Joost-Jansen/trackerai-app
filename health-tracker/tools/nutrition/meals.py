"""Meals and their items, per user: saving what the user confirmed, reading days back, the usual portion per food.

An item stores the nutrients of its amount as a snapshot (tools/nutrition/nutrients.py scale): a new food table
release, or an edited own food, never changes a day already logged. Editing an item's grams scales from the food
again when it still exists, else from the item's own snapshot.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, insert, select, update

from tools import db
from tools.nutrition import foods
from tools.nutrition.nutrients import scale, total

MOMENTS = ("breakfast", "lunch", "dinner", "snack", "training", "drinks")
INPUTS = ("photo", "search", "barcode", "repeat", "agent")
GRAMS_SOURCES = ("ai", "user", "memory")
MAX_GRAMS = 5000.0
MAX_ITEMS = 40
MEMORY_WEIGHT = 0.3  # the newest confirmed amount's weight in the running average: recent meals count more


class MealError(ValueError):
    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _item_values(s: db.Scope, item: dict, position: int, old: dict | None = None) -> dict:
    grams = float(item.get("grams") or 0)
    if not 0 < grams <= MAX_GRAMS:
        raise MealError("invalid_grams", max=int(MAX_GRAMS))
    ref = item.get("food_ref") or (old or {}).get("food_ref")
    food = foods.get(s, ref) if ref else None
    if food is not None:
        nutrients, name, unit = scale(food["per_100"], grams), item.get("name") or food["name"], food["unit"]
    elif old is not None:  # the food is gone (an own food deleted): scale the snapshot
        f = grams / old["grams"]
        nutrients = {k: (round(v * f, 3) if v is not None else None) for k, v in old["nutrients"].items()}
        name, unit = item.get("name") or old["name"], old["unit"]
    else:
        raise MealError("food_not_found", ref=ref or "")
    source = item.get("grams_source") or "user"
    if source not in GRAMS_SOURCES:
        raise MealError("invalid_choice", options=", ".join(GRAMS_SOURCES))
    return {
        "user_id": s.user_id, "position": position, "food_ref": ref, "name": str(name)[:200], "unit": unit, "grams": round(grams, 1),
        "grams_ai": item.get("grams_ai"), "grams_low": item.get("grams_low"), "grams_high": item.get("grams_high"),
        "grams_source": source, "confidence": item.get("confidence"), "nutrients": nutrients,
    }


def _check(day: str, eaten_at: str, moment: str, input_: str | None = None) -> None:
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise MealError("invalid_date", date=day) from None
    try:
        datetime.strptime(eaten_at, "%H:%M")
    except (TypeError, ValueError):
        raise MealError("invalid_time", time=eaten_at) from None
    if moment not in MOMENTS:
        raise MealError("invalid_choice", options=", ".join(MOMENTS))
    if input_ is not None and input_ not in INPUTS:
        raise MealError("invalid_choice", options=", ".join(INPUTS))


def create(s: db.Scope, *, day: str, eaten_at: str, moment: str, input: str, items: list[dict], note: str | None = None,
           photo_id: int | None = None, ai_run_id: int | None = None) -> dict:
    _check(day, eaten_at, moment, input)
    if not items:
        raise MealError("meal_empty")
    if len(items) > MAX_ITEMS:
        raise MealError("meal_too_many_items", max=MAX_ITEMS)
    values = [_item_values(s, it, i) for i, it in enumerate(items)]
    with s.engine.begin() as conn:
        mid = conn.execute(insert(db.meals).values(user_id=s.user_id, day=day, eaten_at=eaten_at, moment=moment, input=input,
                                                   note=note, photo_id=photo_id, ai_run_id=ai_run_id, created_at=_now())).inserted_primary_key[0]
        for v in values:
            conn.execute(insert(db.meal_items).values(meal_id=mid, **v))
    learn(s, values, day)
    return get(s, mid)


def _rows(s: db.Scope, where) -> list[dict]:
    with s.engine.connect() as conn:
        meals = [dict(r) for r in conn.execute(select(db.meals).where(db.meals.c.user_id == s.user_id, *where)
                                               .order_by(db.meals.c.day, db.meals.c.eaten_at, db.meals.c.id)).mappings()]
        ids = [m["id"] for m in meals]
        items = [dict(r) for r in conn.execute(select(db.meal_items).where(db.meal_items.c.user_id == s.user_id, db.meal_items.c.meal_id.in_(ids))
                                               .order_by(db.meal_items.c.meal_id, db.meal_items.c.position)).mappings()] if ids else []
    by_meal: dict[int, list[dict]] = {}
    for it in items:
        it.pop("user_id")
        by_meal.setdefault(it.pop("meal_id"), []).append(it)
    out = []
    for m in meals:
        m.pop("user_id")
        for k in ("created_at", "updated_at"):
            m[k] = m[k].isoformat() if m.get(k) else None
        m["items"] = by_meal.get(m["id"], [])
        m["totals"] = total([it["nutrients"] for it in m["items"]])
        out.append(m)
    return out


def get(s: db.Scope, meal_id: int) -> dict | None:
    rows = _rows(s, [db.meals.c.id == meal_id])
    return rows[0] if rows else None


def between(s: db.Scope, start: str, end: str) -> list[dict]:
    """Meals from `start` to `end` (days, inclusive), in time order."""
    return _rows(s, [db.meals.c.day >= start, db.meals.c.day <= end])


def change(s: db.Scope, meal_id: int, *, items: list[dict] | None = None, **fields) -> dict | None:
    """Edit a meal: its day, time, moment or note, and (items given) its items, which replace the old ones. An item with
    an `id` of this meal keeps what it knew (its food, the AI's estimate) unless the edit says otherwise."""
    meal = get(s, meal_id)
    if meal is None:
        return None
    fields = {k: v for k, v in fields.items() if k in ("day", "eaten_at", "moment", "note")}
    merged = {**meal, **fields}
    _check(merged["day"], merged["eaten_at"], merged["moment"])
    values = None
    if items is not None:
        if not items:
            raise MealError("meal_empty")
        if len(items) > MAX_ITEMS:
            raise MealError("meal_too_many_items", max=MAX_ITEMS)
        old = {it["id"]: it for it in meal["items"]}
        values, taught = [], []
        for i, it in enumerate(items):
            before = old.get(it.get("id"))
            if before is not None:
                given = {k: v for k, v in it.items() if v is not None}
                it = {**{k: before[k] for k in ("food_ref", "name", "grams", "grams_ai", "grams_low", "grams_high", "confidence", "grams_source")}, **given}
                if it["food_ref"] != before["food_ref"] and "name" not in given:
                    it.pop("name")  # swapped for another food: take that food's name
                if it["grams"] != before["grams"] and "grams_source" not in given:
                    it["grams_source"] = "user"  # the user moved the slider: no longer an estimate
            values.append(_item_values(s, it, i, before))
            if before is None or values[-1]["grams"] != before["grams"] or values[-1]["food_ref"] != before["food_ref"]:
                taught.append(values[-1])  # untouched items taught their amount when they were saved
    with s.engine.begin() as conn:
        conn.execute(update(db.meals).where(db.meals.c.user_id == s.user_id, db.meals.c.id == meal_id).values(updated_at=_now(), **fields))
        if values is not None:
            conn.execute(delete(db.meal_items).where(db.meal_items.c.user_id == s.user_id, db.meal_items.c.meal_id == meal_id))
            for v in values:
                conn.execute(insert(db.meal_items).values(meal_id=meal_id, **v))
    if values is not None:
        learn(s, taught, merged["day"])
    return get(s, meal_id)


def remove(s: db.Scope, meal_id: int) -> bool:
    """Delete a meal, its items and its photo."""
    with s.engine.begin() as conn:
        photo = conn.execute(select(db.meals.c.photo_id).where(db.meals.c.user_id == s.user_id, db.meals.c.id == meal_id)).first()
        if photo is None:
            return False
        conn.execute(delete(db.meal_items).where(db.meal_items.c.user_id == s.user_id, db.meal_items.c.meal_id == meal_id))
        conn.execute(delete(db.meals).where(db.meals.c.user_id == s.user_id, db.meals.c.id == meal_id))
        if photo[0] is not None:
            conn.execute(delete(db.meal_photos).where(db.meal_photos.c.user_id == s.user_id, db.meal_photos.c.id == photo[0]))
    return True


def history(s: db.Scope) -> dict[str, int]:
    """How often the user logged each food: search ranks those higher."""
    with s.engine.connect() as conn:
        rows = conn.execute(select(db.meal_items.c.food_ref, func.count()).where(db.meal_items.c.user_id == s.user_id)
                            .group_by(db.meal_items.c.food_ref)).all()
    return {ref: n for ref, n in rows}


# --- the usual portion -------------------------------------------------------------------------------------------


def learn(s: db.Scope, items: list[dict], day: str) -> None:
    """Every amount the user set (grams_source user) moves the food's usual portion: a running average in which the
    newest amount weighs MEMORY_WEIGHT. Estimates (ai) and amounts taken from memory teach nothing."""
    taught = [it for it in items if it["grams_source"] == "user"]
    if not taught:
        return
    with s.engine.begin() as conn:
        for it in taught:
            row = conn.execute(select(db.portion_memory).where(db.portion_memory.c.user_id == s.user_id,
                                                               db.portion_memory.c.food_ref == it["food_ref"])).mappings().first()
            if row is None:
                conn.execute(insert(db.portion_memory).values(user_id=s.user_id, food_ref=it["food_ref"], grams_typical=it["grams"], uses=1, last_used=day))
            else:
                typical = round((1 - MEMORY_WEIGHT) * row["grams_typical"] + MEMORY_WEIGHT * it["grams"], 1)
                conn.execute(update(db.portion_memory).where(db.portion_memory.c.user_id == s.user_id, db.portion_memory.c.food_ref == it["food_ref"])
                             .values(grams_typical=typical, uses=row["uses"] + 1, last_used=max(day, row["last_used"] or day)))


def portions(s: db.Scope, refs: list[str] | None = None) -> dict[str, dict]:
    """ref -> {grams, uses, last_used}: the user's usual portion of each food (all, or those in `refs`)."""
    q = select(db.portion_memory).where(db.portion_memory.c.user_id == s.user_id)
    if refs is not None:
        q = q.where(db.portion_memory.c.food_ref.in_(refs))
    with s.engine.connect() as conn:
        rows = conn.execute(q).mappings().all()
    return {r["food_ref"]: {"grams": r["grams_typical"], "uses": r["uses"], "last_used": r["last_used"]} for r in rows}


def day_totals(meals: list[dict]) -> dict:
    return total([it["nutrients"] for m in meals for it in m["items"]])


def last_meal(meals: list[dict]) -> str | None:
    """The time of the day's last meal or drink (HH:MM), None without meals."""
    return max((m["eaten_at"] for m in meals), default=None)



# --- favourites and "again" -----------------------------------------------------------------------------------

MAX_TEMPLATES = 100
TEMPLATE_FIELDS = ("food_ref", "name", "unit", "grams")


def _template_items(s: db.Scope, items: list[dict]) -> list[dict]:
    if not items:
        raise MealError("meal_empty")
    if len(items) > MAX_ITEMS:
        raise MealError("meal_too_many_items", max=MAX_ITEMS)
    out = []
    for it in items:
        food = foods.get(s, it.get("food_ref") or "")
        if food is None:
            raise MealError("food_not_found", ref=it.get("food_ref") or "")
        grams = float(it.get("grams") or 0)
        if not 0 < grams <= MAX_GRAMS:
            raise MealError("invalid_grams", max=int(MAX_GRAMS))
        out.append({"food_ref": food["ref"], "name": str(it.get("name") or food["name"])[:200], "unit": food["unit"], "grams": round(grams, 1)})
    return out


def templates(s: db.Scope) -> list[dict]:
    with s.engine.connect() as conn:
        rows = conn.execute(select(db.meal_templates).where(db.meal_templates.c.user_id == s.user_id)
                            .order_by(db.meal_templates.c.position, db.meal_templates.c.id)).mappings().all()
    return [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items() if k != "user_id"} for r in rows]


def create_template(s: db.Scope, *, name: str, items: list[dict], moment: str | None = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise MealError("template_name_required")
    if moment is not None and moment not in MOMENTS:
        raise MealError("invalid_choice", options=", ".join(MOMENTS))
    mine = templates(s)
    if len(mine) >= MAX_TEMPLATES:
        raise MealError("too_many_templates", max=MAX_TEMPLATES)
    values = _template_items(s, items)
    with s.engine.begin() as conn:
        tid = conn.execute(insert(db.meal_templates).values(user_id=s.user_id, name=name[:100], moment=moment, items=values,
                                                            position=len(mine), created_at=_now())).inserted_primary_key[0]
    return next(t for t in templates(s) if t["id"] == tid)


def change_template(s: db.Scope, tid: int, *, name: str | None = None, moment: str | None = None, items: list[dict] | None = None,
                    position: int | None = None) -> dict | None:
    mine = templates(s)
    if not any(t["id"] == tid for t in mine):
        return None
    values: dict = {}
    if name is not None:
        if not name.strip():
            raise MealError("template_name_required")
        values["name"] = name.strip()[:100]
    if moment is not None:
        if moment not in MOMENTS:
            raise MealError("invalid_choice", options=", ".join(MOMENTS))
        values["moment"] = moment
    if items is not None:
        values["items"] = _template_items(s, items)
    with s.engine.begin() as conn:
        if values:
            conn.execute(update(db.meal_templates).where(db.meal_templates.c.user_id == s.user_id, db.meal_templates.c.id == tid).values(**values))
        if position is not None:  # move it, renumber the rest
            order = [t["id"] for t in mine if t["id"] != tid]
            order.insert(max(0, min(position, len(order))), tid)
            for i, t in enumerate(order):
                conn.execute(update(db.meal_templates).where(db.meal_templates.c.user_id == s.user_id, db.meal_templates.c.id == t).values(position=i))
    return next(t for t in templates(s) if t["id"] == tid)


def delete_template(s: db.Scope, tid: int) -> bool:
    with s.engine.begin() as conn:
        return bool(conn.execute(delete(db.meal_templates).where(db.meal_templates.c.user_id == s.user_id, db.meal_templates.c.id == tid)).rowcount)


def again(s: db.Scope, day: str, moment: str) -> dict:
    """What to log again in one tap: favourites (those of this moment first) and the meals of the same moment the day
    before ("like yesterday")."""
    from datetime import date, timedelta

    yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    favourites = sorted(templates(s), key=lambda t: (t.get("moment") != moment, t["position"]))
    return {"favourites": favourites, "yesterday": [m for m in between(s, yesterday, yesterday) if m["moment"] == moment]}
