"""Trends: form (CTL/ATL/TSB), weekly volume per sport, Z2 running pace, VO2max, recovery, records and races.

Pure functions over plain data (see api/history.py): works on the file store and on tools/db.py.
Nothing here returns a sentence for the user: insights are codes with numbers, the page words them (web/lib/texts.ts).
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean
from typing import Callable

from api.dashboard import max_by_sport, resting_hr, sync_day
from api.readiness import baseline, normal_resting_hr
from tools import hrquality
from tools.analytics import fitness_series
from tools.summarize import run_sessions

StreamsFn = Callable[[str], "dict | None"]

RECORD_SPLITS = {"1k": "fastestSplit_1000", "5k": "fastestSplit_5000", "10k": "fastestSplit_10000", "21k": "fastestSplit_21098"}
RECORD_KM = {"1k": 1.0, "5k": 5.0, "10k": 10.0, "21k": 21.0975}
RACE_SHORT = 0.98  # a race the watch measured up to 2% short still counts for the record over that distance
RECENT_RECORD_DAYS = 14
RACE_WORDS = ("race", "wedstrijd", "marathon", "triathlon", "benchmark", "loop van", "run van")
RACE_MIN_KM = 5.0
RACE_HARD_SHARE = 0.85  # share of HR time in Z4-Z5: a sustained all-out effort, not a tempo run
RIEGEL = 1.06
PREDICT_KM = {"5k": 5.0, "10k": 10.0, "21k": 21.0975, "42k": 42.195}
SPLIT_KM = {"fastestSplit_5000": 5.0, "fastestSplit_10000": 10.0, "fastestSplit_21098": 21.0975}
MIN_Z2_SECONDS = 300  # a run needs at least 5 minutes in Z2 to count for the Z2 pace
MIN_SPEED = 1.5  # m/s; slower is walking or standing
# long run to aim for per goal distance (km): the usual rule of thumb, the page says it is one
LONG_RUN_TARGET = ((42.0, 30), (21.0, 18), (10.0, 12), (5.0, 8))


def week_of(day: str) -> str:
    """Monday of the ISO week, as YYYY-MM-DD."""
    d = date.fromisoformat(day[:10])
    return (d - timedelta(days=d.weekday())).isoformat()


def _raw(a: dict) -> dict:
    return ((a.get("sources") or {}).get("garmin") or {}).get("raw") or {}


def weekly_volume(activities: list[dict]) -> list[dict]:
    weeks: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: {"km": 0.0, "seconds": 0, "count": 0}))
    for a in activities:
        v = weeks[week_of(a["start_local"])][a["sport"]]
        v["km"] += a.get("distance_km") or 0
        v["seconds"] += a.get("moving_time_s") or 0
        v["count"] += 1
    if not weeks:
        return []
    out, wk, last = [], date.fromisoformat(min(weeks)), date.fromisoformat(max(weeks))
    while wk <= last:  # include empty weeks so charts show the gaps
        sports = weeks.get(wk.isoformat(), {})
        out.append({"week": wk.isoformat(), "sports": {s: {**v, "km": round(v["km"], 1)} for s, v in sports.items()}})
        wk += timedelta(weeks=1)
    return out


def standalone_runs(activities: list[dict]) -> list[dict]:
    """Runs not on a day with a swim or ride before them (triathlon/brick runs are not comparable)."""
    other = defaultdict(list)
    for a in activities:
        if a["sport"] in ("swim", "ride"):
            other[a["start_local"][:10]].append(a["start_local"])
    return [a for a in activities if a["sport"] == "run" and not any(t < a["start_local"] for t in other.get(a["start_local"][:10], []))]


def z2_speed(streams: dict, bounds: list[int]) -> tuple[float, int] | None:
    """Mean speed (m/s) and seconds spent in Z2 while moving, from the streams."""
    time, hr, v = streams.get("time") or [], streams.get("heartrate") or [], streams.get("velocity") or []
    if not (len(time) == len(hr) == len(v)) or len(time) < 2:
        return None
    lo, hi = bounds[0], bounds[1]
    dist = secs = 0.0
    for i in range(len(time) - 1):
        dt = min(time[i + 1] - time[i], 30)
        if hr[i] and lo <= hr[i] < hi and v[i] and v[i] >= MIN_SPEED:
            dist += v[i] * dt
            secs += dt
    if secs < MIN_Z2_SECONDS:
        return None
    return dist / secs, int(secs)


def z2_pace(activities: list[dict], streams_fn: StreamsFn, zones: dict, exclude: set[str] | None = None) -> list[dict]:
    """Weekly pace while in Z2 (standalone, outdoor runs). Falling pace at the same HR = better aerobic base.
    `exclude`: runs with an implausible wrist heart rate (hr_flags)."""
    bounds = (zones.get("run") or {}).get("bounds")
    if not bounds:
        return []
    weeks: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for a in standalone_runs(activities):
        if "treadmill" in (a.get("name") or "").lower() or (exclude and a["id"] in exclude):
            continue
        r = z2_speed(streams_fn(a["id"]) or {}, bounds)
        if r:
            weeks[week_of(a["start_local"])].append(r)
    out = []
    for wk in sorted(weeks):
        dist = sum(v * s for v, s in weeks[wk])
        secs = sum(s for _, s in weeks[wk])
        out.append({"week": wk, "pace_s_per_km": round(1000 * secs / dist), "runs": len(weeks[wk]), "z2_seconds": secs})
    return out


def vo2max(activities: list[dict], wellness: dict | None = None) -> list[dict]:
    """VO2max per day: Garmin's from its activities, else the watch's own estimate in wellness (Apple Health)."""
    by_day = {d: w["vo2max"] for d, w in (wellness or {}).items() if isinstance(w.get("vo2max"), (int, float))}
    for a in sorted(activities, key=lambda a: a["start_local"]):
        value = _raw(a).get("vO2MaxValue")
        if value:
            by_day[a["start_local"][:10]] = value
    return [{"date": d, "value": v} for d, v in sorted(by_day.items())]


RECOVERY_KEYS = ("resting_hr", "sleep_h", "body_battery_high", "stress_avg", "hrv", "sleep_resp", "sleep_stress", "bb_charged_sleep", "spo2_avg")
NORMAL_DAYS = 60  # the user's normal of a recovery value: the median of the last 60 days, as on Today


def recovery_normals(wellness: dict, today: date) -> dict:
    """{key: median of the last NORMAL_DAYS days up to today} per recovery value, None with fewer than 7 values:
    the reference next to each chart, as resting HR has on Today (api/readiness.py baseline)."""
    out = {}
    for k in RECOVERY_KEYS:
        v = baseline({d: _recovery_values(w) for d, w in wellness.items()}, k, today + timedelta(days=1), NORMAL_DAYS)
        out[k] = round(v, 1) if v is not None else None
    return out


def _recovery_values(w: dict) -> dict:
    """The recovery values of one day; HRV is the average of last night (wellness key hrv_last_night), or Apple's
    SDNN for a day from an Apple Health import (another measure: the chart says which one it shows)."""
    w = w or {}
    out = {k: w.get(k) for k in RECOVERY_KEYS}
    if out["hrv"] is None:
        out["hrv"] = w.get("hrv_last_night") if w.get("hrv_last_night") is not None else w.get("hrv_sdnn")
    return out


def recovery_weekly(wellness: dict) -> list[dict]:
    keys = RECOVERY_KEYS
    weeks: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for day, w in wellness.items():
        values = _recovery_values(w)
        for k in keys:
            if values[k] is not None:
                weeks[week_of(day)][k].append(values[k])
    out = []
    for wk in sorted(weeks):
        row = {"week": wk}
        for k in keys:
            vals = weeks[wk].get(k)
            row[k] = round(mean(vals), 1) if vals else None
        out.append(row)
    return out


def recovery_daily(wellness: dict) -> list[dict]:
    """One row per day with any recovery value, oldest first: the dense series behind the weekly averages, so the
    Trends charts can show short periods and a 7- or 28-day moving average."""
    out = []
    for day in sorted(wellness):
        w = _recovery_values(wellness[day])
        row = {k: (round(w[k], 2) if isinstance(w.get(k), float) else w.get(k)) for k in RECOVERY_KEYS}
        if any(v is not None for v in row.values()):
            out.append({"date": day[:10], **row})
    return out


SLEEP_STAGE_KEYS = {"deep": "deep_sleep_h", "light": "light_sleep_h", "rem": "rem_sleep_h", "awake": "awake_h"}


def sleep_stages(wellness: dict) -> list[dict]:
    """Per night with sleep stages, oldest first: {date, deep, light, rem, awake} in hours (the night that ended that
    morning). Trends adds them up per week or month and shows the share of each stage, as for the heart-rate zones."""
    out = []
    for day in sorted(wellness):
        w = wellness[day] or {}
        row = {stage: w.get(key) if isinstance(w.get(key), (int, float)) and w.get(key) > 0 else 0 for stage, key in SLEEP_STAGE_KEYS.items()}
        # Nights synced before light sleep was stored have only the total, deep and REM; Garmin's sleep time is
        # deep + light + REM, so light is the rest. Awake stays unknown (0) for those nights.
        total = w.get("sleep_h")
        if "light_sleep_h" not in w and row["deep"] + row["rem"] > 0 and isinstance(total, (int, float)) and total > row["deep"] + row["rem"]:
            row["light"] = total - row["deep"] - row["rem"]
        if row["deep"] + row["light"] + row["rem"] > 0:
            out.append({"date": day[:10], **{k: round(v, 2) for k, v in row.items()}})
    return out


def records(activities: list[dict]) -> dict:
    """Progression per record distance: every time a new best was set. Candidates are Garmin's fastest split in
    every run (fastestSplit_*) and runs that were races: a race the watch measured just short (up to 2%) has no
    split over the whole distance, so its moving time counts for that distance (source "race")."""
    race_ids = {i for r in races(activities) if r["sport"] == "run" for i in r["activity_ids"]}
    runs = sorted((a for a in activities if a["sport"] == "run"), key=lambda a: a["start_local"])
    out = {}
    for key, field in RECORD_SPLITS.items():
        km = RECORD_KM[key]
        best, rows = None, []
        for a in runs:
            options = []
            if _raw(a).get(field):
                options.append((_raw(a)[field], "split"))
            dist = a.get("distance_km") or 0
            if a["id"] in race_ids and a.get("moving_time_s") and km * RACE_SHORT <= dist < km:
                options.append((a["moving_time_s"], "race"))
            if not options:
                continue
            secs, source = min(options)
            if best is None or secs < best:
                best = secs
                row = {"date": a["start_local"][:10], "seconds": round(secs), "activity_id": a["id"], "source": source}
                if source == "race":
                    row["distance_km"] = dist
                rows.append(row)
        out[key] = rows
    return out


def recent_records(recs: dict, today: date, days: int = RECENT_RECORD_DAYS) -> list[dict]:
    """Records improved in the last `days` days (a first effort over a distance is no improvement)."""
    since = (today - timedelta(days=days - 1)).isoformat()
    out = []
    for key in RECORD_SPLITS:
        rows = recs.get(key) or []
        if len(rows) >= 2 and rows[-1]["date"] >= since:
            last = rows[-1]
            out.append({"key": key, "date": last["date"], "seconds": last["seconds"], "previous_seconds": rows[-2]["seconds"], "activity_id": last["activity_id"], "source": last["source"]})
    return out


def _hard_share(a: dict) -> float:
    z = a.get("hr_zones_s") or {}
    total = sum(z.values())
    return (z.get("Z4", 0) + z.get("Z5", 0)) / total if total else 0.0


def races(activities: list[dict]) -> list[dict]:
    """Triathlon days (swim, ride and run on one day), activities named like a race, and runs of 5 km or more
    with at least 85% of the time in Z4-Z5 (a race or time trial, even when Garmin calls it "Running")."""
    by_day = defaultdict(list)
    for a in activities:
        by_day[a["start_local"][:10]].append(a)
    out = []
    for day, items in sorted(by_day.items()):
        sports = {a["sport"] for a in items}
        if {"swim", "ride", "run"} <= sports:
            multi = [a for a in items if a["sport"] in ("swim", "ride", "run")]
            out.append(
                {
                    "date": day,
                    "name": "Triathlon",
                    "sport": "triathlon",
                    "seconds": sum(a.get("moving_time_s") or 0 for a in multi),
                    "distance_km": round(sum(a.get("distance_km") or 0 for a in multi), 1),
                    "activity_ids": [a["id"] for a in sorted(multi, key=lambda a: a["start_local"])],
                }
            )
            continue
        for a in items:
            name = (a.get("name") or "").lower()
            named = any(w in name for w in RACE_WORDS)
            hard = a["sport"] == "run" and (a.get("distance_km") or 0) >= RACE_MIN_KM and _hard_share(a) >= RACE_HARD_SHARE
            if named or hard:
                out.append(
                    {
                        "date": day,
                        "name": a.get("name") or "",  # the page words a heart-rate find as "race or test (name)"
                        "detected": "name" if named else "heart_rate",
                        "sport": a["sport"],
                        "seconds": a.get("moving_time_s"),
                        "distance_km": a.get("distance_km"),
                        "activity_ids": [a["id"]],
                    }
                )
    return out


def riegel(seconds: float, km: float, target_km: float) -> float:
    return seconds * (target_km / km) ** RIEGEL


def efforts(activities: list[dict], since: str) -> list[dict]:
    """Best efforts to predict from: Garmin's fastest splits in every run, plus whole runs that were races."""
    race_ids = {i for r in races(activities) if r["sport"] == "run" for i in r["activity_ids"]}
    out = []
    for a in standalone_runs(activities):  # a run after swimming or cycling says little about a standalone race
        if a["start_local"][:10] < since:
            continue
        raw = _raw(a)
        for field, km in SPLIT_KM.items():
            if raw.get(field):
                out.append({"date": a["start_local"][:10], "km": km, "seconds": raw[field], "activity_id": a["id"], "source": "split"})
        if a["id"] in race_ids and a.get("moving_time_s"):
            out.append({"date": a["start_local"][:10], "km": a["distance_km"], "seconds": a["moving_time_s"], "activity_id": a["id"], "source": "race"})
    return out


