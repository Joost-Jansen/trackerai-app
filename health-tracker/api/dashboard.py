"""Data for the dashboard page: zones, volume, form, recent activities, recovery."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from api.plans import activity_weeks, parse_date
from tools.analytics import fitness_series
from tools.summarize import run_sessions
from tools.zones import NAMES

DEFAULT_RHR = 60  # population average; used only without the user's own resting HR (sleep data or profile)
# Load indicator: acute (ATL, 7 days) against chronic (CTL, 42 days) load. The 0.8-1.3 band is the "sweet spot" of the
# acute:chronic workload ratio in Gabbett (2016), Br J Sports Med 50:273-280. Used here only as a soft guide to how fast
# load changes against what the user is used to, not as an injury prediction.
ACWR_LOW = 0.8
ACWR_HIGH = 1.3
# Ramp rate: CTL change over 7 days. Coaching guidance for CTL/ATL models (Coggan, TrainingPeaks) calls a rise of
# roughly 5-8 points per week steep but sustainable; above that the build is faster than most people absorb.
RAMP_HIGH = 8.0
LOAD_MIN_DAYS = 28  # CTL is a 42-day average: with less than four weeks of data the ratio says little
LOAD_MIN_CTL = 5.0  # below this (hardly any training) a ratio swings wildly on a single session
# A plan session is a race when its kind says so (same words as web/components/plan/plan.ts RACE_KIND).
# Whole words only and not a pace: "marathontempo", "race pace" and "marathon pace" are training, "halve marathon" a race.
RACE_KIND = re.compile(r"\b(wedstrijd|race|marathon|triathlon)\b(?!\s*-?\s*(tempo|pace))", re.I)
# Dates in the free race field, in the order api.plans.parse_date tries them: 2026-10-18, 18-10(-2026), 18 okt (2026).
RACE_FIELD_DATES = (r"\d{4}-\d{1,2}-\d{1,2}", r"\b\d{1,2}[-/.]\d{1,2}(?:[-/.]\d{2,4})?\b", r"\b\d{1,2}\s+[a-z]{3}[a-z]*\.?(?:\s+\d{4})?")
SUMMARY_FIELDS = ("id", "start_local", "sport", "name", "distance_km", "moving_time_s", "avg_hr", "max_hr", "elevation_gain_m", "hr_zones_s",
                  "open_water", "distance_doubtful", "gps_distance_km", "distance_manual")  # tools/distance.py


def _day(a: dict) -> date:
    return date.fromisoformat(a["start_local"][:10])


def resting_hr(wellness: dict, today: date, fallback: float | None = None) -> float:
    """The resting HR the training load (TRIMP) uses: your normal up to and including last night
    (api/readiness.py normal_resting_hr: 60 days, else the last 7 nights, else Settings), else a population value."""
    from api.readiness import normal_resting_hr  # api.readiness has no app imports; kept local like recent_items

    value, _ = normal_resting_hr(wellness, today + timedelta(days=1), fallback)
    return value if value is not None else DEFAULT_RHR


def max_by_sport(zones: dict, activities: list[dict] | None = None) -> dict:
    """Max HR per sport from the user's zones; for sports without zones, the highest max HR in their own activities."""
    out = {sport: z["max_hr"] for sport, z in zones.items() if isinstance(z, dict) and z.get("max_hr")}
    for a in activities or []:
        if a.get("max_hr") and a["sport"] not in zones:
            out[a["sport"]] = max(out.get(a["sport"], 0), a["max_hr"])
    return out


# Form as % of fitness (tools/analytics.py form_pct), the bands intervals.icu uses: above +20% fitness is slipping
# away, +5 to +20 fresh, -10 to +5 neutral, -30 to -10 the range where training builds fitness, below -30 high risk.
FORM_BANDS = ((20, "transition"), (5, "fresh"), (-10, "neutral"), (-30, "optimal"))


