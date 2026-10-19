"""Carbohydrate and protein targets per kg body weight, scaled to a day's training load.

A day's type comes from its training: what was done on a past day, what the plan says for a day ahead, and for today
both (done so far plus the plan's sessions still open). The day before a race or a session over three hours gets that
day's carbohydrate range, the day before a long or hard session at least a moderate day's (BEFORE): fuelling starts the
day before. That is also where Vandaag's "tomorrow" line comes from.

The ranges follow common sports-nutrition guidance for endurance athletes (Thomas, Erdman & Burke 2016, ACSM/AND/DC
joint position on nutrition and athletic performance; Burke et al. 2011 on carbohydrate per kg by training load).
They are a guide, not a prescription; adjust them in DAY_TYPES only.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from statistics import median

# g per kg body weight per day: (low, high). Order is from light to heavy: a later type wins when a day qualifies twice.
DAY_TYPES: dict[str, dict[str, tuple[float, float]]] = {
    "rest": {"carbs": (3.0, 5.0), "protein": (1.6, 2.0)},
    "easy": {"carbs": (3.0, 5.0), "protein": (1.6, 2.0)},
    "moderate": {"carbs": (5.0, 7.0), "protein": (1.6, 2.0)},
    "long": {"carbs": (6.0, 10.0), "protein": (1.6, 2.0)},
    "race": {"carbs": (8.0, 12.0), "protein": (1.6, 2.0)},
}
ORDER = tuple(DAY_TYPES)
BEFORE = {"race": "race", "long": "moderate"}  # tomorrow's type -> the least today's type becomes
EASY_MAX_MIN = 50  # below this, and not hard: easy (under an hour in Z1-Z2)
LONG_MIN = 90  # from here a session is long; from 60 min with hard work too
HARD_LONG_MIN = 60
RACE_MIN = 180  # over three hours counts as a race day
HARD_SHARE = 0.25  # an activity with this share of its zone time in Z4-Z5 (or twice this in Z3-Z5) was hard work
NOT_TRAINING = {"walking", "steps", "rest"}  # daily movement: not part of the load that sets the target
# A session's kind that means hard work (same spirit as api/dashboard.py RACE_KIND: whole words, Dutch and English).
HARD_KIND = re.compile(r"\b(interval\w*|tempo\w*|drempel\w*|threshold|fartlek|heuvel\w*|hill\w*|vo2\w*|sprint\w*|race|wedstrijd|marathon\w*)\b", re.I)
RACE_KIND = re.compile(r"\b(wedstrijd|race|marathon|triathlon)\b(?!\s*-?\s*(tempo|pace))", re.I)
# Minutes per km when a planned session has a distance and no duration, and the user has no history in that sport.
DEFAULT_MIN_PER_KM = {"run": 6.0, "bike": 2.4, "swim": 25.0, "hiking": 12.0}
RECENT_DAYS = 90
AFTER_TRAINING_H = 4  # Vandaag says "protein within a few hours" this long after a session ends


def _day(a: dict) -> str:
    return a["start_local"][:10]


def pace_by_sport(activities: list[dict], today: date) -> dict[str, float]:
    """The user's median minutes per km per sport over the last RECENT_DAYS, to size a planned session by distance."""
    since = (today - timedelta(days=RECENT_DAYS)).isoformat()
    paces: dict[str, list[float]] = {}
    for a in activities:
        if _day(a) >= since and (a.get("distance_km") or 0) > 0.2 and a.get("moving_time_s"):
            paces.setdefault(a["sport"], []).append(a["moving_time_s"] / 60 / a["distance_km"])
    return {sport: median(v) for sport, v in paces.items()}


def _activity_load(a: dict) -> dict:
    zones = a.get("hr_zones_s") or {}
    total = sum(zones.values()) or 0
    high = (zones.get("Z4", 0) + zones.get("Z5", 0)) / total if total else 0
    mid = (zones.get("Z3", 0) + zones.get("Z4", 0) + zones.get("Z5", 0)) / total if total else 0
    return {
        "minutes": round((a.get("moving_time_s") or 0) / 60),
        "hard": high >= HARD_SHARE or mid >= 2 * HARD_SHARE,
        "race": bool(a.get("race")),
        "sport": a["sport"], "distance_km": a.get("distance_km"), "name": a.get("name"), "done": True,
    }