def _predict(pool: list[dict], km: float) -> dict | None:
    usable = [e for e in pool if e["km"] >= min(km, 5.0) * 0.99] or pool
    if not usable:
        return None
    longest = max(e["km"] for e in usable if e["km"] <= km * 1.01) if any(e["km"] <= km * 1.01 for e in usable) else min(e["km"] for e in usable)
    base = min((e for e in usable if abs(e["km"] - longest) < 0.3), key=lambda e: riegel(e["seconds"], e["km"], km))
    secs = riegel(base["seconds"], base["km"], km)
    return {"seconds": round(secs), "pace_s_per_km": round(secs / km), "from": base}


def predictions(activities: list[dict], today: date, days: int = 180) -> dict:
    """Race time per distance with Riegel (T2 = T1 x (D2/D1)^1.06), from the effort over the longest distance
    in the last `days` days (longer efforts predict a marathon far better than a fast kilometre). Riegel is
    optimistic for the marathon without enough long runs; the page says so."""
    pool = efforts(activities, (today - timedelta(days=days)).isoformat())
    out = {}
    for key, km in PREDICT_KM.items():
        p = _predict(pool, km)
        if p:
            out[key] = p
    return out


# --- the user's own goal ---------------------------------------------------------------------------------------------

_HALF = re.compile(r"halve\s*marathon|half\s*marathon|\bhm\b", re.I)
_FULL = re.compile(r"marathon", re.I)
_KM = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:km|k)\b", re.I)
_HMS = re.compile(r"\b(\d{1,2}):(\d{2}):(\d{2})\b")
_CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_HOURS = re.compile(r"\b(\d)\s*(?:u|uur|h)\s*(\d{1,2})?\b", re.I)
_MINUTES = re.compile(r"\b(\d{1,3})\s*(?:min|minuten|minutes)\b", re.I)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")
PLAUSIBLE_PACE = (150, 720)  # s/km: a goal time outside this is a misread


