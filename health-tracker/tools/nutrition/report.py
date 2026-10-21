"""Nutrition as an agent reads it (api/mcp.py): one day or a range as markdown, the last seven days for get_context,
and the evening before a night for get_day and the Sleep & body timeline. Dutch, like the other tools' text.

Logged values are estimates: amounts from photos and corrected grams, nutrients from the food table. Coverage (days with
at least COVERED_MEALS meals) says how complete a day is; a day with one logged meal is not a day of eating little.
"""

from __future__ import annotations

from datetime import date, timedelta

from tools import db
from tools.nutrition import meals, targets
from tools.nutrition.nutrients import ALCOHOL_UNIT_G

COVERED_MEALS = 2
EVENING_FROM = "19:00"  # meals from here on count as the evening before the night
LATE_LARGE = ("20:30", 600)  # a meal from this time with at least this many kcal: late and large
MAX_RANGE_DAYS = 92
MOMENT_NL = {
    "breakfast": "ontbijt",
    "lunch": "lunch",
    "dinner": "diner",
    "snack": "tussendoor",
    "training": "tijdens training",
    "drinks": "drinken",
}
DAY_TYPE_NL = {
    "rest": "rustdag",
    "easy": "rustige dag",
    "moderate": "matige trainingsdag",
    "long": "lange of zware training",
    "race": "wedstrijd of > 3 uur",
}


def _num(v, digits=0) -> str:
    if v is None:
        return "-"
    return f"{v:.{digits}f}".replace(".", ",") if digits else str(round(v))


def _range(r) -> str:
    return f"{_num(r[0], 1)}-{_num(r[1], 1)}" if r else "-"


def day_summary(day_meals: list[dict], target: dict) -> dict:
    """The numbers of one day: totals, g/kg against the target, alcohol, last meal, covered."""
    t = meals.day_totals(day_meals)
    w = target.get("weight_kg")
    return {
        "kcal": t["energy_kcal"],
        "carbs_g": t["carbs_g"],
        "protein_g": t["protein_g"],
        "fat_g": t["fat_g"],
        "fiber_g": t["fiber_g"],
        "alcohol_g": t["alcohol_g"],
        "salt_g": t["salt_g"],
        "carbs_per_kg": targets.per_kg(t["carbs_g"], w),
        "protein_per_kg": targets.per_kg(t["protein_g"], w),
        "meals": len(day_meals),
        "last_meal": meals.last_meal(day_meals),
        "covered": len(day_meals) >= COVERED_MEALS,
    }


def evening(s: db.Scope, day: str) -> dict | None:
    """What was eaten and drunk on the evening of `day` (from EVENING_FROM): the last meal's time, alcohol in units
    and whether a late, large meal was among it. None when nothing was logged that evening."""
    late = [m for m in meals.between(s, day, day) if m["eaten_at"] >= EVENING_FROM]
    if not late:
        return None
    alcohol = sum(m["totals"]["alcohol_g"] for m in late)
    last = max(m["eaten_at"] for m in late)
    big = [m for m in late if m["eaten_at"] >= LATE_LARGE[0] and m["totals"]["energy_kcal"] >= LATE_LARGE[1]]
    return {
        "day": day,
        "last_meal": last,
        "alcohol_units": round(alcohol / ALCOHOL_UNIT_G, 1),
        "kcal": round(sum(m["totals"]["energy_kcal"] for m in late)),
        "late_large": bool(big),
        "minute": int(last[:2]) * 60 + int(last[3:5]),
    }


def evening_line(e: dict | None) -> str:
    if not e:
        return ""
    parts = [f"laatste maaltijd {e['last_meal']}", f"{e['kcal']} kcal na {EVENING_FROM}"]
    if e["alcohol_units"]:
        parts.append(f"alcohol {_num(e['alcohol_units'], 1)} eenheden")
    if e["late_large"]:
        parts.append(f"late grote maaltijd (na {LATE_LARGE[0]}, {LATE_LARGE[1]}+ kcal)")
    return "Avond ervoor (voeding): " + ", ".join(parts) + "."