def _session_load(s: dict, paces: dict[str, float]) -> dict:
    minutes = s.get("duration_min")
    if not minutes and s.get("distance_km"):
        minutes = s["distance_km"] * paces.get(s["sport"], DEFAULT_MIN_PER_KM.get(s["sport"], 6.0))
    zone = s.get("target_zone") or ""
    top = max((int(z) for z in re.findall(r"[1-5]", zone)), default=0)
    kind = s.get("kind") or ""
    return {
        "minutes": round(minutes or 0),
        "hard": top >= 3 or bool(HARD_KIND.search(kind)),
        "race": bool(RACE_KIND.search(kind)),
        "sport": s["sport"], "distance_km": s.get("distance_km"), "kind": s.get("kind"), "done": False,
    }


def classify(loads: list[dict]) -> str:
    """The day type for a day's sessions (see DAY_TYPES)."""
    loads = [x for x in loads if x["sport"] not in NOT_TRAINING]
    minutes = sum(x["minutes"] for x in loads)
    hard = any(x["hard"] for x in loads)
    if not loads or minutes == 0:
        return "rest"
    if any(x["race"] for x in loads) or minutes > RACE_MIN:
        return "race"
    if minutes >= LONG_MIN or (hard and minutes >= HARD_LONG_MIN):
        return "long"
    if minutes >= EASY_MAX_MIN or hard:
        return "moderate"
    return "easy"


def day_loads(day: date, today: date, activities: list[dict], sessions: list[dict], paces: dict[str, float]) -> list[dict]:
    """What counts for `day`: done activities up to today, the plan's sessions from today on (today: only those not
    done yet, a done session's activity is already in)."""
    iso = day.isoformat()
    done = [_activity_load(a) for a in activities if _day(a) == iso] if day <= today else []
    planned = []
    if day >= today:
        planned = [_session_load(s, paces) for s in sessions
                   if s["date"] == iso and s["sport"] != "rest" and not (day == today and s.get("status") == "done")]
    return done + planned


def heavier(a: str, b: str) -> str:
    return a if ORDER.index(a) >= ORDER.index(b) else b


def for_day(day: date, today: date, activities: list[dict], sessions: list[dict], weight_kg: float | None) -> dict:
    """The targets of one day: its type, why, and the carbohydrate and protein range in g/kg and (with a weight) in g.
    `tomorrow` describes the next day's type and main session when it raises today's target."""
    paces = pace_by_sport(activities, today)
    loads = day_loads(day, today, activities, sessions, paces)
    own = classify(loads)
    nxt = day_loads(day + timedelta(days=1), today, activities, sessions, paces)
    nxt_type = classify(nxt)
    kind = heavier(own, BEFORE[nxt_type]) if nxt_type in BEFORE else own
    ranges = DAY_TYPES[kind]
    out = {
        "day": day.isoformat(),
        "day_type": kind,
        "own_type": own,
        "sessions": loads,
        "weight_kg": weight_kg,
        "carbs_per_kg": list(ranges["carbs"]),
        "protein_per_kg": list(ranges["protein"]),
        "carbs_g": [round(x * weight_kg) for x in ranges["carbs"]] if weight_kg else None,
        "protein_g": [round(x * weight_kg) for x in ranges["protein"]] if weight_kg else None,
        "tomorrow": None,
    }
    main = max((x for x in nxt if x["sport"] not in NOT_TRAINING), key=lambda x: x["minutes"], default=None)
    if main and nxt_type in ("long", "race"):
        out["tomorrow"] = {"day_type": nxt_type, **{k: main.get(k) for k in ("sport", "kind", "distance_km", "minutes")}}
    return out


def context(target: dict, activities: list[dict], now_hhmm: str | None) -> dict | None:
    """One line for Vandaag: tomorrow's long session or race (eat for it today), or right after a moderate or harder
    session today (protein within a few hours). None when there is nothing useful to say."""
    if target.get("tomorrow"):
        return {"line": "tomorrow", **target["tomorrow"], "carbs_per_kg": target["carbs_per_kg"]}
    if now_hhmm and target["own_type"] in ("moderate", "long", "race"):
        ends = []
        for a in activities:
            if _day(a) == target["day"] and a["sport"] not in NOT_TRAINING and a.get("moving_time_s"):
                h, m = int(a["start_local"][11:13]), int(a["start_local"][14:16])
                ends.append(h * 60 + m + a["moving_time_s"] // 60)
        now = int(now_hhmm[:2]) * 60 + int(now_hhmm[3:5])
        if ends and 0 <= now - max(ends) <= AFTER_TRAINING_H * 60:
            return {"line": "after_training"}
    return None


def per_kg(grams: float | None, weight_kg: float | None) -> float | None:
    return round(grams / weight_kg, 1) if grams is not None and weight_kg else None