def _no_dates(text: str) -> str:
    return _ISO.sub(" ", _DMY.sub(" ", text))


def _goal_km(text: str) -> float | None:
    if _HALF.search(text):
        return 21.0975
    if _FULL.search(text):
        return 42.195
    m = _KM.search(_no_dates(text))
    return float(m.group(1).replace(",", ".")) if m else None


def _goal_seconds(text: str, km: float) -> int | None:
    def plausible(secs: int) -> bool:
        return PLAUSIBLE_PACE[0] <= secs / km <= PLAUSIBLE_PACE[1]

    if m := _HMS.search(text):
        secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        return secs if plausible(secs) else None
    if m := _CLOCK.search(text):
        a, b = int(m.group(1)), int(m.group(2))
        for secs in (a * 3600 + b * 60, a * 60 + b):  # h:mm for a marathon, m:ss for a 5 km
            if plausible(secs):
                return secs
        return None
    if m := _HOURS.search(text):
        secs = int(m.group(1)) * 3600 + int(m.group(2) or 0) * 60
        return secs if plausible(secs) else None
    if m := _MINUTES.search(text):
        secs = int(m.group(1)) * 60
        return secs if plausible(secs) else None
    return None


def _goal_date(text: str) -> str | None:
    try:
        if m := _ISO.search(text):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        if m := _DMY.search(text):
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None
    return None