def form_status(pct: float | None) -> str:
    if pct is None:
        return "neutral"
    return next((name for lower, name in FORM_BANDS if pct > lower), "high_risk")


def _zone_share(activities: list[dict]) -> dict:
    per_sport: dict[str, dict[str, int]] = defaultdict(lambda: {z: 0 for z in NAMES})
    for a in activities:
        for z, secs in (a.get("hr_zones_s") or {}).items():
            per_sport[a["sport"]][z] += secs
    out = {sport: _share(secs) for sport, secs in per_sport.items() if sum(secs.values())}
    if out:
        # every sport's seconds were counted with its own zones, so the total is a plain sum
        out["all"] = _share({z: sum(v["seconds"][z] for v in out.values()) for z in NAMES})
    return out


def _share(secs: dict[str, int]) -> dict:
    total = sum(secs.values())
    return {"seconds": secs, "total_s": total, "pct": {z: round(s / total * 100, 1) for z, s in secs.items()}}


def _volume(activities: list[dict], weeks: int = 1) -> dict:
    out: dict[str, dict] = defaultdict(lambda: {"count": 0, "km": 0.0, "seconds": 0})
    for a in activities:
        v = out[a["sport"]]
        v["count"] += 1
        v["km"] += a.get("distance_km") or 0
        v["seconds"] += a.get("moving_time_s") or 0
    return {
        sport: {"count": round(v["count"] / weeks, 1) if weeks > 1 else v["count"], "km": round(v["km"] / weeks, 1), "seconds": round(v["seconds"] / weeks)}
        for sport, v in out.items()
    }


def sync_day(last_sync: str | None) -> date | None:
    """The day of the last sync from the store's text ("2026-09-30 06:02", maybe "; mislukt: ..."), None if unknown."""
    m = re.match(r"\d{4}-\d{2}-\d{2}", last_sync or "")
    try:
        return date.fromisoformat(m[0]) if m else None
    except ValueError:
        return None


def load_indicator(series: list[dict]) -> dict:
    """Acute vs chronic load from a fitness series (tools.analytics.fitness_series): `acwr` = ATL / CTL at the last
    day, `ramp` = CTL change over 7 days, `band` low|build|high|unknown and, for high, `reason` ratio|ramp."""
    thresholds = {"low": ACWR_LOW, "high": ACWR_HIGH, "ramp_high": RAMP_HIGH}
    if len(series) < LOAD_MIN_DAYS or series[-1]["ctl"] < LOAD_MIN_CTL:
        return {"band": "unknown", "acwr": None, "ramp": None, "reason": None, "thresholds": thresholds}
    now, week_ago = series[-1], series[-8]
    acwr = round(now["atl"] / now["ctl"], 2)
    ramp = round(now["ctl"] - week_ago["ctl"], 1)
    reason = "ratio" if acwr > ACWR_HIGH else "ramp" if ramp > RAMP_HIGH else None
    band = "high" if reason else "low" if acwr < ACWR_LOW else "build"
    return {"band": band, "acwr": acwr, "ramp": ramp, "reason": reason, "thresholds": thresholds}


def today_tsb(form: dict | None) -> float | None:
    """Form to judge today by (readiness): None when the series stopped at an older sync."""
    return form["tsb"] if form and not form.get("stopped_at_sync") else None


def today_form_pct(form: dict | None) -> float | None:
    return form.get("pct") if form and not form.get("stopped_at_sync") else None


