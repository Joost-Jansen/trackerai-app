"""How good photo analysis is, for the admin hub: Claude's grams against the grams people saved, per food group and per
month, and how many analyses ran (and their tokens) this month. Over all users, as counts and medians only.

An item counts when it came from a photo (grams_ai set) and the user set its amount (grams_source user); the error is
|saved - estimate| / saved. Items the user left as estimated say nothing about accuracy and are counted apart
("kept"), as are amounts that came from the usual portion ("memory": where the portion memory stood in for Claude).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import median

from sqlalchemy import func, select

from tools import db

MONTHS = 3
MIN_ITEMS = 5  # a food group with fewer corrected items shows no median


def _group(conn) -> dict[str, str]:
    """food_ref -> its food group (NEVO's English group names; other sources have none)."""
    return {f"{src}:{code}": grp for src, code, grp in conn.execute(select(db.foods.c.source, db.foods.c.source_code, db.foods.c.food_group)) if grp}


def stats(engine, today: date) -> dict:
    month = today.replace(day=1).isoformat()
    with engine.connect() as conn:
        runs = conn.execute(select(func.count(), func.coalesce(func.sum(db.nutrition_ai_runs.c.tokens_in), 0),
                                   func.coalesce(func.sum(db.nutrition_ai_runs.c.tokens_out), 0))
                            .where(db.nutrition_ai_runs.c.created_at >= month)).one()
        rows = conn.execute(select(db.meal_items.c.food_ref, db.meal_items.c.grams, db.meal_items.c.grams_ai, db.meal_items.c.grams_source, db.meals.c.day)
                            .join(db.meals, db.meals.c.id == db.meal_items.c.meal_id)
                            .where(db.meal_items.c.grams_ai.isnot(None))).all()
        groups = _group(conn)
    errors: dict[str, list[float]] = defaultdict(list)
    by_month: dict[str, list[float]] = defaultdict(list)
    kept = memory = 0
    for ref, grams, ai, source, day in rows:
        if source == "memory":
            memory += 1
        if source != "user":
            kept += source == "ai"
            continue
        if grams and ai:
            e = abs(grams - ai) / grams
            errors[groups.get(ref, "Other")].append(e)
            by_month[day[:7]].append(e)
    months = sorted(by_month)[-MONTHS:]
    return {
        "runs_month": runs[0], "tokens_in_month": int(runs[1]), "tokens_out_month": int(runs[2]),
        "corrected": sum(len(v) for v in errors.values()), "kept": kept, "memory": memory,
        "by_group": sorted(({"group": g, "items": len(v), "median_error": round(median(v), 3) if len(v) >= MIN_ITEMS else None}
                            for g, v in errors.items()), key=lambda x: -x["items"]),
        "by_month": [{"month": m, "items": len(by_month[m]), "median_error": round(median(by_month[m]), 3)} for m in months],
    }


def facts(engine, today: date) -> list[dict]:
    """The hub's key figures for Voeding (the shared admin page shows `facts` under each tracker)."""
    s = stats(engine, today)
    pct = lambda v: "-" if v is None else f"{round(v * 100)}%"  # noqa: E731
    out = [
        {"label": {"en": "Photo analyses this month", "nl": "Foto-analyses deze maand"}, "value": str(s["runs_month"]),
         "note": {"en": f"{s['tokens_in_month']:,} tokens in, {s['tokens_out_month']:,} out", "nl": f"{s['tokens_in_month']:,} tokens in, {s['tokens_out_month']:,} uit".replace(",", ".")}},
        {"label": {"en": "Photo items corrected", "nl": "Foto-items gecorrigeerd"}, "value": str(s["corrected"]),
         "note": {"en": f"{s['kept']} kept as estimated, {s['memory']} from the usual portion", "nl": f"{s['kept']} geschat gelaten, {s['memory']} uit de gebruikelijke portie"}},
    ]
    for m in s["by_month"]:
        out.append({"label": {"en": f"Gram error {m['month']}", "nl": f"Gramafwijking {m['month']}"}, "value": pct(m["median_error"]),
                    "note": {"en": f"median over {m['items']} items", "nl": f"mediaan over {m['items']} items"}})
    for g in s["by_group"][:6]:
        out.append({"label": {"en": f"Gram error: {g['group']}", "nl": f"Gramafwijking: {g['group']}"}, "value": pct(g["median_error"]),
                    "note": {"en": f"{g['items']} items", "nl": f"{g['items']} items"}})
    return out