def goal_from_plan(plan: dict | None, today: date) -> dict | None:
    """Running goal from the active plan's free fields `race` ("Stadsloop 10 km, 2026-10-18") and `goal`
    ("onder 45:00"): distance (km), target time (seconds or None) and race date (or None). None without a
    distance, or once the race date has passed: then nothing on the page assumes a goal."""
    if not plan:
        return None
    race, goal = (plan.get("race") or "").strip(), (plan.get("goal") or "").strip()
    km = _goal_km(race) or _goal_km(goal)
    if not km:
        return None
    day = _goal_date(race) or _goal_date(goal)
    if day and day < today.isoformat():
        return None
    secs = _goal_seconds(_no_dates(goal), km) or _goal_seconds(_no_dates(race), km)
    return {"km": km, "seconds": secs, "date": day, "text": " · ".join(t for t in (goal, race) if t)}


def long_run_target(goal_km: float) -> int | None:
    return next((target for km, target in LONG_RUN_TARGET if goal_km >= km), None)


# --- longest run per week ------------------------------------------------------------------------------------------


def longest_runs(activities: list[dict]) -> list[dict]:
    """Per week with runs: the longest run session (parts with <= 30 min between them merged), oldest first."""
    ids = {a["start_local"]: a["id"] for a in activities if a["sport"] == "run"}
    weeks: dict[str, dict] = {}
    for s in run_sessions(activities):
        wk = week_of(s["start_local"])
        if wk not in weeks or s["distance_km"] > weeks[wk]["km"]:
            weeks[wk] = {"week": wk, "date": s["start_local"][:10], "km": round(s["distance_km"], 2), "seconds": s["moving_time_s"], "parts": s["parts"], "activity_id": ids[s["start_local"]]}
    return [weeks[k] for k in sorted(weeks)]