def plan_week(sessions: list[dict], activities: list[dict], today: date, synced: date | None = None) -> dict:
    """This week (Monday to Sunday) of a plan whose sessions went through api.plans.match_sessions: per sport the planned
    km and time (planned time only from sessions with a duration) against the km and time of every activity of that
    sport this week, in a session or not, and the number of sessions done, missed and still to come (today's open
    session counts as to come). Sports of the plan without a session this week show up when there was an activity.
    A past session after the last synced day (`synced`) is `unsynced`, not missed: what happened that day is not known
    yet. Rest days are left out."""
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    week = [s for s in sessions if s["sport"] != "rest" and monday.isoformat() <= s["date"] <= sunday.isoformat()]
    done = activity_weeks(activities, {s["sport"] for s in sessions if s["sport"] != "rest"}).get(monday.isoformat(), {})
    empty = {"planned_km": 0.0, "done_km": 0.0, "planned_s": 0, "done_s": 0, "sessions": 0, "done": 0}
    sports: dict[str, dict] = {sport: {**empty, "done_km": v["km"], "done_s": v["s"]} for sport, v in done.items()}
    for s in week:
        row = sports.setdefault(s["sport"], dict(empty))
        row["sessions"] += 1
        row["planned_km"] += s.get("distance_km") or 0
        row["planned_s"] += (s.get("duration_min") or 0) * 60
        if s.get("status") == "done":
            row["done"] += 1
    for row in sports.values():
        row["planned_km"], row["done_km"] = round(row["planned_km"], 1), round(row["done_km"], 1)
    after_sync = synced.isoformat() if synced else "9999"
    status = ["unsynced" if s.get("status") == "missed" and s["date"] > after_sync else s.get("status") for s in week]
    counts = {
        "total": len(week),
        "done": status.count("done"),
        "missed": status.count("missed"),
        "upcoming": status.count("planned") + status.count("today"),
        "unsynced": status.count("unsynced"),
    }
    return {"start": monday.isoformat(), "end": sunday.isoformat(), "sports": sports, "sessions": counts}


def _race_field(text: str | None, year: int) -> tuple[str, str | None]:
    """Name and ISO date from the plan's free race field ("Marathon, 2026-10-18"); the date is None if there is none."""
    text = (text or "").strip()
    for pattern in RACE_FIELD_DATES:
        m = re.search(pattern, text, re.I)
        if not m:
            continue
        try:
            day = parse_date(m[0], year)
        except ValueError:  # 31-02: looks like a date, is none
            day = None
        if day:
            return re.sub(r"\s{2,}", " ", (text[: m.start()] + " " + text[m.end() :]).strip(" ,·–-")).strip(" ,·–-"), day
    return text, None


def next_race(plan: dict, sessions: list[dict], today: date) -> dict | None:
    """The next race of the active plan: the date in its race field or a session of a race kind, whichever comes first
    from today. `name` (from the race field) only for the plan's own race; `distance_km` and `sport` from the race
    session that day (else the longest session that day). None when no race date lies ahead."""
    ordered = sorted(sessions, key=lambda s: s["date"])
    year = date.fromisoformat(ordered[0]["date"]).year if ordered else today.year
    name, field_day = _race_field(plan.get("race"), year)
    races = [s for s in ordered if s["sport"] != "rest" and RACE_KIND.search(s.get("kind") or "")]
    goal_day = field_day or (races[-1]["date"] if races else None)
    ahead = sorted({s["date"] for s in races} | ({field_day} if field_day else set()))
    ahead = [d for d in ahead if d >= today.isoformat()]
    if not ahead:
        return None
    day = ahead[0]
    on_day = [s for s in ordered if s["date"] == day and s["sport"] != "rest"]
    main = next((s for s in on_day if RACE_KIND.search(s.get("kind") or "")), None) or max(on_day, key=lambda s: s.get("distance_km") or 0, default=None)
    return {
        "date": day,
        "days": (date.fromisoformat(day) - today).days,
        "name": (name or None) if day == goal_day else None,
        "distance_km": (main or {}).get("distance_km"),
        "sport": (main or {}).get("sport"),
    }


def summary(a: dict) -> dict:
    return {k: a.get(k) for k in SUMMARY_FIELDS if a.get(k) is not None}