def day_md(day_meals: list[dict], target: dict) -> str:
    """One day: per meal its items and grams, the totals, carbs and protein per kg against the day's target."""
    d = day_summary(day_meals, target)
    out = [f"# Voeding {target['day']} ({DAY_TYPE_NL.get(target['day_type'], target['day_type'])})"]
    if not day_meals:
        out.append("Niets gelogd op deze dag.")
    for m in day_meals:
        out.append(
            f"\n## {m['eaten_at']} {MOMENT_NL.get(m['moment'], m['moment'])} (id {m['id']}, {_num(m['totals']['energy_kcal'])} kcal)"
        )
        out += [
            f"- {it['name']}: {_num(it['grams'])} {it['unit']}" + (" (geschat)" if it["grams_source"] == "ai" else "") for it in m["items"]
        ]
    if day_meals:
        out += [
            "",
            "| | Gegeten | Doel |",
            "|---|---|---|",
            f"| Energie | {_num(d['kcal'])} kcal | - |",
            f"| Koolhydraten | {_num(d['carbs_g'])} g ({_num(d['carbs_per_kg'], 1)} g/kg) | {_range(target['carbs_per_kg'])} g/kg |",
            f"| Eiwit | {_num(d['protein_g'])} g ({_num(d['protein_per_kg'], 1)} g/kg) | {_range(target['protein_per_kg'])} g/kg |",
            f"| Vet | {_num(d['fat_g'])} g | - |",
            f"| Vezels | {_num(d['fiber_g'])} g | - |",
            f"| Alcohol | {_num(d['alcohol_g'])} g ({_num((d['alcohol_g'] or 0) / ALCOHOL_UNIT_G, 1)} eenheden) | - |",
            f"| Zout | {_num(d['salt_g'], 1)} g | 6 g richtlijn |",
        ]
        out.append(
            f"\nLaatste maaltijd {d['last_meal']}. {'Volledig gelogd' if d['covered'] else 'Waarschijnlijk niet alles gelogd'} ({d['meals']} {'maaltijd' if d['meals'] == 1 else 'maaltijden'})."
        )
    if target.get("weight_kg") is None:
        out.append("Geen gewicht in het profiel: doelen alleen per kg.")
    return "\n".join(out)


def range_md(
    s: db.Scope, start: date, end: date, activities: list[dict], sessions: list[dict], today: date, title: str | None = None
) -> str:
    """Per day of a range: kcal, carbs and protein per kg against that day's target, alcohol, meals, last meal."""
    weight = (db.get_setting(s, "profile_facts") or {}).get("weight_kg")
    by_day: dict[str, list[dict]] = {}
    for m in meals.between(s, start.isoformat(), end.isoformat()):
        by_day.setdefault(m["day"], []).append(m)
    paces = targets.pace_by_sport(activities, today)  # once, not per day
    out = [
        title or f"# Voeding {start.isoformat()} t/m {end.isoformat()}",
        "",
        "| Dag | Soort dag | kcal | Koolh. g/kg (doel) | Eiwit g/kg (doel) | Alcohol (eenh.) | Maaltijden | Laatste |",
        "|---|---|---|---|---|---|---|---|",
    ]
    covered = logged = 0
    day = start
    while day <= end:
        iso = day.isoformat()
        target = targets.for_day(day, today, activities, sessions, weight, paces)
        d = day_summary(by_day.get(iso, []), target)
        logged += d["meals"] > 0
        covered += d["covered"]
        out.append(
            f"| {iso} | {DAY_TYPE_NL.get(target['day_type'])} | {_num(d['kcal']) if d['meals'] else '-'} | "
            f"{_num(d['carbs_per_kg'], 1) if d['meals'] else '-'} ({_range(target['carbs_per_kg'])}) | "
            f"{_num(d['protein_per_kg'], 1) if d['meals'] else '-'} ({_range(target['protein_per_kg'])}) | "
            f"{_num((d['alcohol_g'] or 0) / ALCOHOL_UNIT_G, 1) if d['meals'] else '-'} | {d['meals']} | {d['last_meal'] or '-'} |"
        )
        day += timedelta(days=1)
    days = (end - start).days + 1
    out.append(
        f"\nDekking: {covered} van {days} dagen met minstens {COVERED_MEALS} maaltijden ({logged} met iets gelogd). "
        "Waarden zijn schattingen (foto's en gecorrigeerde grammen, voedingswaarden uit NEVO)."
    )
    if weight is None:
        out.append("Geen gewicht in het profiel: g/kg ontbreekt.")
    return "\n".join(out)


def week_md(s: db.Scope, today: date, activities: list[dict], sessions: list[dict]) -> str:
    """For get_context: the last seven days up to and including today."""
    start = today - timedelta(days=6)
    return range_md(
        s, start, today, activities, sessions, today, title=f"## Voeding, laatste 7 dagen: {start.isoformat()} t/m {today.isoformat()}"
    )