# --- performance in other sports ------------------------------------------------------------------------------------

# Bests per sport: the longest session and the fastest over a few minimum distances (whole sessions, moving time).
# Swimming in pace per 100 m (lower is better), cycling in average speed. Distances Garmin got wrong (open water,
# tools/distance.py) arrive without a distance and are left out.
SPORT_BESTS = {"swim": (1.0, 2.0), "ride": (40.0, 90.0)}


def _speed(sport: str, a: dict) -> float:
    """Swim: seconds per 100 m; ride: km/h."""
    return a["moving_time_s"] / (a["distance_km"] * 10) if sport == "swim" else a["distance_km"] / (a["moving_time_s"] / 3600)


def sport_performance(activities: list[dict]) -> dict:
    """Per sport in SPORT_BESTS: `bests` (longest, then fastest from each minimum distance), `longest` per week and
    `speed` per week (time-weighted: all that week's distance over all its time, as pace or speed), oldest first."""
    out = {}
    for sport, minimums in SPORT_BESTS.items():
        acts = [a for a in activities if a["sport"] == sport and (a.get("distance_km") or 0) > 0 and (a.get("moving_time_s") or 0) > 0]
        if not acts:
            continue
        item = lambda a, key, value: {"key": key, "value": round(value, 2), "date": a["start_local"][:10], "km": round(a["distance_km"], 2), "seconds": a["moving_time_s"], "activity_id": a["id"]}
        longest = max(acts, key=lambda a: a["distance_km"])
        bests = [item(longest, "longest", longest["distance_km"])]
        for km in minimums:
            pool = [a for a in acts if a["distance_km"] >= km]
            if pool:
                best = min(pool, key=lambda a: _speed(sport, a)) if sport == "swim" else max(pool, key=lambda a: _speed(sport, a))
                bests.append(item(best, f"from_{km:g}", _speed(sport, best)))
        weeks: dict[str, dict] = {}
        for a in acts:
            w = weeks.setdefault(week_of(a["start_local"]), {"km": 0.0, "s": 0, "longest": None})
            w["km"] += a["distance_km"]
            w["s"] += a["moving_time_s"]
            if not w["longest"] or a["distance_km"] > w["longest"]["distance_km"]:
                w["longest"] = a
        order = sorted(weeks)
        out[sport] = {
            "bests": bests,
            "longest": [{"week": k, "km": round(weeks[k]["longest"]["distance_km"], 2), "date": weeks[k]["longest"]["start_local"][:10], "activity_id": weeks[k]["longest"]["id"]} for k in order],
            "speed": [{"week": k, "value": round(_speed(sport, {"distance_km": weeks[k]["km"], "moving_time_s": weeks[k]["s"]}), 2)} for k in order],
        }
    return out