def recent_items(activities: list[dict], n: int = 6) -> list[dict]:
    """The newest `n` items for "Laatste activiteiten": runs with <= 30 min between them are one item (tools.summarize
    run_sessions) with `parts` and `activity_ids`; `race: True` when an activity (or one of the parts) is a race by the
    same rules as Trends (api.trends.races)."""
    from api.trends import races  # api.trends imports this module, so not at the top

    race_ids = {i for r in races(activities) for i in r["activity_ids"]}
    runs = sorted((a for a in activities if a["sport"] == "run"), key=lambda a: a["start_local"])
    items, i = [], 0
    for session in run_sessions(activities):  # same order as `runs`; each session covers the next `parts` runs
        parts = runs[i : i + session["parts"]]
        i += session["parts"]
        item = summary(parts[0])
        if len(parts) > 1:
            item.update({k: session[k] for k in ("distance_km", "moving_time_s", "avg_hr", "hr_zones_s") if session.get(k) is not None})
            max_hr = [a["max_hr"] for a in parts if a.get("max_hr")]
            gain = [a["elevation_gain_m"] for a in parts if a.get("elevation_gain_m") is not None]
            if max_hr:
                item["max_hr"] = max(max_hr)
            if gain:
                item["elevation_gain_m"] = round(sum(gain), 1)
            item["parts"] = len(parts)
            item["activity_ids"] = [a["id"] for a in parts]
        if any(a["id"] in race_ids for a in parts):
            item["race"] = True
        items.append(item)
    for a in activities:
        if a["sport"] != "run":
            items.append(dict(summary(a), race=True) if a["id"] in race_ids else summary(a))
    return sorted(items, key=lambda x: x["start_local"], reverse=True)[:n]


def build_dashboard(activities: list[dict], wellness: dict, zones: dict, today: date, last_sync: str, rhr_fallback: float | None = None) -> dict:
    monday = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    week = [a for a in activities if monday <= _day(a) <= today]
    month = [a for a in activities if month_start <= _day(a) <= today]
    prev4 = [a for a in activities if monday - timedelta(weeks=4) <= _day(a) < monday]

    rhr = resting_hr(wellness, today, rhr_fallback)
    # After a sync older than yesterday the days since are unknown, not rest: the series stops at the last synced day.
    synced = sync_day(last_sync)
    stopped = synced is not None and synced < today - timedelta(days=1)
    series = fitness_series(activities, rhr, max_by_sport(zones, activities), end=synced if stopped else today)
    form = None
    if series:
        now, peak = series[-1], max(series, key=lambda r: r["ctl"])
        form = {
            "ctl": now["ctl"],
            "atl": now["atl"],
            "tsb": now["tsb"],
            "pct": now["form_pct"],
            "status": form_status(now["form_pct"]),
            "ctl_peak": peak["ctl"],
            "ctl_peak_date": peak["date"],
            "until": now["date"],
            "stopped_at_sync": stopped,
            "load": load_indicator(series),
            "series": series[-91:],
        }

    recent_days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    from api.readiness import normal_resting_hr

    normal_rhr, normal_rhr_source = normal_resting_hr(wellness, today + timedelta(days=1), rhr_fallback)

    return {
        "today": today.isoformat(),
        "last_sync": last_sync,
        "zone_bounds": {sport: z["bounds"] for sport, z in zones.items()},
        "zone_estimates": sorted(sport for sport, z in zones.items() if isinstance(z, dict) and z.get("estimate")),
        "zones_set": sorted(zones),
        "zones": {"week": _zone_share(week), "month": _zone_share(month)},
        "volume": {"week": _volume(week), "avg4w": _volume(prev4, weeks=4)},
        "form": form,
        "recent": recent_items(activities, 20),  # Today shows as many as fit at the end of a column
        "recovery": {
            "days": [dict(wellness[d], date=d) for d in recent_days if d in wellness],
            "baseline_rhr": normal_rhr,
            "baseline_rhr_source": normal_rhr_source,
        },
        "upcoming": [],
    }