# --- wrist HR quality ------------------------------------------------------------------------------------------------


def hr_flags(activities: list[dict], streams_fn: StreamsFn) -> dict[str, list[str]]:
    """Runs whose wrist heart rate looks implausible (tools/hrquality.py): id -> reason codes. The pace-HR relation
    comes from the user's own outdoor runs."""
    stats = {}
    for a in activities:
        if a["sport"] == "run":
            st = hrquality.run_stats(streams_fn(a["id"]) or {})
            if st:
                stats[a["id"]] = st
    by_id = {a["id"]: a for a in activities}
    outdoor = {i: st for i, st in stats.items() if "treadmill" not in (by_id[i].get("name") or "").lower()}
    relation = hrquality.fit_relation(list(outdoor.values()))
    out = {}
    for i, st in stats.items():
        if i not in outdoor:  # treadmill speed is a guess: only the stream checks
            st = {**st, "start_hr": None}
        reasons = hrquality.assess(st, relation)
        if reasons:
            out[i] = reasons
    return out


def _run_km(activities: list[dict], start: date, end: date) -> float:
    """Running km from `start` up to (not including) `end`."""
    lo, hi = start.isoformat(), end.isoformat()
    return sum(a.get("distance_km") or 0 for a in activities if a["sport"] == "run" and lo <= a["start_local"][:10] < hi)


def insights(form: list[dict], weekly: list[dict], activities: list[dict], today: date, goal: dict | None = None, recent: list[dict] | None = None) -> list[dict]:
    """Short, data-backed remarks about load and intensity: {level: goed|let_op|info, code, params}. The page words
    each code (web/lib/texts.ts); numbers stay numbers. Goal-based remarks only when the user has a goal."""
    out = []

    def add(level: str, code: str, **params):
        out.append({"level": level, "code": code, "params": params})

    for r in recent or []:
        add("good", "record_set", key=r["key"], seconds=r["seconds"], previous_seconds=r["previous_seconds"], date=r["date"], activity_id=r["activity_id"])
    if len(form) >= 8:
        now, week_ago = form[-1], form[-8]
        ramp = now["ctl"] - week_ago["ctl"]
        acwr = now["atl"] / now["ctl"] if now["ctl"] else None
        if acwr and acwr > 1.5:
            add("watch", "acwr_high", atl=round(now["atl"]), ctl=round(now["ctl"]), ratio=round(acwr, 1))
        elif ramp > 6:
            add("watch", "ramp_fast", ramp=round(ramp, 1))
        elif now.get("form_pct") is not None and now["form_pct"] > 5:  # api/dashboard.py FORM_BANDS: fresh
            add("info", "fresh", tsb=round(now["tsb"]), pct=now["form_pct"])
    since = (today - timedelta(days=28)).isoformat()
    four = [a for a in activities if a["sport"] == "run" and a["start_local"][:10] > since]
    secs = {z: sum((a.get("hr_zones_s") or {}).get(z, 0) for a in four) for z in ("Z1", "Z2", "Z3", "Z4", "Z5")}
    total = sum(secs.values())
    if total > 3600:
        easy = round((secs["Z1"] + secs["Z2"]) / total * 100)
        grey = round(secs["Z3"] / total * 100)
        add("good" if easy >= 75 else "watch", "easy_share", easy_pct=easy, grey_pct=grey, hard_pct=100 - easy - grey)
    sessions = [s for s in run_sessions(activities) if s["start_local"][:10] > since]
    if sessions:
        km = round(max(s["distance_km"] for s in sessions), 1)
        target = long_run_target(goal["km"]) if goal else None
        if target:
            add("good" if km >= target else "info", "long_run_goal", km=km, target_km=target, goal_km=goal["km"])
        else:
            add("info", "longest_run", km=km)
    if goal and goal.get("seconds"):
        p = _predict(efforts(activities, (today - timedelta(days=180)).isoformat()), goal["km"])
        if p:
            add("info", "goal_prediction", goal_km=goal["km"], goal_seconds=goal["seconds"], predicted_seconds=p["seconds"], from_km=p["from"]["km"], from_date=p["from"]["date"])
    # running volume: the four whole weeks before this week (Europe/Amsterdam, `today`), and this week so far
    monday = date.fromisoformat(week_of(today.isoformat()))
    avg = _run_km(activities, monday - timedelta(weeks=4), monday) / 4
    if avg:
        add("info", "run_volume", avg_km=round(avg, 1), week_km=round(_run_km(activities, monday, today + timedelta(days=1)), 1), week_start=monday.isoformat())
    return out


def build_trends(
    activities: list[dict],
    wellness: dict,
    zones: dict,
    streams_fn: StreamsFn,
    today: date,
    rhr_fallback: float | None = None,
    plan: dict | None = None,
    last_sync: str | None = None,
) -> dict:
    """Everything the Trends page shows. `plan`: the active plan, for the user's own goal (goal_from_plan).
    `last_sync`: the store's sync text; after a sync older than yesterday the form series stops at the last synced
    day, as on the dashboard (api/dashboard.py build_dashboard), because the days since are unknown, not rest days."""
    synced = sync_day(last_sync)
    stopped = synced is not None and synced < today - timedelta(days=1)
    form = fitness_series(activities, resting_hr(wellness, today, rhr_fallback), max_by_sport(zones, activities), end=synced if stopped else today)
    weekly = weekly_volume(activities)
    flags = hr_flags(activities, streams_fn)
    recs = records(activities)
    recent = recent_records(recs, today)
    goal = goal_from_plan(plan, today)
    by_id = {a["id"]: a for a in activities}
    return {
        "today": today.isoformat(),
        "form": form,
        "form_until": form[-1]["date"] if form else None,
        "stopped_at_sync": stopped,
        "weekly": weekly,
        "z2_pace": z2_pace(activities, streams_fn, zones, exclude=set(flags)),
        "vo2max": vo2max(activities, wellness),
        "recovery_weekly": recovery_weekly(wellness),
        "recovery_daily": recovery_daily(wellness),
        "sleep_stages": sleep_stages(wellness),
        "recovery_normals": {**recovery_normals(wellness, today), "resting_hr": normal_resting_hr(wellness, today + timedelta(days=1), rhr_fallback)[0]},
        "records": recs,
        "recent_records": recent,
        "races": races(activities),
        "predictions": predictions(activities, today),
        "longest_runs": longest_runs(activities),
        "sport_performance": sport_performance(activities),
        "hr_flags": sorted(
            ({"id": i, "date": by_id[i]["start_local"][:10], "name": by_id[i].get("name") or "", "reasons": r} for i, r in flags.items()),
            key=lambda f: f["date"],
        ),
        "goal": goal,
        # the thresholds behind races, records and predictions, so the page explains them with the real numbers
        "rules": {
            "race_min_km": RACE_MIN_KM,
            "race_hard_pct": round(RACE_HARD_SHARE * 100),
            "predict_days": 180,
            "riegel": RIEGEL,
            "race_short_pct": round((1 - RACE_SHORT) * 100),
            "recent_record_days": RECENT_RECORD_DAYS,
        },
        "insights": insights(form, weekly, activities, today, goal, recent),
    }
